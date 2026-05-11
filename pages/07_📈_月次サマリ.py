"""
15_サマリ - 月次×チャネル別 集計（Python計算版）

GAS仕様:
- 当月・前月・前々月 × 楽天/Amazon FBA/Amazon FBM/合計
- 売上, 手数料, 送料, 原価, 利益額, 利益率, 平均単価
- 広告費, アフィリエイト, ポイント, クーポン, 廃棄経費, 最終粗利
"""
from datetime import date, timedelta
from calendar import monthrange

import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="月次サマリ", page_icon="📈", layout="wide")
st.title("📈 月次サマリ（月×チャネル別）")
ui.sidebar_common()

# ===========================================================
# データ取得
# ===========================================================
with st.spinner("データ読込中..."):
    sales = sheets.load_sales()
    ad_df = sheets.load_any_sheet("広告費入力", header_row=1, data_start_row=2)
    storage_df = sheets.load_any_sheet("19_FBA保管料", header_row=1, data_start_row=2)

if sales.empty:
    st.warning("売上データなし")
    st.stop()

# 列同定
def _col(df, idx):
    return df.columns[idx] if idx < len(df.columns) else None

DATE_C    = _col(sales, 0)   # A 日付
CHANNEL_C = _col(sales, 1)   # B チャネル
QTY_C     = _col(sales, 6)   # G 数量
AMOUNT_C  = _col(sales, 8)   # I 売上
COST_C    = _col(sales, 9)   # J 原価
FEE_C     = _col(sales, 10)  # K 手数料
SHIP_C    = _col(sales, 11)  # L 送料
POINT_C   = _col(sales, 12)  # M 楽天ポイント
COUPON_C  = _col(sales, 13)  # N 楽天クーポン
PROFIT_C  = _col(sales, 14)  # O 利益額

# 日付パース
sales[DATE_C] = pd.to_datetime(sales[DATE_C], errors="coerce")
sales = sales.dropna(subset=[DATE_C])

# 数値変換
def _to_num_series(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.replace("¥", "").str.strip(), errors="coerce").fillna(0)

for c in [QTY_C, AMOUNT_C, COST_C, FEE_C, SHIP_C, POINT_C, COUPON_C, PROFIT_C]:
    if c and c in sales.columns:
        sales[c] = _to_num_series(sales[c])

# ===========================================================
# 広告費辞書
# ===========================================================
# 広告費入力シート: A 月 | B チャネル | C 広告(税抜) | D 広告(税込) | E アフィリ(税抜) | F アフィリ(手数料込) | G 備考
ad_lookup = {}  # (yyyy-MM, channel) → {ad: 0, aff: 0}
if not ad_df.empty:
    for _, r in ad_df.iterrows():
        try:
            month_str = str(r.iloc[0]).strip() if len(r) > 0 else ""
            channel = str(r.iloc[1]).strip() if len(r) > 1 else ""
            ad_inc = float(str(r.iloc[3]).replace(",", "")) if len(r) > 3 and str(r.iloc[3]).strip() else 0
            aff_inc = float(str(r.iloc[5]).replace(",", "")) if len(r) > 5 and str(r.iloc[5]).strip() else 0
            # 月キー正規化（"2026/04" → "2026-04"）
            mk = month_str.replace("/", "-")
            if len(mk) == 7:  # yyyy-MM
                ad_lookup[(mk, channel)] = {"ad": ad_inc, "aff": aff_inc}
        except (ValueError, IndexError):
            continue

# ===========================================================
# FBA保管料辞書: 月 → 合計保管料
# ===========================================================
storage_lookup: dict[str, float] = {}
if not storage_df.empty:
    for _, r in storage_df.iterrows():
        try:
            month_str = str(r.iloc[0]).strip().replace("/", "-") if len(r) > 0 else ""
            fee = float(str(r.iloc[4]).replace(",", "").replace("¥", "")) if len(r) > 4 and str(r.iloc[4]).strip() else 0
            if len(month_str) == 7:
                storage_lookup[month_str] = storage_lookup.get(month_str, 0) + fee
        except (ValueError, IndexError):
            continue

# ===========================================================
# 月リスト生成（過去12ヶ月）
# ===========================================================
today = date.today()

def month_range(year, month):
    start = date(year, month, 1)
    last_day = monthrange(year, month)[1]
    end = date(year, month, last_day)
    return start, end

# 月選択
n_months = st.slider("表示する過去月数", min_value=3, max_value=24, value=6)

months = []
y, m = today.year, today.month
for _ in range(n_months):
    months.append((y, m))
    m -= 1
    if m == 0:
        m = 12
        y -= 1

