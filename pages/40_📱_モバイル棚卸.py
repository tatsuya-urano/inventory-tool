"""📱 モバイル棚卸 — スマホ最適化

SKU検索 → 自社倉庫(F列) or 月初(G列) を直接書き込み
1SKUずつ大きなボタンで操作
"""
import streamlit as st
import pandas as pd

from lib import sheets, ui

st.set_page_config(page_title="モバイル棚卸", page_icon="📱", layout="centered")
ui.sidebar_common()

# モバイル用大きめCSS
st.markdown("""
<style>
    .stButton>button {
        height: 56px !important;
        font-size: 20px !important;
        font-weight: 700 !important;
    }
    .stTextInput input, .stNumberInput input {
        font-size: 20px !important;
        height: 50px !important;
    }
    .big-stock {
        font-size: 48px;
        font-weight: 800;
        text-align: center;
        color: #C76E47;
        margin: 12px 0;
    }
    .sku-card {
        background: #FFF7F0;
        border: 2px solid #E8A574;
        border-radius: 12px;
        padding: 16px;
        margin: 12px 0;
    }
</style>
""", unsafe_allow_html=True)

st.title("📱 モバイル棚卸")
st.caption("スマホで在庫を直接入力")

with st.spinner("読込中..."):
    inv_df = sheets.load_inventory()
    master_df = sheets.load_master()

if inv_df.empty:
    st.error("在庫データ読込失敗")
    st.stop()

# ===========================================================
# SKU検索
# ===========================================================
search = st.text_input("🔍 SKU or タイトル検索", key="mob_search", placeholder="例: osatukinkoblack")

if not search.strip():
    st.info("SKU or タイトルの一部を入力してください")
    st.stop()

# 部分一致検索
code_col = inv_df.columns[0]
title_col = inv_df.columns[1] if len(inv_df.columns) > 1 else None

mask = inv_df[code_col].astype(str).str.contains(search, case=False, na=False)
if title_col:
    mask |= inv_df[title_col].astype(str).str.contains(search, case=False, na=False)
hits = inv_df[mask].head(10)

if hits.empty:
    st.warning(f"「{search}」にマッチするSKUなし")
    st.stop()

st.caption(f"{len(hits)}件ヒット(最大10件)")

# ===========================================================
# SKU選択
# ===========================================================
options = []
for _, r in hits.iterrows():
    code = str(r[code_col]).strip()
    title = str(r[title_col]).strip() if title_col else ""
    options.append(f"{code} | {title[:30]}")

selected = st.radio("SKU選択", options, key="mob_selected_sku")
selected_code = selected.split(" | ")[0]

# 詳細表示
inv_row = inv_df[inv_df[code_col].astype(str).str.strip() == selected_code]
if inv_row.empty:
    st.error("SKU不明")
    st.stop()
r = inv_row.iloc[0]

# 現在値
def _f(v):
    try:
        return int(float(str(v).replace(",", "").replace("¥", "").strip() or 0))
    except (ValueError, TypeError):
        return 0

cur_fba = _f(r.iloc[3]) if len(r) > 3 else 0
cur_jisha = _f(r.iloc[5]) if len(r) > 5 else 0  # F自社倉庫(計算値)
cur_month_init = _f(r.iloc[6]) if len(r) > 6 else 0  # G月初
cur_avail = _f(r.iloc[7]) if len(r) > 7 else 0  # H販売可能
cur_pending = _f(r.iloc[11]) if len(r) > 11 else 0  # L発注済

st.markdown(f"""
<div class="sku-card">
<div style="font-weight:700; font-size:18px;">{selected_code}</div>
<div style="color:#666; font-size:14px; margin:4px 0;">{str(r[title_col])[:40] if title_col else ''}</div>
</div>
""", unsafe_allow_html=True)

# 在庫サマリ
c1, c2, c3 = st.columns(3)
c1.metric("FBA", cur_fba)
c2.metric("自社", cur_jisha)
c3.metric("販売可能", cur_avail)

st.markdown("---")

# ===========================================================
# 月初在庫(G列) 編集
# ===========================================================
st.markdown("### 📦 月初在庫 (G列) を更新")
st.caption("棚卸の実数を入れる。F自社倉庫はGから自動計算")
st.markdown(f'<div class="big-stock">現在: {cur_month_init}</div>', unsafe_allow_html=True)

new_month = st.number_input(
    "新しい月初在庫",
    min_value=0, max_value=99999,
    value=cur_month_init,
    step=1,
    key="new_month_init",
)

# ボタン群
b1, b2, b3 = st.columns(3)
if b1.button("−1", use_container_width=True, key="mi_minus"):
    new_month = max(0, new_month - 1)
    st.session_state["new_month_init"] = new_month
    st.rerun()
if b2.button("+1", use_container_width=True, key="mi_plus"):
    new_month += 1
    st.session_state["new_month_init"] = new_month
    st.rerun()
if b3.button("+10", use_container_width=True, key="mi_plus10"):
    new_month += 10
    st.session_state["new_month_init"] = new_month
    st.rerun()

# 保存ボタン
if st.button(f"💾 {selected_code} の月初を {new_month} に保存", type="primary", use_container_width=True):
    if new_month == cur_month_init:
        st.warning("値が変わってません")
    else:
        try:
            ss = sheets.get_spreadsheet()
            ws = ss.worksheet("04_在庫管理")
            # 行番号特定 (1-indexed, ヘッダ行6, データ7〜)
            codes = ws.col_values(1)
            target_row = None
            for i, c in enumerate(codes, start=1):
                if i >= 7 and c.strip() == selected_code:
                    target_row = i
                    break
            if not target_row:
                st.error("行が見つからない")
            else:
                ws.update(
                    range_name=f"G{target_row}",
                    values=[[new_month]],
                    value_input_option="USER_ENTERED",
                )
                sheets._invalidate_one("04_在庫管理")
                st.success(f"✅ {selected_code} 月初={new_month} に更新")
                st.balloons()
        except Exception as e:
            st.error(f"更新失敗: {e}")

st.markdown("---")
st.caption("📌 F自社倉庫はARRAYFORMULA計算: G月初 + I入荷 - J出荷 - 当月販売")
