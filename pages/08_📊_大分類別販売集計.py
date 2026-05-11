"""
09_大分類別販売集計（Python計算版・キャッシュ高速化）

大分類 × チャネル群（楽天/Amazon） × 月 の3次元集計
"""
from datetime import date

import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="大分類別販売集計", page_icon="📊", layout="wide")
st.title("📊 大分類別販売集計")
ui.sidebar_common()


# ===========================================================
# 重い前処理をキャッシュ（売上に「大分類」「チャネル群」列を付与）
# ===========================================================
@st.cache_data(ttl=300, show_spinner="売上+マスタ前処理中...")
def _build_enriched_sales():
    sales = sheets.load_sales()
    master = sheets.load_master()
    if sales.empty or master.empty:
        return None

    def _col(df, idx):
        return df.columns[idx] if idx < len(df.columns) else None

    DATE_C    = _col(sales, 0)
    CHANNEL_C = _col(sales, 1)
    CODE_C    = _col(sales, 3)
    QTY_C     = _col(sales, 6)
    AMOUNT_C  = _col(sales, 8)
    COST_C    = _col(sales, 9)
    FEE_C     = _col(sales, 10)
    SHIP_C    = _col(sales, 11)
    PROFIT_C  = _col(sales, 14)

    M_CODE = master.columns[0]
    M_BIG_CAT = master.columns[3] if len(master.columns) > 3 else None

    sales = sales.copy()
    sales[DATE_C] = pd.to_datetime(sales[DATE_C], errors="coerce")
    sales = sales.dropna(subset=[DATE_C])

    def _to_num(s):
        return pd.to_numeric(s.astype(str).str.replace(",", "").str.replace("¥", ""), errors="coerce").fillna(0)

    for c in [QTY_C, AMOUNT_C, COST_C, FEE_C, SHIP_C, PROFIT_C]:
        if c and c in sales.columns:
            sales[c] = _to_num(sales[c])

    # マスタから dict 構築
    code_to_cat = {}
    if M_BIG_CAT:
        for code, cat in zip(master[M_CODE].astype(str), master[M_BIG_CAT].astype(str)):
            code_clean = code.strip()
            cat_clean = cat.strip() if cat else ""
            if code_clean:
                code_to_cat[code_clean] = cat_clean or "(未分類)"

    sales["_大分類"] = sales[CODE_C].astype(str).str.strip().map(code_to_cat).fillna("(未分類)")

    # チャネル群（vectorized）
    sales["_チャネル群"] = sales[CHANNEL_C].map({
        "楽天": "楽天",
        "Amazon FBA": "Amazon",
        "Amazon FBM": "Amazon",
    }).fillna("その他")

    return {
        "df": sales,
        "DATE_C": DATE_C,
        "CHANNEL_C": CHANNEL_C,
        "QTY_C": QTY_C,
        "AMOUNT_C": AMOUNT_C,
        "PROFIT_C": PROFIT_C,
    }


_d = _build_enriched_sales()
if _d is None:
    st.warning("データなし")
    st.stop()

sales    = _d["df"]
DATE_C   = _d["DATE_C"]
QTY_C    = _d["QTY_C"]
AMOUNT_C = _d["AMOUNT_C"]
PROFIT_C = _d["PROFIT_C"]

# ===========================================================
# フィルタ（期間絞りで高速化）
# ===========================================================
with st.expander("🔍 フィルタ", expanded=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        years = sorted(sales[DATE_C].dt.year.unique().tolist(), reverse=True)
        sel_year = st.selectbox("対象年", years, index=0 if years else None)
    with col2:
        # 月の範囲指定で軽量化
        all_months = list(range(1, 13))
        sel_months = st.multiselect(
            "対象月（複数選択可、未選択=全月）",
            all_months,
            default=[],
            help="月を絞ると高速化",
        )
    with col3:
        ch_groups = ["（全て）", "楽天", "Amazon"]
        sel_chg = st.selectbox("チャネル群", ch_groups)

with st.spinner("集計中..."):
    filtered = sales[sales[DATE_C].dt.year == sel_year].copy()
    if sel_months:
        filtered = filtered[filtered[DATE_C].dt.month.isin(sel_months)]
    if sel_chg != "（全て）":
        filtered = filtered[filtered["_チャネル群"] == sel_chg]
    st.caption(f"対象データ: {len(filtered):,}行")

if filtered.empty:
    st.warning("該当データなし")
    st.stop()

# ===========================================================
# 集計
# ===========================================================
filtered["_月"] = filtered[DATE_C].dt.month

# 大分類×月のピボット（売上）
pivot_revenue = filtered.pivot_table(
    index="_大分類",
    columns="_月",
    values=AMOUNT_C,
    aggfunc="sum",
    fill_value=0,
).round(0).astype(int)

pivot_qty = filtered.pivot_table(
    index="_大分類",
    columns="_月",
    values=QTY_C,
    aggfunc="sum",
    fill_value=0,
).astype(int)

pivot_profit = filtered.pivot_table(
    index="_大分類",
    columns="_月",
    values=PROFIT_C,
    aggfunc="sum",
    fill_value=0,
).round(0).astype(int)

# 月名 (1→1月)
pivot_revenue.columns = [f"{c}月" for c in pivot_revenue.columns]
pivot_qty.columns = [f"{c}月" for c in pivot_qty.columns]
pivot_profit.columns = [f"{c}月" for c in pivot_profit.columns]

# 合計列
pivot_revenue["年合計"] = pivot_revenue.sum(axis=1)
pivot_qty["年合計"] = pivot_qty.sum(axis=1)
pivot_profit["年合計"] = pivot_profit.sum(axis=1)

# 並び替え（年合計の降順）
pivot_revenue = pivot_revenue.sort_values("年合計", ascending=False)
pivot_qty = pivot_qty.reindex(pivot_revenue.index)
pivot_profit = pivot_profit.reindex(pivot_revenue.index)

# 合計行
total_rev = pivot_revenue.sum(numeric_only=True)
total_qty = pivot_qty.sum(numeric_only=True)
total_profit = pivot_profit.sum(numeric_only=True)
pivot_revenue.loc["🔵 全カテゴリ合計"] = total_rev
pivot_qty.loc["🔵 全カテゴリ合計"] = total_qty
pivot_profit.loc["🔵 全カテゴリ合計"] = total_profit

# ===========================================================
# 表示（タブ切替）
# ===========================================================
st.markdown(f"### {sel_year}年 大分類別 月推移（{sel_chg}）")

tab1, tab2, tab3, tab4 = st.tabs(["💰 売上", "📦 数量", "💎 利益", "📈 グラフ"])

with tab1:
    st.dataframe(pivot_revenue, use_container_width=True, height=600)
with tab2:
    st.dataframe(pivot_qty, use_container_width=True, height=600)
with tab3:
    st.dataframe(pivot_profit, use_container_width=True, height=600)
with tab4:
    # 大分類別の年合計売上（Top10）
    top10 = pivot_revenue.drop(index="🔵 全カテゴリ合計").nlargest(10, "年合計")
    st.markdown("#### 売上Top10カテゴリ")
    st.bar_chart(top10["年合計"])

    # 月別合計売上推移
    st.markdown("#### 月別売上推移")
    monthly_total = pivot_revenue.loc["🔵 全カテゴリ合計"].drop("年合計")
    st.line_chart(monthly_total)

# CSV
csv = pivot_revenue.to_csv().encode("utf-8-sig")
st.download_button(
    "💾 売上CSV出力",
    csv,
    file_name=f"category_revenue_{sel_year}.csv",
    mime="text/csv",
)
