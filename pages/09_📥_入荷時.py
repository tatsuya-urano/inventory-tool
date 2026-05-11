"""
06_入荷時 編集 + 04反映ページ
"""
from datetime import date
from io import StringIO

import pandas as pd
import streamlit as st

from lib import sheets, ui, inventory_ops

st.set_page_config(page_title="入荷時", page_icon="📥", layout="wide")
st.title("📥 06_入荷時")

SHEET_NAME = "06_入荷時"
ui.sidebar_common(this_sheet=SHEET_NAME)

# ===========================================================
# 使い方
# ===========================================================
with st.expander("📌 入荷時シートとは？運用手順(クリックして読む)", expanded=True):
    st.markdown(
        """
### 🎯 目的
**Rakumart(代行業者)から商品が届いたとき** に、配送依頼書(.xlsx)を取り込んで在庫(04)に反映する。
04の **I列(当月入荷)** に加算され、**L列(発注済み)** から減算される(発注したのが届いたから)。

---

### 📝 運用手順 (5ステップ)

#### 1️⃣ Rakumart から配送依頼書 .xlsx をダウンロード
- 例: `P2026041918520278-46725.xlsx`
- 中に「梱包リスト」シートがあれば自動認識

#### 2️⃣ ページ下部の「📥 Rakumart 配送依頼書 取込」でアップロード
- ファイル選択 → プレビュー → 「📤 06_入荷時に追加」ボタン
- スプシの 06_入荷時 row6以降に貼り付けされ、Q列(商品管理番号)・R列(係数) は数式が自動展開

#### 3️⃣ 入荷データをこのページで確認
- 上部「📋 入荷データ」テーブルで件数・内容を確認
- N列(商品コード)が空の行があればスプシで埋める

#### 4️⃣ 「🔍 ドライラン実行」で件数チェック(任意・推奨)
- 何件処理されるか・マスタ未登録のSKUがいくつあるかを **書込なしで確認**
- 想定と違うときはここで止まれる

#### 5️⃣ 「⚡ 04+マスタに反映実行」で本番処理
- N列(商品コード) で 04の行を引く
- I列(当月入荷) に H÷R(梱包数÷係数=入荷個数) を加算
- L列(発注済み) から H÷R(同じ係数割り後の数) を減算 (マイナス防止)
- 入荷時シートを自動クリア(2重反映防止)
- マスタにないSKUは未マッチ警告で残らない

---

### 🧱 入荷時シートの列構造 (Rakumart梱包リスト形式)
| 列 | 内容 | 反映で使う |
|---|---|---|
| A | 箱NO | - |
| B | 箱寸法(cm) | - |
| C | 実際重量(kg) | - |
| D | 注文番号 | - |
| E | 商品番号 | - |
| F | 画像 | - |
| G | 商品情報 | - |
| **H** | **梱包数(実発注数)** | ✅ ÷R列して I列加算 / L列減算 |
| I | 単価(元) | - |
| J | 小計(元) | - |
| K | 国内運賃 | - |
| L | ラベル種類 | - |
| M | ラベル番号 | - |
| **N** | **商品コード** | ✅ 04 と突合 |
| O | 箱詰備考 | - |
| P | 配送履歴 | - |
| Q | 商品管理番号(数式) | - (補助表示) |
| **R** | **係数(数式)** | 表示参考用(L列減算には使わない) |

---

### ⚠️ 注意点
- **N列(商品コード)** が空だとその行はスキップされます。事前に確認推奨
- マスタにない商品コードは反映されず、シートからは自動削除されます(警告は出ます)
- 反映後にもう一度同じファイルを取り込むと**2重に在庫が増える**ので、反映済みのRakumartファイルは取り込まないこと
"""
    )

with st.spinner("読込中..."):
    df = sheets.load_any_sheet(SHEET_NAME, header_row=5, data_start_row=6)

if df.empty:
    st.info("📭 入荷データなし。下の「📥 Rakumart 配送依頼書 取込」から追加してください")
