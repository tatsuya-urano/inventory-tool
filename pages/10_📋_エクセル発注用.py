"""
10_エクセル発注用 + 04反映
"""
from io import StringIO

import pandas as pd
import streamlit as st

from lib import sheets, ui, inventory_ops

st.set_page_config(page_title="エクセル発注用", page_icon="📋", layout="wide")
st.title("📋 10_エクセル発注用")

SHEET_NAME = "10_エクセル発注用"
ui.sidebar_common(this_sheet=SHEET_NAME)

# ===========================================================
# 使い方
# ===========================================================
with st.expander("📌 エクセル発注用シートとは？(クリックして読む)", expanded=True):
    st.markdown(
        """
### 🎯 目的
仕入先に発注したリストを記録して、04の **L列(発注済み)** に反映する。
仕入先から実際に届いたら「📥 入荷時」ページで在庫加算。

### 📝 列の意味
| 列 | 内容 | 必須 |
|---|---|---|
| **A** | **商品コード(管理番号)** | **必須** |
| F | 注文数 | **必須** |
| O | 現在庫数 | 任意(参考表示) |
| P | 前月発送数 | 任意 |
| Q | 当月出荷数 | 任意 |
| R | 推奨発注数 | 任意 |
| U | 商品名(小分類) | 任意 |
| **X** | **係数** | **必須**(発注数 ÷ 係数 を 04のL列に加算) |

### 🚀 反映の動き
「⚡ 04＋マスタに反映実行」を押すと:
1. F列(発注数) ÷ X列(係数) → 04のL列(発注済み) に加算
2. マスタT列(最終発注日) を **今日** に更新
3. 反映成功した行は **このシートから自動削除**(2重反映防止)
4. マスタにない商品コードは「未マッチ」表示、シートからは削除

### 📥 CSV取込
ページ下部の「📥 CSV取込 / テンプレ」で、Excelで作った発注リストを一括追加可能。
"""
    )

with st.spinner("読込中..."):
    df = sheets.load_any_sheet(SHEET_NAME, header_row=3, data_start_row=4)
    master = sheets.load_master()
    inv = sheets.load_inventory()

st.metric("登録行数", f"{len(df):,}")

# ===========================================================
# マスタからルックアップ辞書を構築
# (商品コード入れたら 小分類/仕入先/FNSKU/ASIN/係数/重量/オプション等を即時表示)
# ===========================================================
master_lookup: dict[str, dict] = {}
if not master.empty:
    m_cols = list(master.columns)
    def _g(r, idx):
        return r.iloc[idx] if idx < len(r) else ""

    for _, mr in master.iterrows():
        code = str(_g(mr, 0)).strip()
        if not code:
            continue
        master_lookup[code] = {
            "小分類":         str(_g(mr, 4)).strip(),       # E
            "販売チャネル":   str(_g(mr, 5)).strip(),       # F
            "物流ルート":     str(_g(mr, 6)).strip(),       # G
            "原価":           str(_g(mr, 7)).strip(),       # H
            "売価":           str(_g(mr, 10)).strip(),      # K
            "仕入先":         str(_g(mr, 13)).strip(),      # N (URL等)
            "バリエーション": str(_g(mr, 14)).strip(),      # O
            "ラベル番号":     str(_g(mr, 16)).strip(),      # Q (FNSKU)
            "ASIN":           str(_g(mr, 15)).strip(),      # P
            "オプション":     str(_g(mr, 17)).strip(),      # R
            "オプション費用": str(_g(mr, 18)).strip(),      # S
            "最終発注日":     str(_g(mr, 19)).strip(),      # T
            "セット組相手":   str(_g(mr, 22)).strip(),      # W
            "セット組備考":   str(_g(mr, 23)).strip(),      # X
            "発注時係数":     str(_g(mr, 24)).strip(),      # Y
            "重量":           str(_g(mr, 26)).strip(),      # AA
            "備考":           str(_g(mr, 27)).strip(),      # AB
        }

# 04の在庫情報も引きたいので辞書化
inv_lookup: dict[str, dict] = {}
if not inv.empty:
    inv_cols = list(inv.columns)
    for _, ir in inv.iterrows():
        code = str(ir.iloc[0]).strip() if len(ir) > 0 else ""
        if not code:
            continue
        inv_lookup[code] = {
            "F自社倉庫": ir.iloc[5] if len(ir) > 5 else "",
            "L発注済み": ir.iloc[11] if len(ir) > 11 else "",
            "M推奨発注": ir.iloc[12] if len(ir) > 12 else "",
            "P90日販売": ir.iloc[15] if len(ir) > 15 else "",
        }

