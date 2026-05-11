"""
🛒 推奨発注リスト

GAS版 generateOrderRecommendation を Python移植
- 04のM列(推奨発注数)>0 のSKUを抽出
- 17_終売SKUに登録あれば除外
- ステータス順にソート
- 累計金額が月間上限超えたら「次回繰越」マーク
"""
import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="推奨発注リスト", page_icon="🛒", layout="wide")
st.title("🛒 推奨発注リスト")
st.caption("04_在庫管理 のM列(推奨発注数)>0 のSKUを集計、ステータス順にソート")
ui.sidebar_common()

# ===========================================================
# データ取得
# ===========================================================
@st.cache_data(ttl=300, show_spinner="集計中...")
def _build_order_recommendation():
    inv = sheets.load_inventory()
    master = sheets.load_master()
    discontinued = sheets.load_any_sheet("17_終売SKU", header_row=1, data_start_row=2)

    if inv.empty or master.empty:
        return None

    # 04列定義
    INV_CODE   = inv.columns[0]
    INV_TITLE  = inv.columns[1]
    INV_ROUTE  = inv.columns[2]
    INV_TOTAL  = inv.columns[7]   # H列（販売可能在庫合計＝現在在庫）
    INV_RECO   = inv.columns[12]  # M列（推奨発注数）
    INV_CORR   = inv.columns[16]  # Q列（補正倍率）
    INV_SALES90 = inv.columns[15]  # P列（過去90日販売数）
    INV_DAYS   = inv.columns[18]  # S列（在庫日数）
    INV_STATUS = inv.columns[19]  # T列（ステータス）

    # マスタ列定義（H列原価）
    M_CODE = master.columns[0]
    M_COST = master.columns[7]  # H列

    def _n(v):
        try:
            return float(str(v).replace(",", "").replace("¥", "").strip())
        except (ValueError, TypeError):
            return 0.0

    # マスタ→原価マップ
    cost_map = {}
    for code, c in zip(master[M_CODE].astype(str).str.strip(), master[M_COST]):
        if code:
            cost_map[code] = _n(c)

    # 終売SKUセット
    discontinued_set = set()
    if not discontinued.empty:
        for v in discontinued.iloc[:, 0]:
            s = str(v).strip()
            if s:
                discontinued_set.add(s)

    # 推奨発注対象抽出（発注見送りSKUは17_終売SKUに登録され M列=0 になるため自動除外）
    candidates = []
    for _, r in inv.iterrows():
        code = str(r[INV_CODE]).strip()
        recommend = _n(r[INV_RECO])
        if not code or recommend <= 0:
            continue
        if code in discontinued_set:
            continue
        # 在庫日数60日超は除外 (2週に1回発注運用、リードタイム60日想定)
        if _n(r[INV_DAYS]) > 60:
            continue

        cost = cost_map.get(code, 0)
        subtotal = recommend * cost
        sales_90 = _n(r[INV_SALES90])
        avg_sales = round(sales_90 / 90, 1)

        candidates.append({
            "商品コード": code,
            "タイトル": r[INV_TITLE],
            "物流ルート": r[INV_ROUTE],
            "現在在庫": int(_n(r[INV_TOTAL])),
            "在庫日数": _n(r[INV_DAYS]),
            "ステータス": str(r[INV_STATUS]),
            "1日平均販売": avg_sales,
            "補正倍率": r[INV_CORR],
            "推奨発注数": int(recommend),
            "原価": cost,
            "小計": int(subtotal),
        })

    return candidates


candidates = _build_order_recommendation()
if candidates is None:
    st.error("データ取得失敗")
    st.stop()

if not candidates:
    st.warning("推奨発注対象なし")
    st.stop()

# ===========================================================
# ステータス順ソート（赤→オレンジ→黄→緑→紫）
# ===========================================================
status_order = {
    "🔴危険": 1,
    "🟠要発注": 2,
    "🟡注意": 3,
    "🟢余裕": 4,
    "🟣過剰": 5,
}
candidates.sort(key=lambda c: (status_order.get(c["ステータス"], 9), c["在庫日数"]))

# ===========================================================
# 月間上限とのチェック
# ===========================================================
default_limit = 1_000_000
monthly_limit = st.number_input(
    "月間発注上限（円）",
    min_value=0,
    value=default_limit,
    step=100_000,
    help="累計小計がこの金額を超えたら「次回繰越」マーク",
)