else:
    st.metric("登録行数", f"{len(df):,}")

    # テーブル表示 (Q/R列は数式由来=🔒 表示)
    st.markdown("### 📋 入荷データ")
    df_cols = list(df.columns)
    col_cfg = {}
    for c in df_cols:
        s = str(c)
        if "商品管理番号" in s or "係数" in s:
            col_cfg[c] = st.column_config.TextColumn(label=f"🔒 {c} (数式)")
    st.dataframe(
        df, use_container_width=True, height=400, hide_index=True,
        column_config=col_cfg,
    )

    # ===========================================================
    # 🔗 シート上の同一商品管理番号を集約
    # ===========================================================
    st.markdown("### 🔗 同じ商品管理番号を集約 (箱違いを1行にまとめる)")
    st.caption(
        "シート上に **同じQ列(商品管理番号)** の行が複数あるとき1行にまとめます。\n"
        "- **H列(梱包数)** = 合算\n"
        "- **K列(国内運賃)**: \n"
        "    - 同じ注文番号(D列)で複数行ある → あるほう優先(同発注日の箱違い)\n"
        "    - 違う注文番号 → **合算**(別発注日が同便にきた → 送料も別途かかる)\n"
        "- 他列(I単価/J小計等) は最初の行の値そのまま"
    )

    st.caption(
        "🛡 **誤集約防止**: Q列(商品管理番号)が **マスタE列(小分類)に存在する** 場合のみ集約します。"
        "「20」「袋詰め」のような未確定/雑メモは集約せず個別行のまま残ります。"
    )

    if st.button("🔗 同一SKUを集約実行", key="merge_dup"):
        with st.spinner("集約中..."):
            try:
                ss_m = sheets.get_spreadsheet()
                ws_m = ss_m.worksheet(SHEET_NAME)
                master_ws_m = ss_m.worksheet("03_商品マスタ参照")

                # マスタE列(小分類) の値セット を作成
                master_e_vals = master_ws_m.col_values(5)
                kogo_set = set()
                for i, v in enumerate(master_e_vals):
                    if i < 6:
                        continue
                    s = str(v or "").strip()
                    if s:
                        kogo_set.add(s)

                arr_last_m = ws_m.row_count
                full_data = ws_m.get(
                    f"A6:R{arr_last_m}",
                    value_render_option="UNFORMATTED_VALUE",
                )

                def _f_n(v):
                    try:
                        return float(str(v or "").replace(",", "").strip() or 0)
                    except (ValueError, TypeError):
                        return 0.0

                grouped: dict[str, list] = {}
                # 各grouped行に「処理済み注文番号セット」を追跡してK列の集約方式を切り替える
                grouped_orders: dict[str, set] = {}
                preserved: list = []
                empty_sku: list = []
                non_master_q: set = set()  # マスタ小分類に無いQ値(誤集約防止で残した)
                for row in full_data:
                    if not row:
                        continue
                    # 全列空をスキップ
                    if not any(str(c or "").strip() for c in row):
                        continue
                    # 18列に揃える
                    while len(row) < 18:
                        row.append("")
                    q = str(row[16] or "").strip() if len(row) > 16 else ""
                    n = str(row[13] or "").strip() if len(row) > 13 else ""
                    order_no = str(row[3] or "").strip() if len(row) > 3 else ""  # D列

                    # SKU空(N列もQ列も空)
                    if not q and not n:
                        empty_sku.append(row)
                        preserved.append(list(row))
                        continue

                    # Q列が マスタ小分類に存在しない なら集約対象外(個別行で残す)
                    if not q or q not in kogo_set:
                        if q:
                            non_master_q.add(q)
                        preserved.append(list(row))
                        continue

                    # 集約処理
                    if q not in grouped:
                        grouped[q] = list(row)
                        grouped_orders[q] = {order_no} if order_no else set()
                    else:
                        # H列(梱包数 idx 7) 合算
                        cur_h = _f_n(grouped[q][7])
                        new_h = _f_n(row[7])
                        merged_h = cur_h + new_h
                        grouped[q][7] = int(merged_h) if merged_h == int(merged_h) else merged_h

                        # K列(国内運賃 idx 10) 注文番号で振り分け:
                        # - 既存と同じ注文番号 → あるほう優先(合算しない)
                        # - 違う注文番号 → 合算(別発注日が同便)
                        new_k_v = _f_n(row[10])
                        cur_k_v = _f_n(grouped[q][10])
                        if order_no and order_no in grouped_orders[q]:
                            # 同じ注文番号 → あるほう優先
                            if cur_k_v == 0 and new_k_v > 0:
                                grouped[q][10] = row[10]
                            # cur > 0 なら触らない
                        else:
                            # 違う注文番号 → 合算
                            merged_k = cur_k_v + new_k_v
                            grouped[q][10] = int(merged_k) if merged_k == int(merged_k) else merged_k
                            if order_no:
                                grouped_orders[q].add(order_no)

                merged_rows = list(grouped.values()) + preserved
                before = len(full_data)
                after = len(merged_rows)

                if before == after:
                    st.info(f"✅ 集約対象なし(現在{before}行)")
                else:
                    # Q/R列はARRAYFORMULAなので触らない: A〜P列のみクリア＆書込
                    if arr_last_m >= 6:
                        ws_m.batch_clear([f"A6:P{arr_last_m}"])
                    # 各行をA-P(16列)に切り詰めてQ/R列を上書きしないようにする
                    merged_rows_ap = [r[:16] for r in merged_rows]
                    ws_m.update(
                        range_name=f"A6",
                        values=merged_rows_ap,
                        value_input_option="USER_ENTERED",
                    )
                    sheets._invalidate_one(SHEET_NAME)
                    st.success(
                        f"✅ 集約完了: {before}行 → {after}行 "
                        f"({before - after}行統合)"
                    )
                    if non_master_q:
                        st.info(
                            f"🛡 マスタ小分類に無いQ値 {len(non_master_q)}種類は誤集約防止で個別行のまま: "
                            + ", ".join(list(non_master_q)[:8])
                            + ("..." if len(non_master_q) > 8 else "")
                        )
                    if empty_sku:
                        st.warning(
                            f"⚠ N列(商品コード)もQ列(商品管理番号)も空の行が {len(empty_sku)}件 残っています。"
                            f"スプシで埋めてください"
                        )
                    st.balloons()
                    st.rerun()
            except Exception as e:
                st.error(f"集約失敗: {e}")
                import traceback
                st.code(traceback.format_exc())

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "💾 現在データをCSVダウンロード",
        csv,
        file_name=f"arrival_{len(df)}rows.csv",
        mime="text/csv",
    )

    # ===========================================================
    # 🗑️ 入荷時シート初期化(クリア)
    # ===========================================================
    with st.expander("🗑️ 入荷時シートを初期化(全クリア)"):
        st.warning(
            "シートのデータ部(row6以降A〜P列)を全削除します。"
            "Q/R列は数式のため温存されます。"
            "間違えて取込んだ時・反映後にゴミが残った時 等に使用してください。"
        )
        confirm = st.checkbox("⚠ 本当にクリアする (チェックしてからボタン)", key="arr_clear_confirm")
        if confirm and st.button("🗑️ 全クリア実行", type="secondary", key="arr_clear_btn"):
            with st.spinner("クリア中..."):
                try:
                    ss_c = sheets.get_spreadsheet()
                    ws_c = ss_c.worksheet(SHEET_NAME)
                    last_r = ws_c.row_count
                    if last_r >= 6:
                        ws_c.batch_clear([f"A6:P{last_r}"])
                    sheets._invalidate_one(SHEET_NAME)
                    st.success("✅ 入荷時シートをクリアしました")
                    st.balloons()
                    st.rerun()
                except Exception as e:
                    st.error(f"クリア失敗: {e}")

    st.markdown("---")

    # ===========================================================
    # 🚀 04 + マスタに反映 (Rakumart梱包リスト型対応)
    # ===========================================================
    st.markdown("### 🚀 04_在庫管理 + マスタに反映")
    st.caption(
        "**Rakumart梱包リスト形式** の入荷時シートを処理:\n"
        "- N列(商品コード) または Q列(商品管理番号→マスタ小分類でマスタ突合) で04・マスタを引く\n"
        "- **04 I列(当月入荷)** に H÷R(梱包数÷係数=入荷個数) を加算\n"
        "- **04 L列(発注済み)** から H÷R(同じ数) を減算 (マイナス防止)\n"
        "- **マスタAC列(直接入力原価)** を I列(単価/元) × 為替レート 等で計算反映 (任意)\n"
        "- 反映後シートクリア"
    )

    apply_dry = st.checkbox(
        "🔍 ドライランモード(書込しないで件数だけ確認)",
        value=False, key="arr_dry",
    )
    apply_cost = st.checkbox(
        "💴 マスタAC列(直接入力原価) も更新する",
        value=False, key="arr_cost",
        help="I列(単価/元) × J列(小計/元) ÷ H列(梱包数) など、いまは未実装。"
             "ON時は警告のみ表示し処理はスキップ",
    )
    fba_direct_mode = st.checkbox(
        "🚚 FBA直納モード（自社倉庫を経由せず Amazon倉庫へ直接入荷）",
        value=False, key="arr_fba_direct",
        help="ON時:\n"
             "- 04 I列(当月入荷) には加算しない (二重計上防止: 後で fba_fetch がD列を埋める)\n"
             "- L列(発注済み) からは通常通り減算\n"
             "- マスタAC列(原価) も通常通り更新可能\n"
             "→ 自社倉庫在庫(F列)は増えないが、発注消化と原価反映はされる",
    )

    if fba_direct_mode:
        st.warning(
            "🚚 **FBA直納モード ON** — I列(当月入荷) はスキップします。"
            "L列(発注済み)減算 + マスタAC原価更新のみ実行します。"
        )

    col1, col2 = st.columns([1, 3])
    with col1:
        if fba_direct_mode:
            btn_label = "🔍 ドライラン実行 (FBA直納)" if apply_dry else "🚚 FBA直納モードで反映"
        else:
            btn_label = "🔍 ドライラン実行" if apply_dry else "⚡ 04+マスタに反映実行"
        btn_type = "secondary" if apply_dry else "primary"
        if st.button(btn_label, type=btn_type, key="arr_apply"):
            with st.spinner("処理中..."):
                try:
                    ss = sheets.get_spreadsheet()
                    arr_ws = ss.worksheet(SHEET_NAME)
                    inv_ws = ss.worksheet("04_在庫管理")
                    master_ws = ss.worksheet("03_商品マスタ参照")

                    # 入荷時データ取得 (row6以降、A-Y列まで - Y列が入荷後原価)
                    arr_last = arr_ws.row_count
                    arr_values = arr_ws.get(
                        f"A6:Y{arr_last}", value_render_option="UNFORMATTED_VALUE"
                    )

                    # 04のA列マップ
                    inv_a = inv_ws.col_values(1)
                    code_to_inv_row = {}
                    for i, c in enumerate(inv_a, start=1):
                        if i < 7:
                            continue
                        cs = str(c or "").strip()
                        if cs:
                            code_to_inv_row[cs] = i

                    # 現在の04 I/L列値
                    inv_i_existing = inv_ws.col_values(9)   # I列(当月入荷)
                    inv_l_existing = inv_ws.col_values(12)  # L列(発注済み)

                    def _f(v):
                        try:
                            return float(str(v or 0).replace(",", "").replace("¥", "") or 0)
                        except (ValueError, TypeError):
                            return 0.0

                    i_values = {}
                    l_values = {}
                    for r, v in enumerate(inv_i_existing, start=1):
                        if r >= 7:
                            i_values[r] = _f(v)
                    for r, v in enumerate(inv_l_existing, start=1):
                        if r >= 7:
                            l_values[r] = _f(v)

                    # 入荷時 各行を処理
                    processed = 0
                    not_found = []
                    i_target_rows = set()
                    l_target_rows = set()

                    for row in arr_values:
                        if not row or len(row) < 8:
                            continue
                        # N列(index 13) = 商品コード
                        code = str(row[13] or "").strip() if len(row) > 13 else ""
                        if not code:
                            continue
                        # ヘッダ誤取り込み防止
                        if code in ("商品コード", "商品管理番号"):
                            continue
                        # H列(index 7) = 梱包数
                        qty = _f(row[7]) if len(row) > 7 else 0
                        if qty <= 0:
                            continue
                        # R列(index 17) = 係数
                        ratio = _f(row[17]) if len(row) > 17 else 0
                        # 係数が0/空なら 1 として扱う
                        if ratio <= 0:
                            ratio = 1

                        if code not in code_to_inv_row:
                            not_found.append(code)
                            continue

                        target_row = code_to_inv_row[code]
                        # 04 I列 += H ÷ R(係数) ← 入荷個数(SKU単位)
                        # 04 L列 -= H ÷ R(係数) ← 発注済みも係数で割った数で記載されているため
                        # ratio が0/空なら1扱い (上で処理済み)
                        amt = qty / ratio
                        if not fba_direct_mode:
                            i_values[target_row] = i_values.get(target_row, 0) + amt
                            i_target_rows.add(target_row)
                        cur_l = l_values.get(target_row, 0)
                        l_values[target_row] = max(0, cur_l - amt)
                        l_target_rows.add(target_row)
                        processed += 1

                    # ドライランなら書込スキップ
                    if apply_dry:
                        mode_label = "🚚 FBA直納モード" if fba_direct_mode else "📦 通常モード"
                        i_label = "(スキップ)" if fba_direct_mode else f"{len(i_target_rows)}行"
                        st.info(
                            f"🔍 ドライラン結果 ({mode_label})\n\n"
                            f"- 処理対象: {processed}件\n"
                            f"- 04 I列(当月入荷)更新予定: {i_label}\n"
                            f"- 04 L列(発注済み)更新予定: {len(l_target_rows)}行\n"
                            f"- マスタにないSKU: {len(not_found)}件"
                        )
                        if not_found:
                            with st.expander(f"⚠ マスタにないSKU {len(not_found)}件"):
                                st.write(not_found)
                    else:
                        # 04 I列 batch_update
                        i_reqs = []
                        for r in i_target_rows:
                            v = i_values[r]
                            v_out = int(v) if v == int(v) else v
                            i_reqs.append({"range": f"I{r}", "values": [[v_out]]})
                        # 04 L列 batch_update
                        l_reqs = []
                        for r in l_target_rows:
                            v = l_values[r]
                            v_out = int(v) if v == int(v) else v
                            l_reqs.append({"range": f"L{r}", "values": [[v_out]]})

                        all_reqs = i_reqs + l_reqs
                        if all_reqs:
                            inv_ws.batch_update(all_reqs, value_input_option="USER_ENTERED")

                        # マスタAC列(直接入力原価)更新
                        cost_updated = 0
                        cost_skipped_zero = 0
                        cost_skipped_child = 0
                        if apply_cost:
                            # マスタ A=コード, E=小分類, U=親SKU
                            mvals = master_ws.get_all_values()
                            kogo_to_master_row = {}
                            for mi, mr in enumerate(mvals[6:], start=7):
                                if not mr or not (mr[0] or "").strip():
                                    continue
                                kogo = (mr[4] if len(mr) > 4 else "").strip()
                                parent = (mr[20] if len(mr) > 20 else "").strip()
                                code_a = (mr[0] or "").strip()
                                if kogo:
                                    kogo_to_master_row[kogo] = {
                                        "row": mi, "code": code_a, "parent": parent
                                    }

                            cost_updates = []
                            seen_kogo = set()
                            for row in arr_values:
                                if not row or len(row) < 25:
                                    continue
                                kogo = str(row[16] or "").strip() if len(row) > 16 else ""
                                if not kogo or kogo in seen_kogo:
                                    continue
                                # Y列(index 24) = 入荷後原価
                                try:
                                    new_cost = float(row[24] or 0) if len(row) > 24 else 0
                                except (ValueError, TypeError):
                                    new_cost = 0
                                # 0円ならスキップ (既存値維持)
                                if new_cost == 0:
                                    cost_skipped_zero += 1
                                    continue
                                target = kogo_to_master_row.get(kogo)
                                if not target:
                                    continue
                                # 子SKU(親SKUあり)はスキップ
                                if target["parent"] and target["parent"] != target["code"]:
                                    cost_skipped_child += 1
                                    continue
                                cost_updates.append({
                                    "range": f"AC{target['row']}",
                                    "values": [[int(new_cost)]],
                                })
                                seen_kogo.add(kogo)
                                cost_updated += 1

                            if cost_updates:
                                CHUNK = 200
                                for j in range(0, len(cost_updates), CHUNK):
                                    master_ws.batch_update(
                                        cost_updates[j:j + CHUNK],
                                        value_input_option="USER_ENTERED",
                                    )
                                sheets._invalidate_one("03_商品マスタ参照")

                        # 入荷時シートクリア(row6以降のA-P列のみ。Q/R列は数式のため温存)
                        if arr_last >= 6:
                            arr_ws.batch_clear([f"A6:P{arr_last}"])

                        sheets._invalidate_one(SHEET_NAME)
                        sheets._invalidate_one("04_在庫管理")

                        mode_label = "🚚 FBA直納モード" if fba_direct_mode else "📦 通常モード"
                        i_label = "スキップ(FBA直納)" if fba_direct_mode else f"{len(i_target_rows)}行加算"
                        msg = (
                            f"✅ 反映完了 ({mode_label})\n\n"
                            f"- 処理件数: {processed}件\n"
                            f"- 04 I列(当月入荷): {i_label}\n"
                            f"- 04 L列(発注済み)減算: {len(l_target_rows)}行\n"
                            f"- マスタにないSKU: {len(not_found)}件\n"
                            f"- 入荷時シートクリア完了"
                        )
                        if apply_cost:
                            msg += (
                                f"\n\n💴 マスタAC列更新: {cost_updated}件"
                                f" (0円スキップ {cost_skipped_zero} / 子SKUスキップ {cost_skipped_child})"
                            )
                        st.success(msg)
                        if not_found:
                            with st.expander(f"⚠ マスタにないSKU"):
                                st.write(not_found)
                        st.balloons()
                except Exception as e:
                    st.error(f"反映失敗: {e}")
                    import traceback
                    st.code(traceback.format_exc())

    with col2:
        st.caption(
            "💡 反映成功した行は入荷時シートから自動クリアされます。"
            "マスタにないSKUは「未マッチ」表示で残らず、警告のみ"
        )

