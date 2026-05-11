"""
🏪 楽天売上突合ページ

今月（または任意期間）の楽天売上を金額降順で並べて、
楽天RMSのレポートと突き合わせるための一覧を表示する。

集計モード:
- 注文単位: 注文番号でグループ化、注文ごとの合計売上で降順
- 商品単位: 商品コード/SKU 単位で売上合計
- 明細行: 1取引1行のまま降順
"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="楽天売上突合", page_icon="🏪", layout="wide")
st.title("🏪 楽天売上突合（レポート比較用）")
st.caption("楽天の今月売上を金額降順で表示")
ui.sidebar_common()


def _to_num(v):
    try:
        return float(str(v).replace(",", "").replace("¥", "").replace("％", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return 0.0


# ===========================================================
# データ読込
# ===========================================================
with st.spinner("売上読込中..."):
    df = sheets.load_sales()

if df.empty:
    st.warning("売上データなし")
    st.stop()

# 列名を絶対インデックスで取得（ヘッダ揺れ対策）
COL_DATE   = df.columns[0]   # A 日付
COL_MALL   = df.columns[1]   # B モール
COL_ORDER  = df.columns[2]   # C 注文番号
COL_CODE   = df.columns[3]   # D 商品コード
COL_NAME   = df.columns[4]   # E 商品名
COL_SKU    = df.columns[5]   # F SKU
COL_QTY    = df.columns[6]   # G 数量
COL_PRICE  = df.columns[7]   # H 単価
COL_SALES  = df.columns[8]   # I 売上
COL_FEE    = df.columns[10] if len(df.columns) > 10 else None   # K 手数料
COL_POINT  = df.columns[12] if len(df.columns) > 12 else None   # M 楽天ポイント費用
COL_COUPON = df.columns[13] if len(df.columns) > 13 else None   # N 楽天クーポン費用
COL_PROFIT = df.columns[14] if len(df.columns) > 14 else None   # O 利益額
COL_NOTE   = df.columns[16] if len(df.columns) > 16 else None   # Q 備考

# 日付パース
df = df.copy()
df["_dt"] = pd.to_datetime(df[COL_DATE], errors="coerce")
df = df[df["_dt"].notna()]  # サマリ行や空行を除外（日付として読めない行を捨てる）

# ===========================================================
# 期間 / モール フィルタ
# ===========================================================
today = date.today()
month_start = today.replace(day=1)

c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    period = st.selectbox(
        "期間",
        ["今月", "先月", "今日", "昨日", "カスタム"],
        index=0,
    )
with c2:
    mall = st.selectbox(
        "モール",
        ["楽天", "Amazon FBA", "Amazon FBM", "（全て）"],
        index=0,
    )
with c3:
    if period == "カスタム":
        d_from = st.date_input("From", value=month_start, key="d_from")
        d_to   = st.date_input("To",   value=today,        key="d_to")
    else:
        if period == "今月":
            d_from, d_to = month_start, today
        elif period == "先月":
            prev_last = month_start - timedelta(days=1)
            d_from = prev_last.replace(day=1)
            d_to   = prev_last
        elif period == "今日":
            d_from = d_to = today
        elif period == "昨日":
            yest = today - timedelta(days=1)
            d_from = d_to = yest
        st.caption(f"{d_from} ~ {d_to}")

# 抽出
mask = (df["_dt"].dt.date >= d_from) & (df["_dt"].dt.date <= d_to)
if mall != "（全て）":
    mask &= df[COL_MALL].astype(str).str.strip() == mall
view = df[mask].copy()

if view.empty:
    st.info("該当データなし")
    st.stop()

# 売上を数値化
view["_sales"] = view[COL_SALES].apply(_to_num)
view["_qty"]   = view[COL_QTY].apply(_to_num)
view["_fee"]    = view[COL_FEE].apply(_to_num)    if COL_FEE    else 0
view["_point"]  = view[COL_POINT].apply(_to_num)  if COL_POINT  else 0
view["_coupon"] = view[COL_COUPON].apply(_to_num) if COL_COUPON else 0
view["_profit"] = view[COL_PROFIT].apply(_to_num) if COL_PROFIT else 0

# ===========================================================
# サマリ
# ===========================================================
total_sales  = int(view["_sales"].sum())
total_qty    = int(view["_qty"].sum())
total_orders = view[COL_ORDER].astype(str).str.strip().nunique()
total_fee    = int(view["_fee"].sum())
total_point  = int(view["_point"].sum())
total_coupon = int(view["_coupon"].sum())
total_profit = int(view["_profit"].sum())

st.markdown(f"### 📊 {mall} {d_from} ~ {d_to}")
m1, m2, m3, m4 = st.columns(4)
m1.metric("💰 売上合計", f"¥{total_sales:,}")
m2.metric("📦 数量合計", f"{total_qty:,}")
m3.metric("🧾 注文件数", f"{total_orders:,}")
m4.metric("💎 利益合計", f"¥{total_profit:,}")
if mall == "楽天":
    m5, m6, m7, _ = st.columns(4)
    m5.metric("💸 手数料", f"¥{total_fee:,}")
    m6.metric("🎁 ポイント費用", f"¥{total_point:,}")
    m7.metric("🎟 クーポン費用", f"¥{total_coupon:,}")

st.markdown("---")

# ===========================================================
# 集計モード
# ===========================================================
mode = st.radio(
    "集計モード",
    ["🧾 注文単位（同一注文をまとめる）", "📦 商品単位（SKU合計）", "📋 明細行（1取引1行）"],
    horizontal=True,
)

# キーワード絞込
keyword = st.text_input("商品コード/タイトル/注文番号 で絞込", "", placeholder="例: gipssandal / 414562-2026...")

if keyword.strip():
    kw = keyword.strip()
    text_mask = (
        view[COL_CODE].astype(str).str.contains(kw, case=False, na=False)
        | view[COL_NAME].astype(str).str.contains(kw, case=False, na=False)
        | view[COL_ORDER].astype(str).str.contains(kw, case=False, na=False)
    )
    view = view[text_mask]

# ===========================================================
# モード別表示
# ===========================================================
if mode.startswith("🧾"):
    # 注文単位
    grouped = view.groupby(view[COL_ORDER].astype(str).str.strip(), dropna=False).agg(
        日時=("_dt", "min"),
        商品数=("_qty", "sum"),
        SKU数=(COL_CODE, "nunique"),
        商品名=(COL_NAME, lambda s: " / ".join(s.astype(str).head(3))),
        売上=("_sales", "sum"),
        手数料=("_fee", "sum"),
        ポイント=("_point", "sum"),
        クーポン=("_coupon", "sum"),
        利益=("_profit", "sum"),
    ).reset_index().rename(columns={COL_ORDER: "注文番号"})
    grouped["日時"] = grouped["日時"].dt.strftime("%Y-%m-%d %H:%M")
    grouped = grouped.sort_values("売上", ascending=False).reset_index(drop=True)
    grouped.insert(0, "順位", grouped.index + 1)

    st.caption(f"注文 {len(grouped):,} 件 / 売上順")
    st.dataframe(
        grouped,
        use_container_width=True,
        hide_index=True,
        height=600,
        column_config={
            "順位":  st.column_config.NumberColumn(width="small"),
            "売上":  st.column_config.NumberColumn(format="¥%d"),
            "手数料": st.column_config.NumberColumn(format="¥%d"),
            "ポイント": st.column_config.NumberColumn(format="¥%d"),
            "クーポン": st.column_config.NumberColumn(format="¥%d"),
            "利益":  st.column_config.NumberColumn(format="¥%d"),
            "商品数": st.column_config.NumberColumn(width="small"),
            "SKU数": st.column_config.NumberColumn(width="small"),
        },
    )
    csv_df = grouped

elif mode.startswith("📦"):
    # 商品単位
    grouped = view.groupby(view[COL_CODE].astype(str).str.strip(), dropna=False).agg(
        商品名=(COL_NAME, lambda s: str(s.astype(str).iloc[0]) if len(s) else ""),
        販売数=("_qty", "sum"),
        注文数=(COL_ORDER, "nunique"),
        売上=("_sales", "sum"),
        利益=("_profit", "sum"),
    ).reset_index().rename(columns={COL_CODE: "商品コード"})
    grouped = grouped.sort_values("売上", ascending=False).reset_index(drop=True)
    grouped.insert(0, "順位", grouped.index + 1)

    st.caption(f"商品 {len(grouped):,} 種 / 売上順")
    st.dataframe(
        grouped,
        use_container_width=True,
        hide_index=True,
        height=600,
        column_config={
            "順位": st.column_config.NumberColumn(width="small"),
            "売上": st.column_config.NumberColumn(format="¥%d"),
            "利益": st.column_config.NumberColumn(format="¥%d"),
            "販売数": st.column_config.NumberColumn(width="small"),
            "注文数": st.column_config.NumberColumn(width="small"),
        },
    )
    csv_df = grouped

else:
    # 明細
    detail = view[[
        "_dt", COL_ORDER, COL_CODE, COL_NAME, COL_SKU,
        "_qty", COL_PRICE, "_sales", "_fee", "_point", "_coupon", "_profit",
    ]].copy()
    detail.columns = ["日時", "注文番号", "商品コード", "商品名", "SKU",
                      "数量", "単価", "売上", "手数料", "ポイント", "クーポン", "利益"]
    detail["日時"] = detail["日時"].dt.strftime("%Y-%m-%d %H:%M")
    detail = detail.sort_values("売上", ascending=False).reset_index(drop=True)
    detail.insert(0, "順位", detail.index + 1)

    st.caption(f"明細 {len(detail):,} 行 / 売上順")
    st.dataframe(
        detail,
        use_container_width=True,
        hide_index=True,
        height=600,
        column_config={
            "順位": st.column_config.NumberColumn(width="small"),
            "売上": st.column_config.NumberColumn(format="¥%d"),
            "単価": st.column_config.NumberColumn(format="¥%d"),
            "手数料": st.column_config.NumberColumn(format="¥%d"),
            "ポイント": st.column_config.NumberColumn(format="¥%d"),
            "クーポン": st.column_config.NumberColumn(format="¥%d"),
            "利益": st.column_config.NumberColumn(format="¥%d"),
        },
    )
    csv_df = detail

# ===========================================================
# CSV ダウンロード
# ===========================================================
st.markdown("---")
st.download_button(
    "📥 CSVダウンロード（突合用）",
    csv_df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"{mall}_売上_{d_from}_{d_to}_{mode[:2]}.csv",
    mime="text/csv",
)

st.caption(
    "💡 楽天RMSの売上レポートと比較するときは『注文単位』モードがおすすめ。"
    "注文番号と売上金額をレポートと突き合わせると差異が見つけやすい。"
)