# ===========================================================
# ✏️ 発注入力テーブル
# A列に商品コード入れたら、マスタ情報が自動で各列に展開される
# ===========================================================
st.markdown("### ✏️ 発注入力 (商品コード入力でマスタ情報を自動表示)")
st.caption(
    "**A列に商品コードを入れる** → 小分類/仕入先/FNSKU/ASIN/係数/重量/オプション 等が即時表示されます。"
    "それを見ながらF列(注文数)を入力。空欄や赤字があればマスタ側の漏れです。"
)

DISPLAY_COLS = [
    "商品コード", "注文数",
    "小分類", "推奨発注(単品)", "推奨発注(係数込)",
    "F自社倉庫", "90日販売",
    "発注時係数", "仕入先", "バリエーション",
    "ラベル番号", "ASIN", "オプション", "オプション費用",
    "重量", "備考", "最終発注日",
]


def _to_num(v):
    try:
        return float(str(v).replace(",", "").replace("¥", "").strip())
    except (ValueError, TypeError):
        return None


# 既存行を編集テーブル形式に変換
def _row_with_master(code: str, qty="") -> dict:
    code = str(code).strip()
    m = master_lookup.get(code, {})
    iv = inv_lookup.get(code, {})

    # 推奨発注(係数込) = 04 M推奨 × マスタY係数
    rec_unit = _to_num(iv.get("M推奨発注", ""))
    ratio_v = _to_num(m.get("発注時係数", ""))
    if rec_unit is not None and ratio_v is not None and ratio_v > 0:
        rec_with_ratio = int(rec_unit * ratio_v) if (rec_unit * ratio_v).is_integer() else rec_unit * ratio_v
    else:
        rec_with_ratio = ""

    return {
        "商品コード":         code,
        "注文数":             qty,
        "小分類":             m.get("小分類", ""),
        "推奨発注(単品)":     iv.get("M推奨発注", ""),
        "推奨発注(係数込)":   rec_with_ratio,
        "F自社倉庫":          iv.get("F自社倉庫", ""),
        "90日販売":           iv.get("P90日販売", ""),
        "発注時係数":         m.get("発注時係数", ""),
        "仕入先":             m.get("仕入先", ""),
        "バリエーション":     m.get("バリエーション", ""),
        "ラベル番号":         m.get("ラベル番号", ""),
        "ASIN":               m.get("ASIN", ""),
        "オプション":         m.get("オプション", ""),
        "オプション費用":     m.get("オプション費用", ""),
        "重量":               m.get("重量", ""),
        "備考":               m.get("備考", ""),
        "最終発注日":         m.get("最終発注日", ""),
    }

work_rows = []
if not df.empty:
    code_col = sheets.find_col(df, ["商品コード"])
    qty_col = sheets.find_col(df, ["注文数", "発注数"])
    for _, r in df.iterrows():
        c = str(r.get(code_col, "")).strip() if code_col else ""
        q = r.get(qty_col, "") if qty_col else ""
        if not c:
            continue
        work_rows.append(_row_with_master(c, q))

# 末尾に空10行
for _ in range(10):
    work_rows.append({c: "" for c in DISPLAY_COLS})

work_df = pd.DataFrame(work_rows, columns=DISPLAY_COLS)
work_df["注文数"] = pd.to_numeric(work_df["注文数"].astype(str).str.replace(",", ""), errors="coerce")

# 編集UI: 商品コードと注文数だけ編集可、他はリアルタイム表示
column_config = {
    "商品コード":     st.column_config.TextColumn(label="🟢 A 商品コード"),
    "注文数":         st.column_config.NumberColumn(label="🟢 F 注文数", min_value=0, step=1),
    "小分類":         st.column_config.TextColumn(label="🔒 小分類", disabled=True),
    "推奨発注(単品)": st.column_config.TextColumn(label="🔒 04 M推奨(単品)", disabled=True,
                                                  help="04のM列(単品換算の推奨発注数)"),
    "推奨発注(係数込)": st.column_config.TextColumn(label="🔒 推奨×係数(目安)", disabled=True,
                                                    help="04 M推奨 × マスタY係数。Rakumartに頼むときの目安"),
    "F自社倉庫":      st.column_config.TextColumn(label="🔒 04 自社倉庫", disabled=True),
    "90日販売":       st.column_config.TextColumn(label="🔒 04 90日販売", disabled=True),
    "発注時係数":     st.column_config.TextColumn(label="🔒 X 係数", disabled=True),
    "仕入先":         st.column_config.TextColumn(label="🔒 仕入先URL", disabled=True),
    "バリエーション": st.column_config.TextColumn(label="🔒 バリエーション", disabled=True),
    "ラベル番号":     st.column_config.TextColumn(label="🔒 FNSKU", disabled=True),
    "ASIN":           st.column_config.TextColumn(label="🔒 ASIN", disabled=True),
    "オプション":     st.column_config.TextColumn(label="🔒 オプション", disabled=True),
    "オプション費用": st.column_config.TextColumn(label="🔒 オプション費用", disabled=True),
    "重量":           st.column_config.TextColumn(label="🔒 重量(g)", disabled=True),
    "備考":           st.column_config.TextColumn(label="🔒 備考", disabled=True),
    "最終発注日":     st.column_config.TextColumn(label="🔒 最終発注", disabled=True),
}