# ===========================================================
# 集計
# ===========================================================
CHANNELS = ["楽天", "Amazon FBA", "Amazon FBM"]

rows = []
for y, m in months:
    start, end = month_range(y, m)
    month_str = f"{y}-{m:02d}"
    month_data = sales[(sales[DATE_C].dt.date >= start) & (sales[DATE_C].dt.date <= end)]

    for ch in CHANNELS + ["🔵 合計"]:
        if ch == "🔵 合計":
            sub = month_data
        else:
            sub = month_data[month_data[CHANNEL_C] == ch]

        revenue  = float(sub[AMOUNT_C].sum())
        fee      = float(sub[FEE_C].sum())
        ship     = float(sub[SHIP_C].sum())
        cost     = float(sub[COST_C].sum())
        profit   = float(sub[PROFIT_C].sum())
        point    = float(sub[POINT_C].sum()) if POINT_C else 0
        coupon   = float(sub[COUPON_C].sum()) if COUPON_C else 0
        qty      = float(sub[QTY_C].sum())

        avg_price = revenue / qty if qty > 0 else 0
        rate = profit / revenue if revenue > 0 else 0

        # 広告費・アフィリ
        if ch == "🔵 合計":
            ad = sum(ad_lookup.get((month_str, c), {}).get("ad", 0) for c in CHANNELS)
            aff = sum(ad_lookup.get((month_str, c), {}).get("aff", 0) for c in CHANNELS)
        else:
            ad = ad_lookup.get((month_str, ch), {}).get("ad", 0)
            aff = ad_lookup.get((month_str, ch), {}).get("aff", 0)

        # 備考列(Q列, index 16)で各種判定
        if ch != "🔵 合計":
            memo_sub = sub
        else:
            memo_sub = month_data
        memo_col = memo_sub.columns[16] if len(memo_sub.columns) > 16 else None

        # VINE経費(VINE+プロモ+無償): 原価+送料+10円(VINEのみ)
        # Amazon FBAチャネル & Q列に「VINE/プロモ部分値引/無償販売」のいずれか
        vine_cost = 0
        vine_count = 0
        if memo_col is not None and ch in ("Amazon FBA", "🔵 合計"):
            memo_str = memo_sub[memo_col].astype(str)
            vine_mask = memo_str.str.contains("VINE|プロモ部分値引|無償販売", case=True, na=False, regex=True)
            if ch == "🔵 合計" and len(memo_sub.columns) > 1:
                vine_mask &= memo_sub[memo_sub.columns[1]].astype(str).str.contains("Amazon FBA", na=False)
            vine_rows = memo_sub[vine_mask]
            vine_count = len(vine_rows)
            # VINE本物のみ10円課金
            real_vine = memo_str[vine_mask].str.contains("VINE", case=True, na=False).sum() if vine_count > 0 else 0
            vine_cost = float(vine_rows[COST_C].sum() + vine_rows[SHIP_C].sum()) + (10 * int(real_vine))

        # 発送後キャンセル経費: 送料分のみ損失計上
        post_cancel_cost = 0
        post_cancel_count = 0
        if memo_col is not None:
            pc_mask = memo_sub[memo_col].astype(str).str.contains("発送後", case=False, na=False)
            pc_rows = memo_sub[pc_mask]
            post_cancel_count = len(pc_rows)
            post_cancel_cost = float(pc_rows[SHIP_C].sum())

        # 廃棄経費: 返品(自動)分のみ = 売価 + 原価 + 送料
        # 厳密マッチ: 「返品(自動)」のみ。「要確認」は VINE側で扱う
        disposal_cost = 0
        disposal_count = 0
        if memo_col is not None:
            ret_mask = memo_sub[memo_col].astype(str).str.contains("返品\\(自動\\)", case=False, na=False, regex=True)
            ret_rows = memo_sub[ret_mask]
            disposal_count = len(ret_rows)
            # 売価 = 単価×数量
            ret_amount = float((ret_rows[QTY_C] * pd.to_numeric(ret_rows[ret_rows.columns[7]] if len(ret_rows.columns) > 7 else 0, errors="coerce").fillna(0)).sum()) if len(ret_rows) > 0 else 0
            disposal_cost = ret_amount + float(ret_rows[COST_C].sum() + ret_rows[SHIP_C].sum())

        # FBA保管料 (合計のみ。チャネル別配分は不可、Amazon系全体に乗せる)
        storage_fee = 0
        if ch == "🔵 合計":
            storage_fee = storage_lookup.get(month_str, 0)
        elif ch == "Amazon FBA":
            # 保管料は基本FBA分なので暫定的にFBAに全部寄せる
            storage_fee = storage_lookup.get(month_str, 0)

        # 保管料状態判定: その月の保管料データが入ってれば「確定」、無ければ「暫定」
        storage_status = "確定" if storage_lookup.get(month_str, 0) > 0 else "暫定"

        # 暫定粗利 = 利益額 - 広告 - アフィリ - ポイント - クーポン - 廃棄 - VINE経費 - 発送後キャンセル経費
        provisional_profit = profit - ad - aff - point - coupon - disposal_cost - vine_cost - post_cancel_cost
        # 確定粗利 = 暫定粗利 - FBA保管料 (保管料未取得月は None)
        final_profit = provisional_profit - storage_fee if storage_status == "確定" else None

        rows.append({
            "月": month_str,
            "チャネル": ch,
            "売上": revenue,
            "手数料": fee,
            "送料": ship,
            "原価": cost,
            "利益額": profit,
            "利益率": rate * 100,
            "平均単価": avg_price,
            "広告費": ad,
            "アフィリ": aff,
            "ポイント": point,
            "クーポン": coupon,
            "廃棄経費": disposal_cost,
            "廃棄件数": disposal_count,
            "VINE経費": vine_cost,
            "VINE件数": vine_count,
            "発送後Cキャンセル経費": post_cancel_cost,
            "発送後キャンセル件数": post_cancel_count,
            "暫定粗利": provisional_profit,
            "FBA保管料": storage_fee,
            "確定粗利": final_profit,
            "保管料状態": storage_status,
        })

