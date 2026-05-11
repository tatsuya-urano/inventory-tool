"""
📦 FBA補充プラン

GAS版 generateFBARefillPlan を Python移植
- C列(物流ルート)="自社経由" のSKUのみ対象
- FBA必要在庫 = 販売速度 × Amazon比率(35%) × (14日サイクル+7日余裕)
- 補充推奨 = 必要在庫 - 現FBA在庫
- 補充可能 = min(補充推奨, 自社倉庫在庫)
- 段ボール推定（1箱10kg想定）
"""
import math

import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="FBA補充プラン", page_icon="📦", layout="wide")
st.title("📦 FBA補充プラン")
st.caption("自社倉庫からFBAへの補充推奨量を自動算出")
ui.sidebar_common()

# ===========================================================
# 設定
# ===========================================================
with st.expander("⚙️ 計算設定", expanded=False):
    cycle_days = st.number_input("補充サイクル（日）", 1, 60, 14)
    safety_days = st.number_input("安全在庫日数", 1, 30, 7)
    amazon_ratio = st.slider("Amazon販売比率", 0.0, 1.0, 0.35, 0.05)
    box_kg = st.number_input("段ボール1箱の想定kg", 1, 30, 10)

target_days = cycle_days + safety_days
st.caption(f"目標FBA在庫日数: {target_days}日 / Amazon販売比率: {amazon_ratio*100:.0f}%")

# ===========================================================
# データ取得
# ===========================================================
@st.cache_data(ttl=300, show_spinner="集計中...")
def _build_refill_plan(_cycle, _safety, _amz_ratio):
    inv = sheets.load_inventory()
    master = sheets.load_master()
    discontinued = sheets.load_any_sheet("17_終売SKU", header_row=1, data_start_row=2)

    if inv.empty or master.empty:
        return None

    # 04列定義
    INV_CODE     = inv.columns[0]
    INV_TITLE    = inv.columns[1]
    INV_ROUTE    = inv.columns[2]
    INV_FBA      = inv.columns[3]   # D列 FBA在庫
    INV_WH       = inv.columns[5]   # F列 自社倉庫在庫
    INV_VELOCITY = inv.columns[17]  # R列 計算用販売速度

    # マスタ列定義（重量= AA列 = 26）
    M_CODE = master.columns[0]
    M_WEIGHT = master.columns[26] if len(master.columns) > 26 else None

    def _n(v):
        try:
            return float(str(v).replace(",", "").replace("¥", "").strip())
        except (ValueError, TypeError):
            return 0.0

    weight_map = {}
    if M_WEIGHT:
        for code, w in zip(master[M_CODE].astype(str).str.strip(), master[M_WEIGHT]):
            if code:
                weight_map[code] = _n(w)

    discontinued_set = set()
    if not discontinued.empty:
        for v in discontinued.iloc[:, 0]:
            s = str(v).strip()
            if s:
                discontinued_set.add(s)

    target_d = _cycle + _safety
    targets = []
    for _, r in inv.iterrows():
        code = str(r[INV_CODE]).strip()
        if not code or code in discontinued_set:
            continue

        route = str(r[INV_ROUTE]).strip()
        # 自社経由のみ（FBA直送は対象外）
        if route != "自社経由":
            continue
        # 発注見送りSKUは17_終売SKUに登録され discontinued_set 経由で除外済

        fba_stock = _n(r[INV_FBA])
        wh_stock = _n(r[INV_WH])
        velocity = _n(r[INV_VELOCITY])

        amazon_velocity = velocity * _amz_ratio
        fba_target = amazon_velocity * target_d
        refill_recommend = max(0, math.ceil(fba_target - fba_stock))
        refill_available = min(refill_recommend, int(wh_stock))

        if refill_recommend == 0:
            continue

        weight = weight_map.get(code, 0)
        total_weight = round((refill_available * weight) / 1000, 2)

        targets.append({
            "商品コード": code,
            "タイトル": r[INV_TITLE],
            "自社倉庫在庫": int(wh_stock),
            "FBA在庫": int(fba_stock),
            "Amazon速度/日": round(amazon_velocity, 2),
            "FBA目標在庫": int(fba_target),
            "補充推奨": int(refill_recommend),
            "補充可能": int(refill_available),
            "確定数": int(refill_available),  # 初期値=補充可能
            "重量(kg)": total_weight,
        })

    return targets


