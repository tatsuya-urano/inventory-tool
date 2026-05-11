"""
04_在庫管理 編集ページ — 一括保存版

編集可: 商品コード、統合タイトル、物流ルート、補正倍率、
        月初在庫(G)、当月入荷(I)、当月廃棄(J)
保護: 数式列(F/H/K/N/O/P)、GAS自動書込列(D/E/L/M/R/S/T)
"""
import pandas as pd
import streamlit as st

from lib import sheets, ui, user_prefs

st.set_page_config(page_title="在庫管理", page_icon="📋", layout="wide")
st.title("📋 04_在庫管理（編集可）")
ui.sidebar_common(this_sheet="04_在庫管理")

with st.spinner("読込中..."):
    df = sheets.load_inventory()

if df.empty:
    st.warning("データなし")
    st.stop()

EDITABLE_COLS = {
    "商品コード", "統合タイトル", "物流ルート", "補正倍率",
    "月初在庫", "当月入荷", "当月廃棄", "発注済み",
}
NUMERIC_EDITABLE_COLS = {"月初在庫", "当月入荷", "当月廃棄", "発注済み"}

# 数値列（読取専用も含む）→ NumberColumnで右寄せ統一
NUMERIC_COLS = {
    "FBA在庫", "FBA入庫処理中", "自社倉庫在庫", "月初在庫",
    "販売可能在庫合計", "当月入荷", "当月廃棄", "在庫金額",
    "発注済み", "推奨発注数", "当月販売数", "コバリ消費(対応)",
    "過去90日販売数", "補正倍率", "計算用販売速度", "在庫日数",
}
# 通貨表示する列
CURRENCY_COLS = {"在庫金額"}

# サマリ
status_col = None
for c in ["ステータス"] + ([df.columns[19]] if len(df.columns) > 19 else []):
    if c in df.columns:
        status_col = c
        break

c1, c2, c3, c4 = st.columns(4)
c1.metric("総SKU数", f"{len(df):,}")
if status_col:
    counts = df[status_col].value_counts()
    c2.metric("🔴危険", int(counts.get("🔴危険", 0)))
    c3.metric("🟠要発注", int(counts.get("🟠要発注", 0)))
    c4.metric("🟣過剰", int(counts.get("🟣過剰", 0)))

st.markdown("---")
st.markdown("**凡例**: 🟢 編集可 / 🔒 数式 or GAS自動書込")

# フィルタ
with st.expander("🔍 フィルタ", expanded=True):
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        keyword = st.text_input("商品コード・タイトル検索", "")
    with col2:
        if status_col:
            opts = ["（全て）"] + sorted(df[status_col].dropna().unique().tolist())
            sel_status = st.selectbox("ステータス", opts)
        else:
            sel_status = "（全て）"
    with col3:
        if len(df.columns) > 2:
            route_col = df.columns[2]
            route_opts = ["（全て）"] + sorted(df[route_col].dropna().unique().tolist())
            sel_route = st.selectbox(f"{route_col}", route_opts)
        else:
            sel_route = "（全て）"
            route_col = None

filtered = df.copy()
if keyword:
    keywords = [k.strip() for k in keyword.split(",") if k.strip()]
    masks = []
    for k in keywords:
        m = filtered.iloc[:, 0].astype(str).str.contains(k, case=False, na=False)
        if len(filtered.columns) > 1:
            m |= filtered.iloc[:, 1].astype(str).str.contains(k, case=False, na=False)
        masks.append(m)
    if masks:
        combined = masks[0]
        for m in masks[1:]:
            combined |= m
        filtered = filtered[combined]
if status_col and sel_status != "（全て）":
    filtered = filtered[filtered[status_col] == sel_status]
if route_col and sel_route != "（全て）":
    filtered = filtered[filtered[route_col] == sel_route]

st.caption(f"表示中: {len(filtered):,} / {len(df):,} 件")

# ===========================================================
# 表示列カスタマイズ（永続化）
# ===========================================================
PREF_KEY = "page01_inv_visible_cols"
all_cols = list(filtered.columns)

# 永続化ファイル → session_state → 既定 の順で復元
if "_inv_visible_cols" not in st.session_state:
    st.session_state["_inv_visible_cols"] = user_prefs.get_pref(PREF_KEY, all_cols)