edited = st.data_editor(
    work_df,
    use_container_width=True,
    height=500,
    hide_index=True,
    num_rows="dynamic",
    column_config=column_config,
    key="order_editor",
)

# ===========================================================
# 自動保存(商品コード or 注文数の変更があったら即スプシへ)
# 商品コード入力 → マスタ情報を再表示するためにrerun
# ===========================================================
state = st.session_state.get("order_editor", {})
has_edits = bool(
    state.get("edited_rows") or state.get("added_rows") or state.get("deleted_rows")
)

if has_edits:
    try:
        save_rows = []
        unmatched_codes = []
        for _, r in edited.iterrows():
            code = str(r["商品コード"]).strip()
            if not code or code.lower() == "nan":
                continue
            qty_v = r["注文数"]
            qty = "" if pd.isna(qty_v) else qty_v
            # マスタにない商品コードは警告だけ(行は維持)
            if code not in master_lookup:
                unmatched_codes.append(code)
            m = master_lookup.get(code, {})
            ratio = m.get("発注時係数", "")
            small = m.get("小分類", "")
            # 24列(A〜X)構造
            row = [""] * 24
            row[0] = code             # A 商品コード
            row[5] = qty              # F 注文数
            row[20] = small           # U 商品名(小分類)
            row[23] = ratio           # X 係数
            save_rows.append(row)

        ss = sheets.get_spreadsheet()
        ws = ss.worksheet(SHEET_NAME)
        last_row = ws.row_count
        if last_row >= 4:
            ws.batch_clear([f"A4:X{last_row}"])
        if save_rows:
            ws.update(range_name="A4", values=save_rows, value_input_option="USER_ENTERED")
        sheets._invalidate_one(SHEET_NAME)

        msg = f"💾 自動保存 {len(save_rows)}件"
        if unmatched_codes:
            msg += f" / ⚠ マスタ未登録: {', '.join(unmatched_codes[:3])}"
        st.toast(msg, icon="✅")
        st.rerun()
    except Exception as e:
        st.error(f"❌ 自動保存失敗: {e}")
else:
    st.caption("✅ 変更なし(編集→Enterで自動保存・即マスタ情報展開)")

# ===========================================================
# 🔗 セット組相手SKUを自動展開
# ===========================================================
st.markdown("### 🔗 セット組相手SKUを展開")
st.caption(
    "現在入力中のSKUのうち、**マスタW列(セット組相手SKU)** が登録されているものについて、"
    "相方を自動で行追加します。同じ相方が既にあれば数量を合算します。"
    "押すと入力テーブルに反映されるので、注文数は確認/修正してください。"
)

