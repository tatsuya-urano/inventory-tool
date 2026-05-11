"""
⬆️ 旧→新 在庫同期(CSV/エクセル取込)

旧在庫管理シートからエクスポートしたCSVを取り込み、
04_在庫管理 の **G列(月初在庫)** に在庫数を上書きする。

仕様:
- CSVのSKU列(任意の列名OK・マッピングで指定) と マスタA列/AE/AF/AG を突合
- マッチした行の04 G列を CSVの在庫数で上書き
- マスタにないSKUは未マッチ警告のみ・書き込まない
- ドライランモード対応
"""
from io import StringIO

import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="旧→新 在庫同期", page_icon="⬆️", layout="wide")
st.title("⬆️ 旧→新 在庫同期")
ui.sidebar_common()

# ===========================================================
# 使い方
# ===========================================================
with st.expander("📌 このページでできること", expanded=True):
    st.markdown(
        """
**旧在庫管理シートが正しい現在庫だった場合に、新ツールの在庫数を旧シートに合わせる** ためのページ。

### 🎯 動作
1. 旧シートから**現在庫数を含むCSV/Excel**をアップロード
2. **マッピング**で「SKU列」「在庫数列」を指定
3. **🔍 ドライラン**でマッチ件数を確認
4. **⚡ 同期実行** で 04_在庫管理 の **G列(月初在庫)** に値を上書き

### ⚠️ 注意点
- G列が直接書き換わるので、F列(自社倉庫在庫の数式) も連動して変わる
- 既に当月の入荷/廃棄/売上が入っているSKUは、F = G + I - J - 売上 - O で計算されるため
  「今日始まった段階(月初)」状態のCSVを使うのが正解
- マスタにないSKUはスキップ・警告表示のみ
"""
    )

st.markdown("---")

# ===========================================================
# CSV/Excel取込
# ===========================================================
st.markdown("### 📥 CSV/Excel 取込")

uploaded = st.file_uploader(
    "ファイル選択 (CSV/TSV/Excel)", type=["csv", "tsv", "xlsx", "xls"],
    key="stock_sync_uploader",
)
pasted = st.text_area("または貼り付け(タブ or カンマ区切り)", height=120, key="stock_sync_paste")

def _decode_with_fallback(raw_bytes: bytes) -> tuple[str, str]:
    """複数の文字コードを試して最初に成功したものを返す"""
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis", "euc_jp"):
        try:
            return raw_bytes.decode(enc), enc
        except UnicodeDecodeError:
            continue
    # 最後の手段
    return raw_bytes.decode("utf-8", errors="replace"), "utf-8(replace)"


new_data = None
detected_enc = None
if uploaded is not None:
    try:
        if uploaded.name.lower().endswith((".xlsx", ".xls")):
            new_data = pd.read_excel(uploaded, dtype=str).fillna("")
        else:
            raw = uploaded.read()
            content, detected_enc = _decode_with_fallback(raw)
            sep = "\t" if content.split("\n")[0].count("\t") > content.split("\n")[0].count(",") else ","
            new_data = pd.read_csv(StringIO(content), sep=sep, dtype=str).fillna("")
        msg = f"読込: {len(new_data)}行 × {len(new_data.columns)}列"
        if detected_enc:
            msg += f" / 文字コード: {detected_enc}"
        st.success(msg)
    except Exception as e:
        st.error(f"読込失敗: {e}")
elif pasted.strip():
    try:
        first = pasted.split("\n")[0]
        sep = "\t" if first.count("\t") > first.count(",") else ","
        new_data = pd.read_csv(StringIO(pasted), sep=sep, dtype=str).fillna("")
        st.success(f"読込: {len(new_data)}行 × {len(new_data.columns)}列")
    except Exception as e:
        st.error(f"読込失敗: {e}")