# ===========================================================
# 📥 Rakumart 配送依頼書 取込
# ===========================================================
st.markdown("---")
st.markdown("### 📥 Rakumart 配送依頼書 (.xlsx) 取込")
st.caption(
    "Rakumartからダウンロードした配送依頼書(.xlsx)を直接アップロード。"
    "**梱包リスト**シートを 06_入荷時 の row6 以降にそのまま貼り付けます。"
    "Q列(商品管理番号)・R列(係数) は既存の数式が自動展開してくれます。"
)

uploaded = st.file_uploader(
    "Rakumart 配送依頼書 (.xlsx)",
    type=["xlsx", "xls"],
    key="rakumart_uploader",
    help="ファイル名例: P2026041918520278-46725.xlsx",
)

new_data = None
sheet_name_in_xlsx = None
if uploaded is not None:
    try:
        xl = pd.ExcelFile(uploaded)
        # 「梱包リスト」シートを優先、なければ最後のシート
        target_sheet = None
        for sn in xl.sheet_names:
            if "梱包" in sn or "リスト" in sn:
                target_sheet = sn
                break
        if not target_sheet:
            target_sheet = xl.sheet_names[-1]
        sheet_name_in_xlsx = target_sheet

        # 梱包リストの実データは row4 以降(headerはrow3だがheader=Noneで取得)
        raw = pd.read_excel(uploaded, sheet_name=target_sheet,
                            dtype=str, header=None).fillna("")
        # row 1〜3はヘッダ系、row 4 (index 3) 以降がデータ
        if len(raw) >= 4:
            new_data = raw.iloc[3:].reset_index(drop=True)
        st.success(f"読込: 「{target_sheet}」シート / {len(new_data)}行")
    except Exception as e:
        st.error(f"読込失敗: {e}")
        import traceback
        st.code(traceback.format_exc())