if st.button("🔗 セット組展開実行", key="expand_set"):
    with st.spinner("セット組展開中..."):
        try:
            # 現在のシートデータ(マスタ補完済み)を再読込
            ss = sheets.get_spreadsheet()
            ws = ss.worksheet(SHEET_NAME)
            last_row_chk = ws.row_count
            current_values = ws.get(f"A4:X{last_row_chk}",
                                    value_render_option="UNFORMATTED_VALUE")

            # 入力エントリ
            entries: list[dict] = []
            for row in current_values:
                if not row or len(row) < 1:
                    continue
                code = str(row[0] or "").strip() if len(row) > 0 else ""
                if not code:
                    continue
                qty = row[5] if len(row) > 5 else ""
                entries.append({"code": code, "qty": qty})

            if not entries:
                st.warning("入力データがありません。先にA列に商品コードを入れてください")
            else:
                # ===========================================================
                # セット組展開ロジック (リファクタ版)
                # 仕様:
                #   - F列は実発注個数(セット数 × 係数)
                #   - 親セット数 = 親F ÷ 親係数
                #   - 相方の必要個数 = 親セット数 × 相方係数 (端数切上げ)
                #   - 同じ親が複数行あっても1回だけ計算 (集約)
                #   - 相方が既に入力欄にあれば、計算結果で「上書き」(加算しない)
                # ===========================================================
                import math as _math

                def _f_num(v):
                    try:
                        return float(str(v).replace(",", "") or 0)
                    except (ValueError, TypeError):
                        return 0.0

                # STEP A: 入力をコード単位で集約 (同じコード行が複数あれば数量合算)
                entries_by_code: dict[str, float] = {}
                for e in entries:
                    code = e["code"]
                    qty = _f_num(e["qty"])
                    entries_by_code[code] = entries_by_code.get(code, 0) + qty

                # STEP B: 各親について 相方の必要数を計算 (合算)
                partner_required: dict[str, float] = {}
                parent_codes_with_partner = set()
                for code, qty in entries_by_code.items():
                    m = master_lookup.get(code, {})
                    partner = m.get("セット組相手", "")
                    if not partner or partner not in master_lookup:
                        continue
                    parent_ratio = _f_num(m.get("発注時係数", "")) or 1
                    set_count = qty / parent_ratio if parent_ratio > 0 else 0

                    pm = master_lookup.get(partner, {})
                    partner_ratio = _f_num(pm.get("発注時係数", "")) or 1
                    partner_required[partner] = (
                        partner_required.get(partner, 0) + set_count * partner_ratio
                    )
                    parent_codes_with_partner.add(code)

                # STEP C: expanded リストを構築
                # - 親(セット相手あり)は entries_by_code の値そのまま
                # - 相方は partner_required で計算した値で「上書き」(既存があっても置換)
                # - 親でも相方でもないSKUはそのまま
                final_dict: dict[str, float] = {}
                # まず元の入力をコピー
                for code, qty in entries_by_code.items():
                    final_dict[code] = qty
                # 相方を計算値で上書き(端数切上げ)
                auto_added = 0
                for partner_code, needed in partner_required.items():
                    new_qty = int(_math.ceil(needed)) if needed > 0 else 0
                    if partner_code not in final_dict:
                        auto_added += 1
                    final_dict[partner_code] = new_qty

                # 順序: 元の入力順 → 後から追加された相方
                expanded: list[dict] = []
                seen = set()
                for code in entries_by_code:  # 元順
                    expanded.append({"code": code, "qty": final_dict[code]})
                    seen.add(code)
                for code in final_dict:
                    if code not in seen:
                        expanded.append({"code": code, "qty": final_dict[code]})

                # スプシに書き戻し(A,F,U,X 最低限。残りの補完は反映ボタンで)
                save_rows = []
                for e in expanded:
                    code = e["code"]
                    qty = e["qty"]
                    m = master_lookup.get(code, {})
                    row = [""] * 24
                    row[0] = code
                    row[5] = qty
                    row[20] = m.get("小分類", "")
                    row[23] = m.get("発注時係数", "") or 1
                    save_rows.append(row)

                if last_row_chk >= 4:
                    ws.batch_clear([f"A4:X{last_row_chk}"])
                if save_rows:
                    ws.update(range_name="A4", values=save_rows, value_input_option="USER_ENTERED")
                sheets._invalidate_one(SHEET_NAME)

                st.success(f"✅ セット組展開完了: 既存{len(entries)}件 → 展開後{len(expanded)}件 (相方追加 {auto_added}件)")
                st.balloons()
                st.rerun()
        except Exception as e:
            st.error(f"展開失敗: {e}")
            import traceback
            st.code(traceback.format_exc())

st.markdown("---")

# ===========================================================
# 🚀 反映ボタン
# ===========================================================
st.markdown("### 🚀 04_在庫管理 + マスタに反映")
st.caption(
    "押すと **以下4つを順に実行**:\n\n"
    "1. **N列(備考)** をマスタ備考+改行+注文数で補完\n"
    "2. **Rakumart用xlsx/CSV** を生成 (ダウンロードは下のボタン)\n"
    "3. **04のL列(発注済み)** に F÷X を加算 / **マスタT列(最終発注日)** を今日に\n"
    "4. **エクセル発注用シートをクリア**"
)

