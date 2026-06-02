"""
在庫管理ツール Streamlit版 — Home ページ

サイドバーの pages/ から各機能ページに遷移
"""
import os

import streamlit as st

from lib import sheets, ui

_PAGES_DIR = os.path.dirname(os.path.abspath(__file__))


def _plink(path: str, label: str, **kw) -> None:
    """対象ページが存在する時だけ st.page_link を描画(クラウドで未配置のページを安全にスキップ)。"""
    if os.path.exists(os.path.join(_PAGES_DIR, path)):
        st.page_link(path, label=label, **kw)

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

# ステータス列を探す（X列=index23, 2026-06-02 移設で T→X）
status_col = None
candidates = ["ステータス"]
if len(inv.columns) > 23:
    candidates.append(inv.columns[23])
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
st.markdown("## 📱 スマホ用ページ")
st.caption("スマホはこの3つだけでOK")
_plink("pages/40_📱_モバイル棚卸.py", "📱 棚卸（在庫を入力）", use_container_width=True)
_plink("pages/41_📱_モバイル発注チェック.py", "📱 推奨発注数・発注済み", use_container_width=True)
_plink("pages/44_📱_モバイル到着納品.py", "📱 発注→到着→納品（見るだけ）", use_container_width=True)

with st.expander("🖥 PC用ページ"):
    _plink("pages/01_📋_在庫管理.py", "📋 在庫管理")
    _plink("pages/02_💰_売上管理.py", "💰 売上管理")
    _plink("pages/05_🛒_推奨発注リスト.py", "🛒 推奨発注リスト")
    _plink("pages/43_📋_発注到着納品.py", "📋 発注→到着→納品")
    _plink("pages/07_📈_月次サマリ.py", "📈 月次サマリ")

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
