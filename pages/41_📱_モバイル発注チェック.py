"""📱 モバイル発注済みチェック — スマホ最適化

04のL列(発注済)に数値を入力 / 一覧で状況確認
"""
import streamlit as st
import pandas as pd

from lib import sheets, ui

st.set_page_config(page_title="モバイル発注チェック", page_icon="📱", layout="centered")
ui.sidebar_common()

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
        font-size: 40px;
        font-weight: 800;
        text-align: center;
        color: #2E7D32;
        margin: 12px 0;
    }
    .sku-card {
        background: #F0FFF4;
        border: 2px solid #66BB6A;
        border-radius: 12px;
        padding: 16px;
        margin: 12px 0;
    }
</style>
""", unsafe_allow_html=True)

st.title("📱 発注済みチェック")
st.caption("L列(発注済)をスマホで直接入力")

with st.spinner("読込中..."):
    inv_df = sheets.load_inventory()

if inv_df.empty:
    st.error("在庫データ読込失敗")
    st.stop()

# タブ切替
tab1, tab2 = st.tabs(["🔍 個別更新", "📋 要発注一覧"])

with tab1:
    search = st.text_input("🔍 SKU検索", key="mob_po_search", placeholder="SKUの一部")
    if search.strip():
        code_col = inv_df.columns[0]
        title_col = inv_df.columns[1] if len(inv_df.columns) > 1 else None
        mask = inv_df[code_col].astype(str).str.contains(search, case=False, na=False)
        if title_col:
            mask |= inv_df[title_col].astype(str).str.contains(search, case=False, na=False)
        hits = inv_df[mask].head(10)

        if hits.empty:
            st.warning("マッチなし")
        else:
            options = []
            for _, r in hits.iterrows():
                code = str(r[code_col]).strip()
                title = str(r[title_col]).strip()[:30] if title_col else ""
                options.append(f"{code} | {title}")
            selected = st.radio("選択", options, key="po_sel")
            selected_code = selected.split(" | ")[0]

            inv_row = inv_df[inv_df[code_col].astype(str).str.strip() == selected_code]
            r = inv_row.iloc[0]

            def _f(v):
                try:
                    return int(float(str(v).replace(",", "").replace("¥", "").strip() or 0))
                except (ValueError, TypeError):
                    return 0

            cur_avail = _f(r.iloc[7]) if len(r) > 7 else 0  # H販売可能
            cur_pending = _f(r.iloc[11]) if len(r) > 11 else 0  # L発注済
            cur_rec = _f(r.iloc[12]) if len(r) > 12 else 0  # M推奨発注
            status = str(r.iloc[19]) if len(r) > 19 else ""

            st.markdown(f"""
            <div class="sku-card">
            <div style="font-weight:700; font-size:18px;">{selected_code}</div>
            <div style="color:#666; font-size:14px;">{str(r[title_col])[:40] if title_col else ''}</div>
            <div style="margin-top:8px;">{status}</div>
            </div>
            """, unsafe_allow_html=True)

            c1, c2, c3 = st.columns(3)
            c1.metric("販売可能", cur_avail)
            c2.metric("推奨発注", cur_rec)
            c3.metric("現発注済", cur_pending)

            st.markdown("### 📦 発注済み数 (L列) 更新")
            st.markdown(f'<div class="big-stock">{cur_pending}</div>', unsafe_allow_html=True)

            new_po = st.number_input(
                "新しい発注済数",
                min_value=0, max_value=99999,
                value=cur_pending,
                step=1,
                key="new_po",
            )
            b1, b2, b3, b4 = st.columns(4)
            if b1.button("+10", use_container_width=True, key="po_plus10"):
                st.session_state["new_po"] = new_po + 10
                st.rerun()
            if b2.button("+50", use_container_width=True, key="po_plus50"):
                st.session_state["new_po"] = new_po + 50
                st.rerun()
            if b3.button(f"推奨{cur_rec}", use_container_width=True, key="po_set_rec",
                         disabled=cur_rec == 0):
                st.session_state["new_po"] = cur_rec
                st.rerun()
            if b4.button("0", use_container_width=True, key="po_zero"):
                st.session_state["new_po"] = 0
                st.rerun()

            if st.button(f"💾 発注済を {new_po} に保存", type="primary", use_container_width=True):
                if new_po == cur_pending:
                    st.warning("値が変わってません")
                else:
                    try:
                        ss = sheets.get_spreadsheet()
                        ws = ss.worksheet("04_在庫管理")
                        codes = ws.col_values(1)
                        target_row = None
                        for i, c in enumerate(codes, start=1):
                            if i >= 7 and c.strip() == selected_code:
                                target_row = i
                                break
                        if not target_row:
                            st.error("行不明")
                        else:
                            ws.update(
                                range_name=f"L{target_row}",
                                values=[[new_po]],
                                value_input_option="USER_ENTERED",
                            )
                            sheets._invalidate_one("04_在庫管理")
                            st.success(f"✅ {selected_code} 発注済={new_po}")
                            st.balloons()
                    except Exception as e:
                        st.error(f"更新失敗: {e}")

with tab2:
    st.caption("ステータス 🔴危険 / 🟠要発注 / ⚪在庫なし の一覧")

    code_col = inv_df.columns[0]
    title_col = inv_df.columns[1] if len(inv_df.columns) > 1 else None
    if len(inv_df.columns) <= 19:
        st.warning("ステータス列なし")
        st.stop()
    status_col = inv_df.columns[19]

    danger = inv_df[inv_df[status_col].isin(["🔴危険", "🟠要発注", "⚪在庫なし"])].copy()
    if danger.empty:
        st.success("✨ 危険SKU無し!")
    else:
        st.caption(f"{len(danger)}件")
        # コンパクト表示
        show_cols = [code_col]
        if title_col:
            show_cols.append(title_col)
        show_cols.append(status_col)
        # 発注済列も
        if len(inv_df.columns) > 11:
            show_cols.append(inv_df.columns[11])
        if len(inv_df.columns) > 12:
            show_cols.append(inv_df.columns[12])

        st.dataframe(
            danger[show_cols].rename(columns={
                code_col: "SKU",
                title_col: "タイトル" if title_col else "",
                status_col: "状態",
                inv_df.columns[11]: "発注済" if len(inv_df.columns) > 11 else "",
                inv_df.columns[12]: "推奨" if len(inv_df.columns) > 12 else "",
            }),
            use_container_width=True,
            hide_index=True,
            height=500,
        )

st.markdown("---")
st.caption("💡 棚卸タブで月初在庫を変更したい場合は「📱 モバイル棚卸」へ")