dry_run = st.checkbox(
    "🔍 ドライランモード(書込/クリアせず、Rakumart用ファイルだけ生成して確認)",
    value=False,
    key="order_dry_run",
    help="ON: ステップ1〜2のみ実行、ステップ3〜4(04加算/マスタ更新/シートクリア)をスキップ。"
         "Rakumartに送る前にxlsxの中身を確認したい時に使う",
)

col1, col2 = st.columns([1, 3])
with col1:
    btn_label = "🔍 ドライラン実行" if dry_run else "⚡ 04＋マスタに反映実行"
    btn_type = "secondary" if dry_run else "primary"
    if st.button(btn_label, type=btn_type):
        with st.spinner("処理中..."):
            try:
                ss = sheets.get_spreadsheet()
                order_ws = ss.worksheet(SHEET_NAME)

                # === STEP 0: セット組相手SKUを自動展開 ===
                # 入力された商品コードのセット相方(マスタW列)を持っている場合:
                # - 既にリストに相方があれば数量合算
                # - なければ新規で相方行を追加(数量は親と同じ)
                # - 各エントリに setRef を付与("○とセット" の文字列)
                last_row_chk = order_ws.row_count
                current_values = order_ws.get(f"A4:X{last_row_chk}",
                                              value_render_option="UNFORMATTED_VALUE")
                # 入力エントリ {code, qty}
                entries: list[dict] = []
                for row in current_values:
                    if not row or len(row) < 1:
                        continue
                    code = str(row[0] or "").strip() if len(row) > 0 else ""
                    if not code:
                        continue
                    qty = row[5] if len(row) > 5 else ""
                    if qty in ("", None):
                        continue
                    entries.append({"code": code, "qty": qty, "setRef": ""})

                # セット組展開
                expanded: list[dict] = []
                auto_added = 0
                for e in entries:
                    expanded.append(e)
                    m = master_lookup.get(e["code"], {})
                    partner = m.get("セット組相手", "")
                    if not partner or partner not in master_lookup:
                        continue
                    # 既存相方を探す
                    existing = next((x for x in expanded if x["code"] == partner), None)
                    if existing:
                        try:
                            existing["qty"] = (
                                float(str(existing["qty"]).replace(",", "") or 0)
                                + float(str(e["qty"]).replace(",", "") or 0)
                            )
                        except (ValueError, TypeError):
                            pass
                    else:
                        expanded.append({"code": partner, "qty": e["qty"], "setRef": ""})
                        auto_added += 1

                # setRef を計算 (○とセット)
                # オーナー → 相方(単数) / 相方 → オーナー(複数なら改行)
                code_to_idx = {e["code"]: i for i, e in enumerate(expanded)}
                partners_of: dict[str, list[int]] = {}
                for i, e in enumerate(expanded):
                    m = master_lookup.get(e["code"], {})
                    p = m.get("セット組相手", "")
                    if p and p in code_to_idx:
                        partners_of.setdefault(p, []).append(i)

                # オーナー → 相方
                for i, e in enumerate(expanded):
                    m = master_lookup.get(e["code"], {})
                    p = m.get("セット組相手", "")
                    if p and p in code_to_idx:
                        e["setRef"] = f"{code_to_idx[p] + 1}とセット"

                # 相方 → オーナー(複数なら改行)
                for partner_code, owner_idxs in partners_of.items():
                    p_idx = code_to_idx[partner_code]
                    expanded[p_idx]["setRef"] = "\n".join(
                        f"{idx + 1}とセット" for idx in owner_idxs
                    )

                # === STEP 1: 展開後のデータをスプシに書き戻し(マスタ補完含む) ===
                # 展開でセット相方が増えた可能性があるので、シートを再構築
                rebuild_rows = []
                for e in expanded:
                    code = e["code"]
                    qty = e["qty"]
                    m = master_lookup.get(code, {})
                    # 24列構造で構築
                    row = [""] * 24
                    row[0] = code                                 # A 商品コード
                    row[1] = m.get("仕入先", "")                  # B サイトURL
                    row[3] = m.get("バリエーション", "")          # D サイズ
                    row[5] = qty                                  # F 注文数
                    row[11] = m.get("ラベル番号", "")             # L FNSKU
                    row[12] = m.get("ASIN", "")                   # M ASIN
                    # N(備考) は STEP1.5 で構築
                    row[18] = m.get("セット組相手", "")           # S セット商品
                    row[19] = m.get("セット組備考", "")           # T セット商品備考
                    row[20] = m.get("小分類", "")                 # U 商品名(小分類)
                    row[21] = m.get("ラベル番号", "")             # V ラベル番号
                    row[22] = code                                # W 商品コード(コピー)
                    row[23] = m.get("発注時係数", "") or 1        # X 係数

                    # オプション列(J): マスタのオプション内容のみ
                    # 注文数は F列に入るので、ここに連結しない
                    row[9] = m.get("オプション", "")

                    # N(備考): マスタ備考 + 改行 + 注文数 + 改行 + setRef
                    base_memo = m.get("備考", "") or ""
                    qty_part = f"\n{qty}" if qty not in ("", None) else ""
                    set_ref_part = f"\n{e['setRef']}" if e.get("setRef") else ""
                    row[13] = f"{base_memo}{qty_part}{set_ref_part}".lstrip("\n")

                    rebuild_rows.append(row)

                # シート再構築: A4以降をクリアして書き直し
                if rebuild_rows:
                    if last_row_chk >= 4:
                        order_ws.batch_clear([f"A4:X{last_row_chk}"])
                    order_ws.update(
                        range_name="A4",
                        values=rebuild_rows,
                        value_input_option="USER_ENTERED",
                    )
                    sheets._invalidate_one(SHEET_NAME)

                n_updates = rebuild_rows  # 後続のメッセージ用

                # === STEP 2: Rakumart 15列様式 (.xlsx) を生成 ===
                # Rakumart ver.3.1 ヘッダ:
                # A 番号 / B サイトURL / C 写真 / D サイズ / E カラー / F 注文数 /
                # G 単価(元) / H 小計(元) / I 小計(円) / J オプション / K 納品先倉庫 /
                # L FBA(FNSKU) / M ASIN / N 備考 / O 管理番号
                rakumart_headers = [
                    "番号", "サイトURL（必需）", "写真", "サイズ", "カラー",
                    "注文数（必需）", "単価(元)", "小計(元)", "小計(円)", "オプション",
                    "納品先倉庫指定", "FBA(FNSKU)", "ASIN", "備考", "管理番号",
                ]
                # スプシ最新値再取得 (N列補完済み)
                fresh = order_ws.get(f"A4:X{last_row_chk}",
                                     value_render_option="FORMATTED_VALUE")
                rakumart_rows = []
                serial = 1
                for r in fresh:
                    if not r or len(r) < 1:
                        continue
                    code = str(r[0] or "").strip() if len(r) > 0 else ""
                    if not code:
                        continue
                    qty = r[5] if len(r) > 5 else ""
                    if not str(qty).strip():
                        continue
                    # シート上の値(優先) → 空ならマスタから補完(GAS版「Rakumart発注書補完」相当)
                    # マスタ列: N=仕入先URL(13), O=バリエーション(14), P=ASIN(15),
                    #           Q=FNSKU/ラベル番号(16), R=オプション(17)
                    m = master_lookup.get(code, {})
                    url = (str(r[1]).strip() if len(r) > 1 else "") or m.get("仕入先", "")
                    size = (str(r[3]).strip() if len(r) > 3 else "") or m.get("バリエーション", "")
                    color = str(r[4]).strip() if len(r) > 4 else ""
                    raw_option = (str(r[9]).strip() if len(r) > 9 else "") or m.get("オプション", "")
                    fnsku = (str(r[11]).strip() if len(r) > 11 else "") or m.get("ラベル番号", "")
                    asin_v = (str(r[12]).strip() if len(r) > 12 else "") or m.get("ASIN", "")
                    memo_n = str(r[13]).strip() if len(r) > 13 else ""

                    # GAS仕様: オプションあるなら "内容\n(注文数÷係数=セット数)"
                    option = raw_option
                    if raw_option and qty not in ("", None):
                        try:
                            ratio_v = float(m.get("発注時係数", "") or 0)
                            qty_n = float(str(qty).replace(",", ""))
                            if ratio_v > 0:
                                set_count = qty_n / ratio_v
                                set_count_disp = (
                                    str(int(set_count)) if set_count.is_integer() else str(set_count)
                                )
                                option = f"{raw_option}\n{set_count_disp}"
                        except (ValueError, TypeError):
                            pass

                    rakumart_rows.append([
                        serial, url, "", size, color, qty,
                        "", "", "",  # 単価/小計はRakumart側で計算
                        option, "", fnsku, asin_v, memo_n, code,
                    ])
                    serial += 1

                # xlsx生成
                from io import BytesIO
                from openpyxl import Workbook
                wb = Workbook()
                wsx = wb.active
                wsx.title = "temp"
                wsx.append(rakumart_headers)
                for row in rakumart_rows:
                    wsx.append(row)
                xlsx_buf = BytesIO()
                wb.save(xlsx_buf)
                xlsx_bytes = xlsx_buf.getvalue()

                # 念のため CSV 版も併存
                csv_df = pd.DataFrame(rakumart_rows, columns=rakumart_headers)
                csv_bytes = csv_df.to_csv(index=False).encode("utf-8-sig")

                from datetime import datetime as _dt
                ts = _dt.now().strftime('%Y%m%d_%H%M%S')
                st.session_state["_order_csv_bytes"] = csv_bytes
                st.session_state["_order_xlsx_bytes"] = xlsx_bytes
                st.session_state["_order_csv_filename"] = f"rakumart_order_{ts}.csv"
                st.session_state["_order_xlsx_filename"] = f"rakumart_order_{ts}.xlsx"
                st.session_state["_order_csv_rows"] = len(rakumart_rows)

                # === STEP 3: 04 L列加算 + マスタT列更新 + シートクリア (ドライランならスキップ) ===
                if dry_run:
                    result = {"processed": 0, "not_found": [], "total": len(rakumart_rows),
                              "master_updated": 0, "_dry_run": True}
                else:
                    result = inventory_ops.apply_order()
            except Exception as e:
                st.error(f"反映失敗: {e}")
                import traceback
                st.code(traceback.format_exc())
                result = None

        if result:
            if result.get("_dry_run"):
                st.info(
                    f"🔍 ドライラン完了 (実際の書込みはしてません)\n\n"
                    f"- N列補完: {len(n_updates)}件 (シート上で確認可)\n"
                    f"- 生成行数: {result['total']}件\n\n"
                    f"📥 **下のRakumart用xlsx/CSVをダウンロードして中身を確認してください。"
                    f"問題なければ ドライランOFF で本実行を**"
                )
            else:
                st.success(
                    f"✅ 反映完了\n\n"
                    f"- N列補完: {len(n_updates)}件\n"
                    f"- 04 L列加算: {result['processed']}件\n"
                    f"- マスタ最終発注日更新: {result.get('master_updated', 0)}件\n"
                    f"- マスタにないSKU: {len(result['not_found'])}件\n"
                    f"- 元の総行数: {result['total']}件\n\n"
                    f"📥 **下の「Rakumart用」ボタンを押してファイル取得 → Rakumartに申請してください**"
                )
                if result["not_found"]:
                    with st.expander(f"⚠ マスタにないSKU"):
                        st.write(result["not_found"])
                st.balloons()

