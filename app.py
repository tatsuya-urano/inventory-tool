"""
在庫管理ツール Streamlit版 — Home ページ

サイドバーの pages/ から各機能ページに遷移
"""
import streamlit as st

from lib import sheets, ui

st.set_page_config(
    page_title="在庫管理ツール",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📦 在庫管理ツール")
st.caption("Streamlit + Google Sheets / GAS版とデータ同期")

ui.sidebar_common()

# 全シートプリロードは「⚡ ツール」の手動ボタンから実行する運用に変更
# (起動時の自動プリロードは API レート制限を圧迫するためスキップ)

# ===========================================================
# 全体サマリ
# ===========================================================
st.markdown("## 📊 ダッシュボード")

with st.spinner("データ読み込み中..."):
    inv = sheets.load_inventory()

if inv.empty:
    st.warning("在庫データを取得できません")
    st.stop()

# ステータス列を探す（14列目想定）
status_col = None
candidates = ["ステータス"]
if len(inv.columns) > 13:
    candidates.append(inv.columns[13])
for c in candidates:
    if c in inv.columns:
        status_col = c
        break

# メトリクス
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("📦 総SKU数", f"{len(inv):,}")

if status_col:
    counts = inv[status_col].value_counts()
    col2.metric("🔴 危険", int(counts.get("🔴危険", 0)))
    col3.metric("🟠 要発注", int(counts.get("🟠要発注", 0)))
    col4.metric("🟣 過剰", int(counts.get("🟣過剰", 0)))
    col5.metric("⚫ 在庫切れ", int(counts.get("⚫在庫切れ", 0)))

st.markdown("---")

# ===========================================================
# クイックリンク
# ===========================================================
st.markdown("## 🧭 ページ")
st.markdown(
    """
左サイドバーから移動してください:

- **📋 在庫管理** — 04_在庫管理 の閲覧・絞り込み
- **💰 売上管理** — 05_売上管理 の閲覧・期間絞り込み

今後追加予定:

- 📈 月次サマリ
- 🛒 推奨発注リスト
- 🔧 SKU統合
"""
)

# ===========================================================
# 危険SKUのプレビュー
# ===========================================================
if status_col:
    danger = inv[inv[status_col].isin(["🔴危険", "⚫在庫切れ"])]
    if not danger.empty:
        st.markdown("## ⚠️ 要注意SKU（危険・在庫切れ）")
        st.caption(f"{len(danger)}件")
        # 主要列だけ表示
        show_cols = [c for c in [
            inv.columns[0],     # A 商品コード
            inv.columns[1] if len(inv.columns) > 1 else None,  # B タイトル
            status_col,
            "在庫日数" if "在庫日数" in inv.columns else None,
            "推奨発注数" if "推奨発注数" in inv.columns else None,
        ] if c]
        st.dataframe(
            danger[show_cols],
            use_container_width=True,
            hide_index=True,
            height=300,
        )