if new_data is not None and not new_data.empty:
    # 梱包リストの列構成 (row3のヘッダから推定):
    # A箱NO/B箱寸法/C実際重量/D注文番号/E商品番号/F画像/G商品情報/H梱包数/I単価/J小計/K国内運賃/L_/M_/N商品コード/O箱詰備考/P配送履歴
    # → 06_入荷時 の同名列構造とマッチするので、そのまま A-P をコピー

    # プレビュー(梱包リスト4列だけ抜粋)
    preview_rows = []
    for i, r in new_data.head(8).iterrows():
        preview_rows.append({
            "箱NO":        r.iloc[0] if len(r) > 0 else "",
            "注文番号":     r.iloc[3] if len(r) > 3 else "",
            "商品番号":     r.iloc[4] if len(r) > 4 else "",
            "梱包数":       r.iloc[7] if len(r) > 7 else "",
            "商品コード":   r.iloc[13] if len(r) > 13 else "",
            "箱詰備考":     (r.iloc[14] if len(r) > 14 else "")[:30],
        })
    st.markdown("**👀 取込プレビュー(先頭8行)**")
    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

    # 全データを A〜P (16列) で構築
    rows_2d = []
    for _, r in new_data.iterrows():
        row = [""] * 16  # A〜P
        for j in range(min(16, len(r))):
            row[j] = str(r.iloc[j]).strip()
        # 全列空ならスキップ
        if any(c for c in row):
            rows_2d.append(row)

    st.caption(f"取込予定: {len(rows_2d)}行 / 既存: {len(df)}件")

    st.checkbox(
        "🔗 同じ商品管理番号(Q列)を集約する",
        value=False,
        key="aggregate_q_rows",
        help="OFF=Excel通り全行そのまま / ON=同一商品管理番号を1行に集約",
    )

    if rows_2d and st.button(
        f"📤 「{sheet_name_in_xlsx}」を 06_入荷時 に追加",
        type="primary", use_container_width=True, key="arr_rakumart_apply",
    ):
        with st.spinner("書込中..."):
            try:
                sh = sheets.get_spreadsheet()
                ws = sh.worksheet(SHEET_NAME)

                # マスタを先読みして 小分類→(係数, 商品コード) の辞書を作る
                # (各行で XLOOKUP を発火させずに Python側で解決して値で書き込む)
                master_ws_local = sh.worksheet("03_商品マスタ参照")
                master_a = master_ws_local.col_values(1)   # A列(商品コード)
                master_e = master_ws_local.col_values(5)   # E列(小分類)
                master_y = master_ws_local.col_values(25)  # Y列(発注時係数)
                kogo_to_ratio: dict[str, str] = {}
                kogo_to_code: dict[str, str] = {}
                for i, e_v in enumerate(master_e):
                    if i < 6:  # ヘッダ行までスキップ
                        continue
                    key = str(e_v or "").strip()
                    if not key:
                        continue
                    val = master_y[i] if i < len(master_y) else ""
                    code = master_a[i] if i < len(master_a) else ""
                    if key not in kogo_to_ratio:
                        kogo_to_ratio[key] = str(val).strip()
                        kogo_to_code[key] = str(code).strip()

                # 既存データの最終行を検出 (D列=注文番号で実データ判定、データ行はrow6から)
                d_col = ws.col_values(4)
                last_data_row = max(
                    [i + 1 for i, v in enumerate(d_col) if v.strip() and i + 1 >= 6] + [5]
                )
                start_row = last_data_row + 1

                # 各行の N/Q/R を Python側で計算して値として書き込む (数式を使わない)
                # Q列(商品管理番号) = O列(箱詰備考)の1行目
                # R列(係数) = マスタE列でQ列を引いてY列を返す
                # N列(商品コード) = マスタE列でQ列を引いてA列を返す ★これを追加
                #   → 04_在庫管理 のA列と一致する正規の商品コード
                rows_full = []
                for base_row in rows_2d:
                    full_row = list(base_row) + ["", ""]  # 16=Q, 17=R
                    o_value = str(full_row[14] or "").strip() if len(full_row) > 14 else ""
                    # 改行があれば1行目だけ取る
                    q_value = o_value.split("\n")[0].split("\r")[0] if o_value else ""
                    full_row[16] = q_value
                    full_row[17] = kogo_to_ratio.get(q_value, "")
                    # N列(商品コード) が空なら、Q列(品名) → マスタE列 → マスタA列で逆引き
                    n_current = str(full_row[13] or "").strip() if len(full_row) > 13 else ""
                    if not n_current and q_value:
                        resolved_code = kogo_to_code.get(q_value, "")
                        if resolved_code:
                            full_row[13] = resolved_code
                    rows_full.append(full_row)

                # ===========================================================
                # ✅ SKU空チェック (N列=商品コード が空 = 商品管理番号Qも空 → アラート)
                # ===========================================================
                sku_empty_rows = []
                for idx, r in enumerate(rows_full):
                    n_v = str(r[13] or "").strip() if len(r) > 13 else ""
                    q_v = str(r[16] or "").strip() if len(r) > 16 else ""
                    # N列(商品コード)・Q列(商品管理番号) どちらも空 → エラー
                    if not n_v and not q_v:
                        sku_empty_rows.append((idx + 1, r))

                if sku_empty_rows:
                    st.warning(
                        f"⚠ **SKU(商品コード/商品管理番号) が空の行が {len(sku_empty_rows)}件あります**。"
                        f"反映できないので、スプシで N列(商品コード) または O列(箱詰備考)の1行目 を埋めてください。"
                    )
                    with st.expander(f"⚠ SKU空 行リスト ({len(sku_empty_rows)}件)"):
                        for idx, r in sku_empty_rows[:30]:
                            d_no = r[3] if len(r) > 3 else ""
                            info = r[6][:30] if len(r) > 6 and r[6] else ""
                            st.write(f"  行{idx}: 注文番号={d_no} / 商品情報={info}")

                # ===========================================================
                # 集約モード: チェックボックスで切替
                # ===========================================================
                if st.session_state.get("aggregate_q_rows", False):
                    def _q_key(r):
                        q = str(r[16] or "").strip() if len(r) > 16 else ""
                        return q

                    def _f_n(v):
                        try:
                            return float(str(v or "").replace(",", "").strip() or 0)
                        except (ValueError, TypeError):
                            return 0.0

                    grouped: dict[str, list] = {}
                    preserved: list = []
                    for r in rows_full:
                        key = _q_key(r)
                        if not key:
                            preserved.append(r)
                            continue
                        if key not in grouped:
                            grouped[key] = list(r)
                        else:
                            existing_h = _f_n(grouped[key][7] if len(grouped[key]) > 7 else 0)
                            new_h = _f_n(r[7] if len(r) > 7 else 0)
                            merged_h = existing_h + new_h
                            grouped[key][7] = int(merged_h) if merged_h == int(merged_h) else merged_h
                            existing_k = grouped[key][10] if len(grouped[key]) > 10 else ""
                            new_k = r[10] if len(r) > 10 else ""
                            if (not existing_k or _f_n(existing_k) == 0) and new_k:
                                grouped[key][10] = new_k

                    merged_count_diff = len(rows_full) - (len(grouped) + len(preserved))
                    rows_to_write = list(grouped.values()) + preserved
                else:
                    # 集約しない: そのまま74行全部書く
                    rows_to_write = rows_full
                    merged_count_diff = 0

                # Q列(商品管理番号) と R列(係数) はスプシのARRAYFORMULAに任せる
                # → A:P 列まで書込
                rows_to_write_ap = [r[:16] for r in rows_to_write]
                end_col = "P"
                range_str = f"A{start_row}:{end_col}{start_row + len(rows_to_write_ap) - 1}"
                ws.update(
                    range_name=range_str, values=rows_to_write_ap,
                    value_input_option="USER_ENTERED",
                )
                sheets._invalidate_one(SHEET_NAME)

                msg = (
                    f"✅ {len(rows_to_write)}行 追加完了 "
                    f"(取込{len(rows_full)}行 → 集約{merged_count_diff}行統合)"
                )
                if sku_empty_rows:
                    msg += f"\n⚠ SKU空 {len(sku_empty_rows)}件はアラートに表示中"
                st.success(msg)
                st.balloons()
                st.rerun()
            except Exception as e:
                st.error(f"取込失敗: {e}")
                import traceback
                st.code(traceback.format_exc())