with col2:
    st.caption("💡 反映 → クリアされます。下のCSVダウンロードを忘れずに")

# 反映後のRakumart用ダウンロード(session_stateから)
if st.session_state.get("_order_xlsx_bytes"):
    n_rows = st.session_state.get("_order_csv_rows", 0)
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            f"📥 Rakumart用xlsxダウンロード ({n_rows}行)",
            st.session_state["_order_xlsx_bytes"],
            file_name=st.session_state["_order_xlsx_filename"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            f"📥 CSV版ダウンロード ({n_rows}行)",
            st.session_state["_order_csv_bytes"],
            file_name=st.session_state["_order_csv_filename"],
            mime="text/csv",
            use_container_width=True,
        )
    st.caption(
        "💡 Rakumartには **xlsx版** をアップロードしてください "
        "(15列様式: A番号/B URL/D サイズ/F 注文数/J オプション/L FNSKU/M ASIN/N 備考/O 管理番号)"
    )


# ===========================================================
# 📥 CSV取込 / テンプレ
# ===========================================================
st.markdown("---")
st.markdown("### 📥 CSV取込 / テンプレ")

template_df = pd.DataFrame([
    {"商品コード": "例: cameraholder2K", "注文数": 10, "係数": 1, "商品名": "R305カメラスタンド2黒"},
    {"商品コード": "例: 605",            "注文数": 5,  "係数": 1, "商品名": "マグネットローダー5個"},
])
template_csv = template_df.to_csv(index=False).encode("utf-8-sig")