summary_df = pd.DataFrame(rows)

# ===========================================================
# 表示
# ===========================================================
st.markdown("### 📊 月×チャネル別 集計")

# 合計行を強調表示
def _highlight_total_row(row):
    if str(row.get("チャネル", "")) == "🔵 合計":
        return ["background-color: #FBF1E7; font-weight: bold; color: #2A2520"] * len(row)
    return [""] * len(row)

styled_df = summary_df.style.apply(_highlight_total_row, axis=1)

st.dataframe(
    styled_df,
    use_container_width=True,
    height=600,
    hide_index=True,
    column_config={
        "売上":     st.column_config.NumberColumn(format="¥%d"),
        "手数料":   st.column_config.NumberColumn(format="¥%d"),
        "送料":     st.column_config.NumberColumn(format="¥%d"),
        "原価":     st.column_config.NumberColumn(format="¥%d"),
        "利益額":   st.column_config.NumberColumn(format="¥%d"),
        "利益率":   st.column_config.NumberColumn(format="%.1f%%"),
        "平均単価": st.column_config.NumberColumn(format="¥%d"),
        "広告費":   st.column_config.NumberColumn(format="¥%d"),
        "アフィリ": st.column_config.NumberColumn(format="¥%d"),
        "ポイント": st.column_config.NumberColumn(format="¥%d"),
        "クーポン": st.column_config.NumberColumn(format="¥%d"),
        "廃棄経費": st.column_config.NumberColumn(format="¥%d"),
        "廃棄件数": st.column_config.NumberColumn(format="%d"),
        "VINE経費": st.column_config.NumberColumn(format="¥%d"),
        "VINE件数": st.column_config.NumberColumn(format="%d"),
        "発送後Cキャンセル経費": st.column_config.NumberColumn(format="¥%d"),
        "発送後キャンセル件数": st.column_config.NumberColumn(format="%d"),
        "暫定粗利": st.column_config.NumberColumn(format="¥%d"),
        "FBA保管料": st.column_config.NumberColumn(format="¥%d"),
        "確定粗利": st.column_config.NumberColumn(format="¥%d"),
    },
)

# ===========================================================
# グラフ: 月別売上推移（チャネル別）
# ===========================================================
st.markdown("### 📈 月別売上推移（チャネル別）")
chart_data = summary_df[summary_df["チャネル"] != "🔵 合計"].pivot(
    index="月", columns="チャネル", values="売上"
).fillna(0)
chart_data = chart_data.sort_index()
st.bar_chart(chart_data)

st.markdown("### 📈 月別 粗利推移（暫定 vs 確定）")
profit_chart_df = summary_df[summary_df["チャネル"] == "🔵 合計"].set_index("月")[["暫定粗利", "確定粗利"]].sort_index()
st.line_chart(profit_chart_df)

st.caption("📌 保管料が未取得の月は「暫定粗利＝確定粗利」になります。`08_自動実行/fba_storage_fee_fetch.py --month 2026-04` で月次取得してください。")

# ===========================================================
# CSVダウンロード
# ===========================================================
csv = summary_df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "💾 CSV出力",
    csv,
    file_name=f"summary_{n_months}months.csv",
    mime="text/csv",
)
