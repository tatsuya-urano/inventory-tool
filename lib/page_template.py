"""
シート閲覧ページの共通テンプレート

各 pages/*.py は以下のように呼び出すだけ:

    from lib.page_template import render_sheet_page
    render_sheet_page("06_入荷時", "入荷時", "📥")
"""
import pandas as pd
import streamlit as st

from . import sheets, ui


def render_sheet_page(
    sheet_name: str,
    page_title: str,
    page_icon: str,
    header_row: int = 1,
    data_start_row: int = 2,
    auto_detect: bool = True,
):
    """汎用シート表示ページ

    Args:
        sheet_name: スプシ内のシート名
        page_title: ページタイトル
        page_icon:  絵文字アイコン
        header_row: ヘッダ行（auto_detect=Falseの時のみ）
        data_start_row: データ開始行（auto_detect=Falseの時のみ）
        auto_detect: True ならヘッダ行を自動検出
    """
    st.set_page_config(page_title=page_title, page_icon=page_icon, layout="wide")
    st.title(f"{page_icon} {sheet_name}")
    ui.sidebar_common()

    with st.spinner(f"「{sheet_name}」読み込み中..."):
        df = sheets.load_any_sheet(
            sheet_name,
            header_row=header_row,
            data_start_row=data_start_row,
            auto_detect=auto_detect,
        )

    if df.empty:
        # auto_detect で取れなかった場合、デフォルトで再試行
        if auto_detect:
            with st.spinner("再試行（ヘッダ=1行目）..."):
                df = sheets.load_any_sheet(
                    sheet_name, header_row=1, data_start_row=2, auto_detect=False
                )

    if df.empty:
        st.warning(
            f"「{sheet_name}」からデータを取得できませんでした。\n"
            "「全シートビューア」で詳細パラメータを調整してください"
        )
        st.stop()

    # サマリ
    c1, c2, c3 = st.columns(3)
    c1.metric("行数", f"{len(df):,}")
    c2.metric("列数", f"{len(df.columns):,}")
    c3.metric("非空セル", f"{int((df != '').sum().sum()):,}")

    st.markdown("---")

    # 検索
    keyword = st.text_input(
        "🔍 全列横断検索（部分一致）",
        "",
        key=f"search_{sheet_name}",
    )

    filtered = df.copy()
    if keyword:
        mask = pd.Series(False, index=filtered.index)
        for c in filtered.columns:
            mask |= filtered[c].astype(str).str.contains(keyword, case=False, na=False)
        filtered = filtered[mask]

    st.caption(f"表示中: {len(filtered):,} / {len(df):,} 件")

    # テーブル
    st.dataframe(
        filtered,
        use_container_width=True,
        height=600,
        hide_index=True,
    )

    # CSV
    csv = filtered.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "💾 CSVダウンロード",
        csv,
        file_name=f"{sheet_name}_{len(filtered)}rows.csv",
        mime="text/csv",
        key=f"dl_{sheet_name}",
    )