saved_visible = [c for c in st.session_state["_inv_visible_cols"] if c in all_cols]
if not saved_visible:
    saved_visible = all_cols


def _apply_inv_cols(cols):
    st.session_state["_inv_visible_cols"] = cols
    user_prefs.set_pref(PREF_KEY, cols)


with st.expander(f"📐 表示列カスタマイズ（現在 {len(saved_visible)}/{len(all_cols)}列）", expanded=False):
    st.caption("プリセット（クリックで即適用・永続化）")
    pc1, pc2, pc3 = st.columns(3)
    if pc1.button("全て表示", use_container_width=True, key="inv_cols_all"):
        _apply_inv_cols(all_cols)
        st.rerun()
    if pc2.button("編集列のみ", use_container_width=True, key="inv_cols_editable",
                  help="商品コード/タイトル/物流ルート/補正倍率/月初在庫/当月入荷/当月廃棄"):
        _apply_inv_cols([c for c in all_cols if c in EDITABLE_COLS])
        st.rerun()
    if pc3.button("コア指標のみ", use_container_width=True, key="inv_cols_core",
                  help="商品コード/タイトル/販売可能在庫/在庫日数/ステータス"):
        core = ["商品コード", "統合タイトル", "販売可能在庫合計", "在庫日数", "ステータス"]
        _apply_inv_cols([c for c in core if c in all_cols])
        st.rerun()

    st.markdown("---")
    st.caption("カスタム選択（×で外す/プルダウンから追加 → 「✅ 適用」で反映・永続化）")
    mc1, mc2 = st.columns([4, 1])
    with mc1:
        pending_cols = st.multiselect(
            "表示する列",
            options=all_cols,
            default=saved_visible,
            key="_inv_visible_cols_ms",
            label_visibility="collapsed",
        )
    with mc2:
        if st.button("✅ 適用", use_container_width=True, type="primary", key="inv_cols_apply"):
            _apply_inv_cols(pending_cols if pending_cols else all_cols)
            st.rerun()

    if pending_cols != saved_visible:
        st.info(f"📝 選択中: {len(pending_cols)}列 — 「✅ 適用」を押して反映")

visible_cols = saved_visible
display_df = filtered[visible_cols]

# 数値列を pandas.to_numeric で前処理（NumberColumn は数値型じゃないと表示が崩れる）
for col in display_df.columns:
    if col in NUMERIC_COLS:
        display_df[col] = pd.to_numeric(
            display_df[col].astype(str).str.replace(",", "").str.replace("¥", "").str.replace("-¥", "-"),
            errors="coerce",
        )

# 編集テーブル — 数値列は NumberColumn（右寄せ）、文字列は TextColumn（左寄せ）で統一
column_config = {}
for col in display_df.columns:
    is_editable = col in EDITABLE_COLS
    label = f"🟢 {col}" if is_editable else f"🔒 {col}"

    if col == "物流ルート":
        column_config[col] = st.column_config.SelectboxColumn(
            label=label,
            options=["", "自社経由", "FBA直送"],
            disabled=not is_editable,
        )
    elif col == "補正倍率":
        column_config[col] = st.column_config.NumberColumn(
            label=label,
            min_value=0.0, max_value=10.0, step=0.1,
            disabled=not is_editable,
        )
    elif col in CURRENCY_COLS:
        column_config[col] = st.column_config.NumberColumn(
            label=label, format="¥%d", disabled=not is_editable,
        )
    elif col in NUMERIC_COLS:
        column_config[col] = st.column_config.NumberColumn(
            label=label, format="%d", step=1, disabled=not is_editable,
        )
    else:
        column_config[col] = st.column_config.TextColumn(
            label=label, disabled=not is_editable,
        )

edited = st.data_editor(
    display_df,
    use_container_width=True,
    height=600,
    hide_index=True,
    num_rows="fixed",
    column_config=column_config,
    key="inv_editor",
)

# 変更検出（実際のスプシ列位置はoriginalのfiltered.columnsから引く）
all_filtered_cols = list(filtered.columns)