targets = _build_refill_plan(cycle_days, safety_days, amazon_ratio)
if targets is None:
    st.error("データ取得失敗")
    st.stop()

if not targets:
    st.info("補充対象なし（全SKUがFBA在庫充足、または自社経由対象なし）")
    st.stop()

df = pd.DataFrame(targets)

# ===========================================================
# サマリ
# ===========================================================
total_units = int(df["確定数"].sum())
total_weight = round(df["重量(kg)"].sum(), 1)
estimated_boxes = math.ceil(total_weight / box_kg) if total_weight > 0 else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("補充対象SKU", len(df))
c2.metric("合計補充数", f"{total_units:,}")
c3.metric("合計重量", f"{total_weight}kg")
c4.metric("推定箱数", f"{estimated_boxes}箱")

st.markdown("---")

# ===========================================================
# フィルタ
# ===========================================================
keyword = st.text_input("商品コード・タイトル検索", "")
filtered = df.copy()
if keyword:
    mask = filtered["商品コード"].astype(str).str.contains(keyword, case=False, na=False)
    mask |= filtered["タイトル"].astype(str).str.contains(keyword, case=False, na=False)
    filtered = filtered[mask]

st.caption(f"表示中: {len(filtered):,} / {len(df):,} 件")

# ===========================================================
# 編集テーブル（確定数を変更可能）
# ===========================================================
edited = st.data_editor(
    filtered,
    use_container_width=True,
    height=500,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "商品コード":     st.column_config.TextColumn(disabled=True),
        "タイトル":       st.column_config.TextColumn(disabled=True),
        "自社倉庫在庫":   st.column_config.NumberColumn(disabled=True),
        "FBA在庫":        st.column_config.NumberColumn(disabled=True),
        "Amazon速度/日":  st.column_config.NumberColumn(disabled=True, format="%.2f"),
        "FBA目標在庫":    st.column_config.NumberColumn(disabled=True),
        "補充推奨":       st.column_config.NumberColumn(disabled=True),
        "補充可能":       st.column_config.NumberColumn(disabled=True),
        "確定数":         st.column_config.NumberColumn(label="🟢 確定数", min_value=0, step=1),
        "重量(kg)":       st.column_config.NumberColumn(disabled=True, format="%.2f"),
    },
    key="fba_editor",
)

# ===========================================================
# CSV出力 + スプシへ書き戻し
# ===========================================================
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    csv = edited.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "💾 CSVダウンロード",
        csv,
        file_name=f"fba_refill_{len(edited)}rows.csv",
        mime="text/csv",
    )
with col2:
    if st.button("📤 スプシ「12_FBA補充プラン」に書き戻し"):
        with st.spinner("書込中..."):
            try:
                ss = sheets.get_spreadsheet()
                ws = ss.worksheet("12_FBA補充プラン")
                last_row = ws.row_count
                if last_row >= 7:
                    ws.batch_clear([f"A7:M{last_row}"])
                # GAS仕様の13列形式
                gas_cols = ["商品コード", "タイトル", "自社倉庫在庫", "FBA在庫", "Amazon速度/日",
                            "FBA目標在庫", "補充推奨", "補充可能", "確定数", "重量(kg)"]
                rows = []
                for _, r in edited.iterrows():
                    rows.append([
                        r["商品コード"], "", r["タイトル"],  # ASINは空
                        r["自社倉庫在庫"], r["FBA在庫"], r["Amazon速度/日"],
                        r["FBA目標在庫"], r["補充推奨"], r["補充可能"], r["確定数"],
                        estimated_boxes, r["重量(kg)"], ""
                    ])
                if rows:
                    ws.update(range_name="A7", values=rows, value_input_option="USER_ENTERED")
                sheets._invalidate_one("12_FBA補充プラン")
                st.success(f"✅ {len(rows)}行を書き戻しました")
                st.balloons()
            except Exception as e:
                st.error(f"失敗: {e}")
