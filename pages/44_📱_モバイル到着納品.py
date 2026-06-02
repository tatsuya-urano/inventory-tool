"""📱 モバイル発注到着納品 — スマホ最適化(見るだけ)

04_在庫管理 のRakumart状況4列を読むだけ。書き込みなし。
  M 仕入中(Rakumart)   = 発注済み・未着
  N ラクマート到着済み  = 到着(発送可)
  O FBA発送済み        = FBA納品
  P 自社発送済み        = 自社納品
"""
import unicodedata

import streamlit as st
import pandas as pd

from lib import sheets, ui

st.set_page_config(page_title="モバイル到着納品", page_icon="📱", layout="centered")
ui.sidebar_common()

st.markdown("""
<style>
    .stTextInput input {
        font-size: 20px !important;
        height: 50px !important;
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

st.title("📱 発注→到着→納品")
st.caption("Rakumartの今の状況を見るだけ(入力なし)")

with st.spinner("読込中..."):
    try:
        inv_df = sheets.load_inventory()
    except Exception as e:
        st.error("📡 在庫データの取得に失敗しました（サーバー混雑かも）。")
        st.caption(f"詳細: {type(e).__name__}")
        if st.button("🔄 もう一度読み込む"):
            sheets._invalidate_one("04_在庫管理")
            st.rerun()
        st.stop()

if inv_df.empty:
    st.error("在庫データ読込失敗")
    st.stop()

code_col = inv_df.columns[0]
title_col = inv_df.columns[1] if len(inv_df.columns) > 1 else None


def _f(v):
    try:
        return int(float(str(v).replace(",", "").replace("¥", "").strip() or 0))
    except (ValueError, TypeError):
        return 0


def _norm(s):
    """検索用の正規化。NFKCで全角英数字/カナを半角相当に統一し、小文字化。
    これで半角/全角を気にせず検索できる。"""
    return unicodedata.normalize("NFKC", str(s)).lower().strip()


# 04列(2026-06-02移設): M仕入中=12 / Nラクマート到着=13 / O FBA発送=14 / P自社発送=15
def _row_status(r):
    return (
        _f(r.iloc[12]) if len(r) > 12 else 0,   # M 仕入中(未着)
        _f(r.iloc[13]) if len(r) > 13 else 0,   # N ラクマート到着
        _f(r.iloc[14]) if len(r) > 14 else 0,   # O FBA発送
        _f(r.iloc[15]) if len(r) > 15 else 0,   # P 自社発送
    )


tab1, tab2 = st.tabs(["🔍 個別検索", "📋 発注中一覧"])

with tab1:
    search = st.text_input("🔍 SKU or タイトル検索", key="mob_ad_search",
                           placeholder="SKUの一部（半角/全角どちらでもOK）")
    q = _norm(search)
    if not q:
        st.info("SKU or タイトルの一部を入力")
    else:
        mask = inv_df[code_col].astype(str).map(_norm).str.contains(q, na=False, regex=False)
        if title_col:
            mask |= inv_df[title_col].astype(str).map(_norm).str.contains(q, na=False, regex=False)
        hits = inv_df[mask].head(10)
        if hits.empty:
            st.warning("マッチなし")
        else:
            for _, r in hits.iterrows():
                code = str(r[code_col]).strip()
                title = str(r[title_col]).strip()[:40] if title_col else ""
                m, n, o, p = _row_status(r)
                st.markdown(f"""
                <div class="sku-card">
                <div style="font-weight:700; font-size:18px;">{code}</div>
                <div style="color:#666; font-size:13px;">{title}</div>
                </div>
                """, unsafe_allow_html=True)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("⏳仕入中", m)
                c2.metric("✅到着", n)
                c3.metric("📦FBA発送", o)
                c4.metric("🏠自社発送", p)

with tab2:
    st.caption("M仕入中・N到着・O FBA発送・P自社発送 のいずれかが>0のSKU")
    kw = st.text_input("🔍 SKU or タイトルで絞り込み", key="mob_ad_list_kw",
                       placeholder="SKUの一部（半角/全角どちらでもOK・空欄で全件）")
    qk = _norm(kw)
    rows = []
    for _, r in inv_df.iterrows():
        m, n, o, p = _row_status(r)
        if (m + n + o + p) <= 0:
            continue
        code = str(r[code_col]).strip()
        title = str(r[title_col]).strip()[:30] if title_col else ""
        if qk and qk not in _norm(code) and qk not in _norm(title):
            continue
        rows.append({
            "SKU": code,
            "タイトル": title,
            "⏳仕入中": m,
            "✅到着": n,
            "📦FBA発送": o,
            "🏠自社発送": p,
        })
    if not rows:
        if qk:
            st.warning("該当SKUなし（絞り込み条件にマッチしません）")
        else:
            st.success("✨ Rakumart発注中の在庫なし")
    else:
        out = pd.DataFrame(rows).sort_values(
            ["✅到着", "⏳仕入中"], ascending=False)
        st.caption(f"{len(out)}件　※数量はマスタ単位(発注時係数で割った値)")
        st.dataframe(out, use_container_width=True, hide_index=True, height=500)

st.markdown("---")
st.caption("💡 入力や発送指示はPC版「📋 発注→到着→納品」で")