def _same_value(a, b) -> bool:
    """NaN・空文字・数値型違いを吸収して同値判定"""
    a_na = pd.isna(a) if not isinstance(a, str) else False
    b_na = pd.isna(b) if not isinstance(b, str) else False
    if a_na and b_na:
        return True
    if a_na:
        return b == "" or b is None
    if b_na:
        return a == "" or a is None
    try:
        return float(a) == float(b)
    except (ValueError, TypeError):
        return str(a).strip() == str(b).strip()


diffs = []
for idx in filtered.index:
    pos = filtered.index.get_loc(idx)
    for col_name in display_df.columns:
        if col_name not in EDITABLE_COLS:
            continue
        sheet_col_pos = all_filtered_cols.index(col_name)  # 0-indexed
        # 比較は display_df(数値変換済) と edited で apples-to-apples
        display_col_pos = list(display_df.columns).index(col_name)
        old_val = display_df.iloc[pos, display_col_pos]
        new_val = edited.iloc[pos, list(edited.columns).index(col_name)]
        if _same_value(old_val, new_val):
            continue
        diffs.append({
            "行": idx + 7,
            "商品コード": filtered.iloc[pos, 0],
            "列": col_name,
            "旧": old_val,
            "新": new_val,
            "_sheet_row": idx + 7,
            "_sheet_col": sheet_col_pos + 1,
        })

st.markdown("---")

# ===========================================================
# 自動保存（編集確定後の Enter / Tab で即書き戻し）
# ===========================================================
if diffs:
    try:
        ss = sheets.get_spreadsheet()
        ws = ss.worksheet("04_在庫管理")
        requests = []
        for d in diffs:
            cell = f"{sheets._col_index_to_letter(d['_sheet_col'])}{d['_sheet_row']}"
            new_val = d["新"]
            if pd.isna(new_val):
                new_val = ""
            # numpy型(int64/float64)を Python ネイティブに変換 (JSON化対応)
            elif hasattr(new_val, "item"):
                try:
                    new_val = new_val.item()
                except (AttributeError, ValueError):
                    new_val = str(new_val)
            requests.append({"range": cell, "values": [[new_val]]})
        sheets.safe_batch_update(ws, requests, value_input_option="USER_ENTERED")
        sheets._invalidate_one("04_在庫管理")
        st.toast(f"💾 自動保存 {len(diffs)}件", icon="✅")
        st.rerun()
    except Exception as e:
        st.error(f"❌ 自動保存失敗: {e}")
        diff_df = pd.DataFrame(diffs)[["行", "商品コード", "列", "旧", "新"]]
        st.dataframe(diff_df, use_container_width=True, hide_index=True, height=200)
else:
    st.caption("✅ 変更なし（編集→Enterで自動保存されます）")

st.markdown("---")
csv = filtered.to_csv(index=False).encode("utf-8-sig")
st.download_button("💾 CSVダウンロード", csv, file_name=f"inventory_{len(filtered)}rows.csv", mime="text/csv")

