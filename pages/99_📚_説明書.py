"""
📚 説明書

`07_Streamlitアプリ/MANUAL.md` を表示するページ。
内容は MANUAL.md を直接編集すれば即反映される。
"""
from pathlib import Path

import streamlit as st

from lib import ui

st.set_page_config(page_title="説明書", page_icon="📚", layout="wide")
st.title("📚 アプリ説明書")
ui.sidebar_common()

MANUAL_PATH = Path(__file__).resolve().parent.parent / "MANUAL.md"

if not MANUAL_PATH.exists():
    st.error(f"MANUAL.md が見つかりません: {MANUAL_PATH}")
    st.stop()

# 目次（H1/H2 だけサイドバーに表示）
text = MANUAL_PATH.read_text(encoding="utf-8")
headings: list[tuple[int, str]] = []
for line in text.splitlines():
    if line.startswith("## "):
        headings.append((2, line[3:].strip()))
    elif line.startswith("# "):
        headings.append((1, line[2:].strip()))

with st.sidebar:
    st.markdown("---")
    st.markdown("### 🔍 目次")
    for level, h in headings[:50]:
        indent = "&nbsp;&nbsp;&nbsp;&nbsp;" if level == 2 else ""
        # 見出しのアンカーへリンク
        anchor = h.lower().replace(" ", "-").replace("/", "-")
        st.markdown(f"{indent}[{h}](#{anchor})", unsafe_allow_html=True)

# 本文
st.markdown(text)

st.markdown("---")
with st.expander("📝 編集について"):
    st.markdown(
        f"""
- 表示元: `{MANUAL_PATH}`
- 更新ルール: 機能改修ごとには更新せず、改修が溜まったタイミングでまとめて書き換える
- 更新時は冒頭の「最終更新: YYYY-MM-DD」と末尾の「更新履歴」も同時に追記
"""
    )