cumulative = 0
priority = 0
for c in candidates:
    priority += 1
    cumulative += c["小計"]
    c["優先度"] = priority
    c["累計金額"] = cumulative
    c["判定"] = "✅発注推奨" if cumulative <= monthly_limit else "⚠️次回繰越"

df = pd.DataFrame(candidates)

# 列順序
df = df[["優先度", "ステータス", "商品コード", "タイトル", "物流ルート",
         "現在在庫", "在庫日数", "1日平均販売", "補正倍率", "推奨発注数", "原価", "小計", "累計金額", "判定"]]

# ===========================================================
# サマリ
# ===========================================================
in_limit = df[df["判定"] == "✅発注推奨"]
over_limit = df[df["判定"] == "⚠️次回繰越"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("総候補", len(df))
c2.metric("✅発注推奨", len(in_limit))
c3.metric("⚠️次回繰越", len(over_limit))
c4.metric("発注推奨 合計金額", f"¥{int(in_limit['小計'].sum()):,}")

st.markdown("---")

# ===========================================================
# フィルタ
# ===========================================================
from lib import user_prefs

PREF_KEY_HIDE = "page05_hide_excess"
saved_hide = user_prefs.get_pref(PREF_KEY_HIDE, True)

with st.expander("🔍 フィルタ", expanded=False):
    col1, col2 = st.columns(2)
    with col1:
        keyword = st.text_input("商品コード・タイトル検索", "")
    with col2:
        status_opts = ["（全て）"] + sorted(df["ステータス"].unique().tolist())
        sel_status = st.selectbox("ステータス", status_opts)

    hide_excess = st.checkbox(
        "🟣過剰 / 🟢余裕 を非表示にする（永続化）",
        value=saved_hide,
        key="hide_excess_chk",
    )
    if hide_excess != saved_hide:
        user_prefs.set_pref(PREF_KEY_HIDE, hide_excess)

filtered = df.copy()
if keyword:
    mask = filtered["商品コード"].astype(str).str.contains(keyword, case=False, na=False)
    mask |= filtered["タイトル"].astype(str).str.contains(keyword, case=False, na=False)
    filtered = filtered[mask]
if sel_status != "（全て）":
    filtered = filtered[filtered["ステータス"] == sel_status]
if hide_excess:
    # 絵文字バリエーション吸収のため文字列contains判定
    filtered = filtered[
        ~filtered["ステータス"].astype(str).str.contains("過剰|余裕", regex=True, na=False)
    ]
    # 在庫日数 >= 45日 (リードタイム以内に枯渇しない) も非表示
    if "在庫日数" in filtered.columns:
        days_num = pd.to_numeric(filtered["在庫日数"], errors="coerce")
        filtered = filtered[days_num < 45]

st.caption(f"表示中: {len(filtered):,} / {len(df):,} 件")

# ===========================================================
# テーブル表示
# ===========================================================
st.dataframe(
    filtered,
    use_container_width=True,
    height=500,
    hide_index=True,
    column_config={
        "原価":     st.column_config.NumberColumn(format="¥%d"),
        "小計":     st.column_config.NumberColumn(format="¥%d"),
        "累計金額": st.column_config.NumberColumn(format="¥%d"),
    },
)

# ===========================================================
# CSV出力 + スプシへ書き戻し
# ===========================================================
st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    csv = filtered.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "💾 CSVダウンロード",
        csv,
        file_name=f"order_recommendation_{len(filtered)}rows.csv",
        mime="text/csv",
    )

with col2:
    if st.button("📤 スプシ「11_推奨発注リスト」に書き戻し"):
        with st.spinner("書込中..."):
            try:
                ss = sheets.get_spreadsheet()
                ws = ss.worksheet("11_推奨発注リスト")
                # 6行目以降をクリア
                last_row = ws.row_count
                if last_row >= 6:
                    ws.batch_clear([f"A6:N{last_row}"])
                # 14列形式で書込（GAS互換）
                gas_cols = ["優先度", "商品コード", "タイトル", "物流ルート",
                            "在庫日数", "ステータス", "1日平均販売", "補正倍率",
                            "推奨発注数", "原価", "小計", "累計金額", "判定"]
                out_df = filtered[gas_cols].copy()
                out_df["メモ"] = ""
                values = out_df.fillna("").astype(str).values.tolist()
                if values:
                    ws.update(range_name="A6", values=values, value_input_option="USER_ENTERED")
                sheets._invalidate_one("11_推奨発注リスト")
                st.success(f"✅ {len(values)}行を書き戻しました")
                st.balloons()
            except Exception as e:
                st.error(f"失敗: {e}")