# ===========================================================
# 発注済み(L列)CSV一括更新
# ===========================================================
st.markdown("---")
with st.expander("📦 発注済み(L列) CSV一括更新", expanded=False):
    st.caption(
        "**ヘッダ必須**: `商品コード,発注済み` の2列CSV。\n"
        "アップロード→ 04のL列を一括上書き → 完了後はリセットボタンで0クリア可能"
    )

    # テンプレダウンロード
    template_csv = "商品コード,発注済み\nexample_sku,10\n".encode("utf-8-sig")
    st.download_button(
        "📥 テンプレCSVダウンロード", template_csv,
        file_name="ordered_template.csv", mime="text/csv",
    )

    uploaded_ordered = st.file_uploader(
        "発注済みCSVファイル", type=["csv"], key="ordered_csv_upload"
    )

    mode = st.radio(
        "書込モード",
        ["➕ 加算（既存値 + CSV値）", "🔄 上書き（CSV値で置換）"],
        index=0,
        key="ordered_mode",
        horizontal=True,
    )
    is_add_mode = mode.startswith("➕")

    if uploaded_ordered is not None:
        try:
            ordered_df = pd.read_csv(uploaded_ordered, dtype=str).fillna("")
        except UnicodeDecodeError:
            uploaded_ordered.seek(0)
            ordered_df = pd.read_csv(uploaded_ordered, dtype=str, encoding="cp932").fillna("")

        if len(ordered_df.columns) < 2:
            st.error("CSVに2列以上必要（商品コード, 発注済み）")
        else:
            sku_col = ordered_df.columns[0]
            qty_col = ordered_df.columns[1]
            st.caption(f"読込: {len(ordered_df)}行 / SKU列=`{sku_col}` / 数量列=`{qty_col}`")
            st.dataframe(ordered_df.head(10), use_container_width=True, hide_index=True)

            # 04のSKU→行番号マップ + 既存L列値マップ
            inv_a_col = df.iloc[:, 0].astype(str).str.strip()
            sku_to_row = {c: i + 7 for i, c in enumerate(inv_a_col)}
            # 既存L列値（発注済み列）
            L_COL_NAME = df.columns[11] if len(df.columns) > 11 else None
            existing_qty = {}
            if L_COL_NAME:
                for i, c in enumerate(inv_a_col):
                    try:
                        v = pd.to_numeric(df.iloc[i][L_COL_NAME], errors="coerce")
                        existing_qty[c] = int(v) if pd.notna(v) else 0
                    except Exception:
                        existing_qty[c] = 0

            # CSV内同SKUは加算してまとめる（加算モード時のみ）
            csv_sku_qty: dict[str, int] = {}
            for _, row in ordered_df.iterrows():
                sku = str(row[sku_col]).strip()
                try:
                    qty = int(float(str(row[qty_col]).replace(",", "").strip()))
                except (ValueError, TypeError):
                    qty = 0
                if not sku:
                    continue
                if is_add_mode:
                    csv_sku_qty[sku] = csv_sku_qty.get(sku, 0) + qty
                else:
                    csv_sku_qty[sku] = qty  # 上書きモード=最後の値で置換

            updates = []
            unmatched = []
            preview = []
            for sku, qty in csv_sku_qty.items():
                if sku not in sku_to_row:
                    unmatched.append(sku)
                    continue
                old = existing_qty.get(sku, 0)
                new_val = old + qty if is_add_mode else qty
                updates.append({"range": f"L{sku_to_row[sku]}", "values": [[new_val]]})
                preview.append({"商品コード": sku, "既存": old, "CSV": qty, "結果": new_val})

            st.info(f"反映対象: {len(updates)}件 / マスタにないSKU: {len(unmatched)}件 / モード: {'加算' if is_add_mode else '上書き'}")
            if preview:
                st.caption("プレビュー（上位20件）")
                st.dataframe(pd.DataFrame(preview).head(20), use_container_width=True, hide_index=True)
            if unmatched:
                st.warning(f"⚠ マスタにないSKU {len(unmatched)}件: {unmatched[:20]}{'...' if len(unmatched) > 20 else ''}")

            if st.button("🚀 04のL列に書込実行", type="primary", key="apply_ordered"):
                if updates:
                    try:
                        ss = sheets.get_spreadsheet()
                        ws = ss.worksheet("04_在庫管理")
                        CHUNK = 200
                        for i in range(0, len(updates), CHUNK):
                            sheets.safe_batch_update(ws, updates[i:i + CHUNK], value_input_option="USER_ENTERED")
                        sheets._invalidate_one("04_在庫管理")
                        st.success(f"✅ {len(updates)}件 L列(発注済み)を{'加算' if is_add_mode else '上書き'}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"書込失敗: {e}")

    st.markdown("---")
    st.caption("⚠ 発注済みを一括0クリアしたい場合（届いた後の整理用）")
    if st.button("🧹 全SKUの発注済みを0にリセット", key="reset_ordered"):
        try:
            ss = sheets.get_spreadsheet()
            ws = ss.worksheet("04_在庫管理")
            updates_clear = [
                {"range": f"L{i+7}", "values": [[0]]}
                for i, c in enumerate(df.iloc[:, 0].astype(str).str.strip())
                if c
            ]
            CHUNK = 200
            for i in range(0, len(updates_clear), CHUNK):
                sheets.safe_batch_update(ws, updates_clear[i:i + CHUNK], value_input_option="USER_ENTERED")
            sheets._invalidate_one("04_在庫管理")
            st.success(f"✅ {len(updates_clear)}件 L列を0クリア")
            st.rerun()
        except Exception as e:
            st.error(f"クリア失敗: {e}")