dc1, dc2 = st.columns([1, 3])
with dc1:
    st.download_button(
        "📄 テンプレCSVダウンロード",
        template_csv,
        file_name="order_template.csv",
        mime="text/csv",
        use_container_width=True,
    )
with dc2:
    st.caption(
        "📝 必須列: `商品コード`, `注文数`, `係数`。任意列: 商品名 等。"
        "先頭0付きSKUは Excelで開くと0が落ちるのでメモ帳/VSCode 推奨"
    )

uploaded = st.file_uploader(
    "CSV / TSV / Excel ファイル",
    type=["csv", "tsv", "xlsx", "xls"],
    key="order_uploader",
)
pasted = st.text_area("または貼り付け(タブ or カンマ区切り)", height=120, key="order_paste")

new_data = None
if uploaded is not None:
    try:
        if uploaded.name.lower().endswith((".xlsx", ".xls")):
            new_data = pd.read_excel(uploaded, dtype=str).fillna("")
        else:
            content = uploaded.read().decode("utf-8-sig", errors="replace")
            sep = "\t" if content.split("\n")[0].count("\t") > content.split("\n")[0].count(",") else ","
            new_data = pd.read_csv(StringIO(content), sep=sep, dtype=str).fillna("")
        st.success(f"読込: {len(new_data)}行 × {len(new_data.columns)}列")
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
    cands_code = [c for c in new_data.columns if any(kw in str(c) for kw in ["商品コード", "SKU", "管理番号"])]
    cands_qty  = [c for c in new_data.columns if any(kw in str(c) for kw in ["注文数", "発注数", "数量", "個数"])]
    cands_ratio = [c for c in new_data.columns if any(kw in str(c) for kw in ["係数"])]
    cands_name = [c for c in new_data.columns if any(kw in str(c) for kw in ["商品名", "タイトル", "小分類"])]

    cc1, cc2 = st.columns(2)
    with cc1:
        sel_code = st.selectbox("商品コード列(必須)", options=list(new_data.columns),
                                index=(list(new_data.columns).index(cands_code[0]) if cands_code else 0),
                                key="ord_csv_code")
        sel_qty  = st.selectbox("注文数列(必須)", options=list(new_data.columns),
                                index=(list(new_data.columns).index(cands_qty[0]) if cands_qty else 0),
                                key="ord_csv_qty")
    with cc2:
        opts_opt = ["（無視・1扱い）"] + list(new_data.columns)
        sel_ratio = st.selectbox("係数列(必須・無視で1)", options=opts_opt,
                                  index=(opts_opt.index(cands_ratio[0]) if cands_ratio else 0),
                                  key="ord_csv_ratio")
        opts_name = ["（無視）"] + list(new_data.columns)
        sel_name = st.selectbox("商品名列(任意)", options=opts_name,
                                index=(opts_name.index(cands_name[0]) if cands_name else 0),
                                key="ord_csv_name")

    # 10_エクセル発注用 は 24列(A〜X)構造、データはrow4から
    rows_2d = []
    for _, r in new_data.iterrows():
        row = [""] * 24
        row[0] = str(r[sel_code]).strip()       # A 商品コード
        row[5] = str(r[sel_qty]).strip()        # F 注文数
        row[23] = str(r[sel_ratio]).strip() if sel_ratio != "（無視・1扱い）" else "1"  # X 係数
        if sel_name != "（無視）":
            row[20] = str(r[sel_name]).strip() # U 商品名
        # 商品コード空はスキップ
        if row[0]:
            rows_2d.append(row)

    st.caption(f"取込予定: {len(rows_2d)}件")

    if rows_2d:
        st.markdown("**👀 マッピング後プレビュー（先頭5件）**")
        prev = pd.DataFrame(rows_2d[:5])
        prev_show = prev[[0, 5, 20, 23]].copy()
        prev_show.columns = ["A商品コード", "F注文数", "U商品名", "X係数"]
        st.dataframe(prev_show, use_container_width=True, hide_index=True)

        if st.button("📤 10_エクセル発注用に追加", type="primary", use_container_width=True, key="ord_csv_apply"):
            with st.spinner("書込中..."):
                try:
                    sh = sheets.get_spreadsheet()
                    ws = sh.worksheet(SHEET_NAME)
                    # 既存データの最終行を検出
                    a_col = ws.col_values(1)
                    last_data_row = max([i + 1 for i, v in enumerate(a_col) if v.strip() and i + 1 >= 4] + [3])
                    start_row = last_data_row + 1
                    end_col = "X"
                    range_str = f"A{start_row}:{end_col}{start_row + len(rows_2d) - 1}"
                    ws.update(range_name=range_str, values=rows_2d, value_input_option="USER_ENTERED")
                    sheets._invalidate_one(SHEET_NAME)
                    st.success(f"✅ {len(rows_2d)}件 追加しました")
                    st.balloons()
                    st.rerun()
                except Exception as e:
                    st.error(f"取込失敗: {e}")