if new_data is not None and not new_data.empty:
    st.markdown("**📋 取込プレビュー(先頭10行)**")
    st.dataframe(new_data.head(10), use_container_width=True, hide_index=True)

    # ===========================================================
    # 🔗 列マッピング
    # ===========================================================
    st.markdown("### 🔗 列マッピング")
    csv_cols = list(new_data.columns)

    # SKU候補と在庫数候補を自動推定
    sku_kw = ["商品コード", "SKU", "管理番号", "コード", "code", "sku"]
    qty_kw = ["在庫", "残在庫", "現在庫", "実在庫", "stock", "数量", "在庫数"]

    sku_idx = next(
        (i for i, c in enumerate(csv_cols) if any(kw in str(c) for kw in sku_kw)),
        0,
    )
    qty_idx = next(
        (i for i, c in enumerate(csv_cols) if any(kw in str(c) for kw in qty_kw)),
        len(csv_cols) - 1,
    )

    cc1, cc2 = st.columns(2)
    with cc1:
        sel_sku = st.selectbox(
            "SKU列(必須・商品コード)", options=csv_cols, index=sku_idx,
            key="sync_sku_col",
        )
    with cc2:
        sel_qty = st.selectbox(
            "在庫数列(必須)", options=csv_cols, index=qty_idx,
            key="sync_qty_col",
        )

    # ===========================================================
    # マスタロード&ルックアップ辞書
    # ===========================================================
    with st.spinner("マスタ・在庫読込中..."):
        master = sheets.load_master()
        inv = sheets.load_inventory()

    if master.empty or inv.empty:
        st.error("マスタ or 04_在庫管理 が空")
        st.stop()

    # マスタA列(主) AE楽天SKU(30) AF FBM(31) AG FBA(32) を全部キーに
    master_keys: dict[str, str] = {}  # 任意SKU文字列 → マスタA列(主)
    for _, mr in master.iterrows():
        a = str(mr.iloc[0]).strip() if len(mr) > 0 else ""
        if not a:
            continue
        # A列自身もキーに
        if a not in master_keys:
            master_keys[a] = a
        for col_idx in (30, 31, 32):
            if col_idx < len(mr):
                v = str(mr.iloc[col_idx]).strip()
                if v and v not in master_keys:
                    master_keys[v] = a

    # 04のA列→行番号
    inv_code_to_row: dict[str, int] = {}
    for i, code in enumerate(inv.iloc[:, 0].astype(str).str.strip().tolist(), start=7):
        if code:
            inv_code_to_row[code] = i

    # ===========================================================
    # マッチング試算
    # ===========================================================
    def _f_n(v):
        try:
            return float(str(v or "").replace(",", "").strip() or 0)
        except (ValueError, TypeError):
            return 0.0

    matched_updates: list[tuple] = []  # (inv_row, sku, qty, master_a) → 04に書き込む
    master_only: list[tuple] = []      # マスタにはあるが04にない (sku, qty, master_a)
    truly_unmatched: list[tuple] = []  # マスタにすらない (sku, qty)

    for _, r in new_data.iterrows():
        sku = str(r[sel_sku]).strip()
        qty_v = r[sel_qty]
        if not sku:
            continue
        try:
            qty = int(_f_n(qty_v))
        except (ValueError, TypeError):
            qty = 0

        master_a = master_keys.get(sku)
        if not master_a and sku.startswith("0"):
            master_a = master_keys.get(sku.lstrip("0"))

        if not master_a:
            # マスタにすらない
            truly_unmatched.append((sku, qty))
            continue

        # マスタA列(主)が04にあるか
        if master_a in inv_code_to_row:
            matched_updates.append((inv_code_to_row[master_a], sku, qty, master_a))
        else:
            # マスタにはあるが04にない (コバリ子等)
            master_only.append((sku, qty, master_a))

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("CSV行数", len(new_data))
    mc2.metric("✅ マッチ", len(matched_updates))
    mc3.metric("⚠ マスタのみ", len(master_only),
               help="マスタA/AE/AF/AGに存在するが、04_在庫管理にない(コバリ子等)。書込みできないが、マスタ的にはOK")
    mc4.metric("❌ 未登録", len(truly_unmatched),
               help="マスタにも04にもない")

    if truly_unmatched:
        with st.expander(f"❌ マスタ未登録SKU {len(truly_unmatched)}件 (CSVダウンロード可)", expanded=True):
            df_un = pd.DataFrame(truly_unmatched, columns=["SKU", "在庫数"])
            st.dataframe(df_un, use_container_width=True, hide_index=True, height=300)
            csv_bytes = df_un.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                f"📥 マスタ未登録SKU CSVダウンロード ({len(truly_unmatched)}件)",
                csv_bytes,
                file_name=f"truly_unmatched_{len(truly_unmatched)}rows.csv",
                mime="text/csv",
                use_container_width=True,
            )

    if master_only:
        with st.expander(f"⚠ マスタにあるが04に無いSKU {len(master_only)}件 (コバリ子など)"):
            df_m = pd.DataFrame(master_only, columns=["CSV SKU", "在庫数", "マスタA列"])
            st.dataframe(df_m, use_container_width=True, hide_index=True, height=300)
            csv_bytes_m = df_m.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                f"📥 マスタのみSKU CSVダウンロード ({len(master_only)}件)",
                csv_bytes_m,
                file_name=f"master_only_{len(master_only)}rows.csv",
                mime="text/csv",
                use_container_width=True,
            )

    if matched_updates:
        with st.expander(f"✅ 同期予定 {len(matched_updates)}件 (先頭20件)"):
            preview = [
                {"04行": r, "CSV SKU": s, "→マスタコード": m, "新G列(月初在庫)": q}
                for r, s, q, m in matched_updates[:20]
            ]
            st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)

    # ===========================================================
    # 実行
    # ===========================================================
    st.markdown("---")
    dry_run = st.checkbox(
        "🔍 ドライランモード(書込なしで確認)",
        value=True, key="sync_dry_run",
    )

    btn_label = "🔍 ドライラン実行" if dry_run else "⚡ 04 G列に同期実行"
    btn_type = "secondary" if dry_run else "primary"

    add_master_only = st.checkbox(
        "📌 マスタにあるが04にないSKUも04に新規行を追加(通常はOFF推奨・コバリ子は04に入れない方針)",
        value=False,
        key="sync_add_master_only",
        help="ON: コバリ子等を04末尾にA(コード)/B(タイトル)/C(物流ルート)/G(月初在庫)で新規追加。"
             "通常運用ではOFFのまま、マッチ分(✅)だけ書き込む",
    )

    total_writes = len(matched_updates) + (len(master_only) if add_master_only else 0)
    if total_writes == 0:
        st.info("書込み対象がありません")

    if total_writes and st.button(btn_label, type=btn_type, key="sync_apply",
                                   use_container_width=True):
        if dry_run:
            st.info(
                f"🔍 ドライラン: 既存04行 G列更新={len(matched_updates)}件 / "
                f"04新規行追加={len(master_only) if add_master_only else 0}件 "
                f"(実際は書込みしてません)"
            )
        else:
            with st.spinner(f"{total_writes}件 書込中(チャンク分割で実行)..."):
                ss = sheets.get_spreadsheet()
                inv_ws = ss.worksheet("04_在庫管理")

                # 既存04行 G列更新 (チャンク分割 + 個別リトライ)
                ok_count = 0
                err_count = 0
                err_samples: list[str] = []
                if matched_updates:
                    import time as _time
                    requests = [
                        {"range": f"G{r}", "values": [[q]]}
                        for r, _, q, _ in matched_updates
                    ]
                    # 100件ずつ分割
                    CHUNK = 100
                    chunks = [requests[i:i + CHUNK] for i in range(0, len(requests), CHUNK)]
                    progress = st.progress(0, text=f"0/{len(requests)} 書込み中...")
                    for ci, chunk in enumerate(chunks):
                        # チャンク単位リトライ(429対応)
                        for attempt in range(4):
                            try:
                                sheets.safe_batch_update(inv_ws, chunk, value_input_option="USER_ENTERED")
                                ok_count += len(chunk)
                                break
                            except Exception as e:
                                err_msg = str(e)
                                if "429" in err_msg or "Quota" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                                    # レート制限 → 指数バックオフ
                                    wait = 2 ** attempt * 5  # 5,10,20,40 秒
                                    progress.progress(
                                        ok_count / len(requests),
                                        text=f"⚠ レート制限、{wait}秒待機中... ({ok_count}/{len(requests)}完了)",
                                    )
                                    _time.sleep(wait)
                                    continue
                                # それ以外のエラーは1件ずつ試行(部分成功狙い)
                                if attempt == 3:
                                    err_count += len(chunk)
                                    if len(err_samples) < 3:
                                        err_samples.append(err_msg[:150])
                                    break
                                _time.sleep(2)
                        progress.progress(
                            min(ok_count, len(requests)) / len(requests),
                            text=f"{ok_count}/{len(requests)}件 完了",
                        )
                    progress.empty()

                    # マスタのみ → 04末尾に新規行追加
                    added_count = 0
                    if add_master_only and master_only:
                        try:
                            master_a_to_info: dict[str, dict] = {}
                            for _, mr in master.iterrows():
                                a = str(mr.iloc[0]).strip() if len(mr) > 0 else ""
                                if not a:
                                    continue
                                master_a_to_info[a] = {
                                    "title": str(mr.iloc[1]).strip() if len(mr) > 1 else "",
                                    "route": str(mr.iloc[6]).strip() if len(mr) > 6 else "",
                                }

                            inv_a = inv_ws.col_values(1)
                            last_inv_row = max(
                                [i + 1 for i, v in enumerate(inv_a) if str(v).strip() and i + 1 >= 7] + [6]
                            )
                            next_row = last_inv_row + 1

                            new_rows = []
                            for _, qty, master_a in master_only:
                                info = master_a_to_info.get(master_a, {})
                                row = [
                                    master_a, info.get("title", ""), info.get("route", ""),
                                    "", "", "", qty,
                                ]
                                new_rows.append(row)

                            if new_rows:
                                range_str = f"A{next_row}:G{next_row + len(new_rows) - 1}"
                                inv_ws.update(
                                    range_name=range_str,
                                    values=new_rows,
                                    value_input_option="USER_ENTERED",
                                )
                                added_count = len(new_rows)
                        except Exception as e:
                            st.warning(f"⚠ マスタのみ追加処理失敗(既存更新は完了済み): {e}")

                    sheets._invalidate_one("04_在庫管理")

                    if err_count == 0:
                        st.success(
                            f"✅ 同期完了\n\n"
                            f"- 既存行 G列更新: {ok_count}件\n"
                            f"- 04に新規追加: {added_count}件\n"
                            f"- マスタ未登録(スキップ): {len(truly_unmatched)}件"
                        )
                    else:
                        st.warning(
                            f"⚠ 一部失敗あり\n\n"
                            f"- 既存行 G列更新 成功: {ok_count}件\n"
                            f"- 既存行 G列更新 失敗: {err_count}件\n"
                            f"- 04に新規追加: {added_count}件\n"
                            f"- マスタ未登録(スキップ): {len(truly_unmatched)}件"
                        )
                        if err_samples:
                            with st.expander("⚠ エラーサンプル"):
                                for s in err_samples:
                                    st.code(s)
                    if truly_unmatched:
                        st.info(
                            f"💡 マスタ未登録 {len(truly_unmatched)}件はスキップ。"
                            f"上のCSVをダウンロードして対処してください"
                        )
                    if err_count == 0:
                        st.balloons()
