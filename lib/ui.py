"""
共通UIヘルパ
"""
import urllib.parse

import streamlit as st

from . import sheets


# ============================================================
# 上部ナビゲーション (プライスター風)
# ============================================================
# モバイルはヘッダーが画面幅に収まらず横スクロールもできないため、
# 最も使うモバイルグループを先頭(一番左)に置いて常に見える/押せるようにする。
NAV_GROUPS = [
    ("📱 モバイル", "mobile", [
        ("📱 モバイル棚卸", "40_📱_モバイル棚卸"),
        ("📱 発注チェック", "41_📱_モバイル発注チェック"),
        ("📱 到着納品", "44_📱_モバイル到着納品"),
    ]),
    ("📊 メイン", "main", [
        ("📋 在庫管理", "01_📋_在庫管理"),
        ("💰 売上管理", "02_💰_売上管理"),
        ("📦 商品マスタ", "03_📦_商品マスタ"),
    ]),
    ("📈 分析", "analytics", [
        ("🛒 推奨発注リスト", "05_🛒_推奨発注リスト"),
        ("📋 発注→到着→納品", "43_📋_発注到着納品"),
        ("📈 月次サマリ", "07_📈_月次サマリ"),
        ("📊 大分類別販売集計", "08_📊_大分類別販売集計"),
    ]),
    ("📥 入出力", "io", [
        ("📦 入荷反映", "38_📦_入荷反映"),
        ("📦 FBA納品取込", "42_📦_FBA納品レポート取込"),
        ("📋 エクセル発注用", "10_📋_エクセル発注用"),
        ("🗒️ 棚卸在庫", "11_🗒️_棚卸在庫"),
        ("🎁 レビュープレゼント", "12_🎁_レビュープレゼント"),
        ("📢 広告費入力", "13_📢_広告費入力"),
    ]),
    ("🎯 SKU管理", "sku", [
        ("🚫 終売SKU", "15_🚫_終売SKU"),
        ("➕ 新規SKU登録", "16_➕_新規SKU登録"),
        ("🆕 新商品モード", "18_🆕_新商品モード"),
        ("🏷️ ASIN/FNSKU取得", "19_🏷️_ASIN_FNSKU取得"),
    ]),
    ("⚙️ 設定", "settings", [
        ("🔐 認証設定", "20_🔐_認証設定"),
        ("🔄 プール在庫設定", "21_🔄_プール在庫設定"),
        ("⚡ 一括実行", "22_⚡_一括実行"),
        ("⚙️ 設定", "30_⚙️_設定"),
    ]),
]


def _streamlit_url_slug(filename: str) -> str:
    """Streamlit multipageのURL slugを推測。
    pages/01_📋_在庫管理.py のような '数字_絵文字_名前' 形式から '名前' を取り出す。
    Streamlitは _ で区切って数字部分を除去、絵文字も飾りとして除外する。
    """
    parts = filename.split("_")
    # 先頭が数字なら除去
    if parts and parts[0].isdigit():
        parts = parts[1:]
    # 次が絵文字 (1〜2文字で、英数字でない) なら除去
    if parts and parts[0]:
        first = parts[0]
        # 英数字でなければ絵文字とみなす
        if not first.replace(" ", "").isalnum() and not any(
            "\u3040" <= c <= "\u9fff" for c in first  # ひらがな〜CJK統合漢字でなければ
        ):
            parts = parts[1:]
    return "_".join(parts) if parts else filename


def _streamlit_page_name(filename: str) -> str:
    """pages/01_📋_在庫管理.py → '在庫管理' の Streamlit内部ページ名を返す"""
    parts = filename.split("_")
    if parts and parts[0].isdigit():
        parts = parts[1:]
    if parts and parts[0]:
        first = parts[0]
        # 英数字でない先頭部分(絵文字)を除外
        if not first.replace(" ", "").isalnum() and not any(
            "\u3040" <= c <= "\u9fff" for c in first
        ):
            parts = parts[1:]
    return "_".join(parts) if parts else filename


def render_top_nav() -> None:
    """プライスター風の上部固定ナビゲーション。
    HTML+CSS でホバー展開、クエリパラメータで遷移指示 → app側で受け取って switch_page。
    """
    # クエリパラメータ ?nav=ページ名 を受け取って遷移
    qp = st.query_params
    nav_target = qp.get("nav")
    if nav_target:
        # 既に遷移処理済みの場合スキップ (二重switch防止)
        if st.session_state.get("_nav_processed") != nav_target:
            st.session_state["_nav_processed"] = nav_target
            # nav_target は ファイル名(拡張子なし)
            try:
                st.query_params.clear()
                st.switch_page(f"pages/{nav_target}.py")
            except Exception:
                pass

    items_html = ""
    for label, key, pages in NAV_GROUPS:
        sub_html = ""
        for page_label, page_path in pages:
            # クエリ ?nav=<filename> をリンクに付ける(同一ページ内JSで切替の代わり)
            href = f"/?nav={urllib.parse.quote(page_path)}"
            sub_html += (
                f'<a class="nav-sub-item" href="{href}" target="_self">{page_label}</a>'
            )
        items_html += (
            f'<div class="nav-group" tabindex="0">'
            f'  <div class="nav-group-label">{label} <span class="nav-arrow">▾</span></div>'
            f'  <div class="nav-dropdown">{sub_html}</div>'
            f'</div>'
        )
    home_href = f"/?nav={urllib.parse.quote('01_📋_在庫管理')}"

    st.markdown(
        f"""
        <style>
        /* Streamlitヘッダーを詰める */
        header[data-testid="stHeader"] {{
            background: transparent !important;
            height: 0 !important;
        }}
        /* メイン余白を上部ナビ分確保 */
        .block-container {{
            padding-top: 5.2rem !important;
        }}

        .topnav {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 999999;
            background: linear-gradient(135deg, #E8A574 0%, #C76E47 50%, #9C4A3A 100%);
            border-bottom: 0;
            box-shadow: 0 2px 10px rgba(140, 70, 50, 0.18);
            padding: 0 24px;
            display: flex;
            align-items: center;
            height: 60px;
            font-family: -apple-system, "Segoe UI", "Hiragino Kaku Gothic ProN", sans-serif;
        }}
        .topnav::after {{
            content: "";
            position: absolute;
            left: 0; right: 0; bottom: 0;
            height: 2px;
            background: linear-gradient(90deg, #F5D097 0%, #E8A574 50%, #C76E47 100%);
        }}
        .topnav-brand {{
            font-weight: 800;
            color: #FFFFFF;
            font-size: 18px;
            margin-right: 32px;
            display: flex;
            align-items: center;
            gap: 6px;
            text-decoration: none;
            white-space: nowrap;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
        }}
        .topnav-brand:hover {{
            color: #FFE7A8;
        }}
        .topnav-items {{
            display: flex;
            gap: 4px;
            flex: 1;
        }}
        .nav-group {{
            position: relative;
            outline: none;
        }}
        .nav-group-label {{
            padding: 9px 16px;
            cursor: pointer;
            font-weight: 700;
            color: #FFFFFF;
            border-radius: 8px;
            transition: background 0.15s ease, transform 0.15s ease;
            display: flex;
            align-items: center;
            gap: 4px;
            font-size: 14px;
            white-space: nowrap;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
        }}
        .nav-group:hover .nav-group-label,
        .nav-group:focus-within .nav-group-label {{
            background: rgba(255, 255, 255, 0.18);
            transform: translateY(-1px);
        }}
        .nav-arrow {{
            font-size: 10px;
            opacity: 0.85;
            transition: transform 0.15s ease;
        }}
        .nav-group:hover .nav-arrow,
        .nav-group:focus-within .nav-arrow {{
            transform: rotate(180deg);
        }}
        .nav-dropdown {{
            position: absolute;
            top: 100%;
            left: 0;
            background: linear-gradient(180deg, #FFFFFF 0%, #FFF7F0 100%);
            border: 1px solid rgba(191, 0, 0, 0.15);
            border-radius: 12px;
            box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
            min-width: 240px;
            padding: 8px;
            opacity: 0;
            visibility: hidden;
            transform: translateY(-4px);
            transition: opacity 0.15s ease, transform 0.15s ease, visibility 0.15s;
        }}
        .nav-group:hover .nav-dropdown,
        .nav-group:focus-within .nav-dropdown {{
            opacity: 1;
            visibility: visible;
            transform: translateY(0);
        }}
        .nav-sub-item {{
            display: block;
            padding: 10px 14px;
            color: #1A1A1A;
            text-decoration: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.15s ease;
            white-space: nowrap;
        }}
        .nav-sub-item:hover {{
            background: linear-gradient(90deg, #FFF7F0 0%, #FFE5D0 100%);
            color: #BF0000;
            transform: translateX(2px);
        }}
        .topnav-right {{
            color: rgba(255, 255, 255, 0.75);
            font-size: 12px;
            margin-left: auto;
            white-space: nowrap;
            font-weight: 500;
        }}
        </style>

        <nav class="topnav">
            <a class="topnav-brand" href="{home_href}" target="_self">📦 在庫管理ツール</a>
            <div class="topnav-items">{items_html}</div>
            <div class="topnav-right">v2026.05</div>
        </nav>
        """,
        unsafe_allow_html=True,
    )


def inject_global_css(font_size_px: int = 32) -> None:
    """全ページ共通の見た目調整CSSを注入。
    楽天ショップオーナーツール風: 明るくポップ、暖色アクセント、丸み、シャドウ。
    """
    st.markdown(
        f"""
        <style>
        /* ============================================================
           DataFrame / DataEditor: 文字サイズと罫線
        ============================================================ */
        [data-testid="stDataFrame"] div[role="gridcell"],
        [data-testid="stDataFrame"] [role="columnheader"],
        [data-testid="stDataEditor"] div[role="gridcell"],
        [data-testid="stDataEditor"] [role="columnheader"],
        [data-testid="stDataFrame"] *,
        [data-testid="stDataEditor"] *,
        .glide-data-editor,
        .glide-data-editor canvas {{
            font-size: {font_size_px}px !important;
            line-height: 1.5 !important;
        }}
        /* Streamlit Glide DataEditor (canvas) のフォント設定 */
        .stDataFrame, .stDataEditor {{
            --gdg-cell-font-style: {font_size_px}px sans-serif !important;
            --gdg-header-font-style: bold {font_size_px}px sans-serif !important;
        }}
        [data-testid="stDataFrame"], [data-testid="stDataEditor"] {{
            border: 1px solid #FFD7BF !important;
            border-radius: 12px !important;
            overflow: hidden !important;
            box-shadow: 0 2px 8px rgba(191, 0, 0, 0.05) !important;
        }}

        /* ============================================================
           st.metric: 優しいグラデーションカード
        ============================================================ */
        [data-testid="stMetric"] {{
            background: linear-gradient(135deg, #FDFAF6 0%, #FBF1E7 70%, #F5E4D2 100%);
            border: 1px solid #ECDDC9;
            border-radius: 12px;
            padding: 14px 18px;
            box-shadow:
                0 2px 6px rgba(120, 80, 60, 0.06),
                inset 0 1px 0 rgba(255, 255, 255, 0.5);
            transition: transform 0.18s ease, box-shadow 0.18s ease;
            position: relative;
            overflow: hidden;
        }}
        /* 左端の優しいアクセントバー */
        [data-testid="stMetric"]::before {{
            content: "";
            position: absolute;
            top: 8px; bottom: 8px; left: 0;
            width: 3px;
            background: linear-gradient(180deg, #E8B47A 0%, #C25F3A 100%);
            border-radius: 0 3px 3px 0;
        }}
        [data-testid="stMetric"]:hover {{
            transform: translateY(-2px);
            box-shadow:
                0 4px 12px rgba(120, 80, 60, 0.10),
                inset 0 1px 0 rgba(255, 255, 255, 0.5);
        }}
        [data-testid="stMetricValue"] {{
            font-size: {font_size_px + 10}px !important;
            font-weight: 700 !important;
            color: #8C2A1F !important;
            letter-spacing: -0.3px;
        }}
        [data-testid="stMetricLabel"] {{
            font-size: {font_size_px - 1}px !important;
            color: #5C4A3D !important;
            font-weight: 600 !important;
        }}

        /* ============================================================
           ボタン: 優しい配色 (テラコッタ系)
        ============================================================ */
        button[kind="primary"] {{
            background: linear-gradient(135deg, #C76E47 0%, #9C4A3A 100%) !important;
            border: none !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
            box-shadow: 0 2px 6px rgba(140, 70, 50, 0.20) !important;
            transition: transform 0.1s ease, box-shadow 0.1s ease !important;
        }}
        button[kind="primary"]:hover {{
            transform: translateY(-1px) !important;
            box-shadow: 0 4px 12px rgba(140, 70, 50, 0.28) !important;
        }}
        button[kind="secondary"] {{
            border-radius: 10px !important;
            border: 1.5px solid #ECDDC9 !important;
            background: #FFFFFF !important;
            color: #8C2A1F !important;
            font-weight: 600 !important;
        }}
        button[kind="secondary"]:hover {{
            background: #FBF1E7 !important;
            border-color: #C76E47 !important;
        }}

        /* 一般ボタンのラベル: 改行せず1行で */
        .stButton button p {{
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }}

        /* ============================================================
           Expander / Tab: 丸みと暖色アクセント
        ============================================================ */
        [data-testid="stExpander"] {{
            border: 1px solid #FFD7BF !important;
            border-radius: 12px !important;
            background: #FFFFFF;
            margin-bottom: 8px;
        }}
        [data-testid="stExpander"] summary {{
            font-weight: 600;
            color: #1A1A1A;
        }}

        button[role="tab"] {{
            font-weight: 600 !important;
            border-radius: 8px 8px 0 0 !important;
            padding: 10px 18px !important;
        }}
        button[role="tab"][aria-selected="true"] {{
            background: #FFF7F0 !important;
            color: #BF0000 !important;
            border-bottom: 3px solid #BF0000 !important;
        }}

        /* ============================================================
           タイトル / 見出し (優しい配色)
        ============================================================ */
        .stApp h1 {{
            color: #8C2A1F !important;
            font-weight: 700 !important;
            border-bottom: 3px solid #ECDDC9;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .stApp h2 {{
            color: #2A2520 !important;
            border-left: 5px solid #C76E47;
            padding-left: 12px;
            margin-top: 20px;
        }}
        .stApp h3 {{
            color: #3A3530 !important;
            border-left: 3px solid #E8A574;
            padding-left: 10px;
        }}

        /* ============================================================
           Alert (info/success/warning/error): カラフルに
        ============================================================ */
        [data-testid="stAlert"] {{
            border-radius: 12px !important;
            border-left-width: 6px !important;
        }}
        /* success */
        [data-testid="stAlert"][kind="success"] {{
            background: #F0FDF4 !important;
            border-left-color: #22C55E !important;
        }}
        /* info */
        [data-testid="stAlert"][kind="info"] {{
            background: #EFF6FF !important;
            border-left-color: #3B82F6 !important;
        }}
        /* warning */
        [data-testid="stAlert"][kind="warning"] {{
            background: #FFF7ED !important;
            border-left-color: #F97316 !important;
        }}
        /* error */
        [data-testid="stAlert"][kind="error"] {{
            background: #FEF2F2 !important;
            border-left-color: #BF0000 !important;
        }}

        /* ============================================================
           サイドバー: 暖色背景 + ナビ強調
        ============================================================ */
        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #FFF7F0 0%, #FFEFE0 100%) !important;
            border-right: 1px solid #FFD7BF;
        }}
        [data-testid="stSidebar"] a {{
            border-radius: 8px !important;
            margin: 2px 0;
            transition: background 0.1s ease;
        }}
        [data-testid="stSidebar"] a:hover {{
            background: rgba(191, 0, 0, 0.08) !important;
        }}

        /* ============================================================
           入力系: 角丸+影
        ============================================================ */
        .stTextInput input, .stNumberInput input, .stTextArea textarea {{
            border-radius: 8px !important;
            border: 1.5px solid #FFD7BF !important;
            transition: border-color 0.1s ease;
        }}
        .stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {{
            border-color: #BF0000 !important;
            box-shadow: 0 0 0 3px rgba(191, 0, 0, 0.1) !important;
        }}
        .stSelectbox > div > div {{
            border-radius: 8px !important;
        }}

        /* ============================================================
           File uploader: ドロップゾーンを華やかに
        ============================================================ */
        [data-testid="stFileUploader"] section {{
            border: 2px dashed #FFD7BF !important;
            border-radius: 12px !important;
            background: #FFF7F0 !important;
            transition: background 0.1s ease, border-color 0.1s ease;
        }}
        [data-testid="stFileUploader"] section:hover {{
            background: #FFEFE0 !important;
            border-color: #BF0000 !important;
        }}

        /* ============================================================
           Markdown 本文サイズ
        ============================================================ */
        .stMarkdown p, .stMarkdown li {{
            font-size: {font_size_px}px !important;
            line-height: 1.7 !important;
        }}
        .stCaption, [data-testid="stCaptionContainer"] {{
            color: #6B7280 !important;
        }}

        /* ============================================================
           プログレスバー: 楽天レッド
        ============================================================ */
        [role="progressbar"] > div > div {{
            background: linear-gradient(90deg, #BF0000, #FF6B6B) !important;
        }}

        /* ============================================================
           チェックボックス・ラジオ: 楽天レッド選択時
        ============================================================ */
        [data-testid="stCheckbox"] svg, [data-testid="stRadio"] svg {{
            color: #BF0000 !important;
        }}

        /* テーブル(旧 st.table) */
        .stTable td, .stTable th {{
            font-size: {font_size_px}px !important;
        }}

        /* ============================================================
           サイドバーを完全非表示 (上部ナビに集約済みのため)
        ============================================================ */
        [data-testid="stSidebar"] {{
            display: none !important;
        }}
        [data-testid="stSidebarCollapsedControl"] {{
            display: none !important;
        }}
        /* メインコンテンツを左端まで広げる */
        .main .block-container {{
            max-width: 100% !important;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar_common(this_sheet: str = None):
    """全ページ共通のサイドバー要素

    Args:
        this_sheet: 現在ページが扱うシート名（指定すると「このシートだけ再読込」ボタン有効化）
    """
    # ボタンキー用のページ識別子
    page_id = this_sheet or "default"

    # 文字サイズ設定（session_stateで全ページ共有）
    font_size = st.session_state.get("_font_size_px", 16)
    inject_global_css(font_size)

    # 上部固定ナビゲーション (全ページ共通)
    render_top_nav()

    # ----- 全ページ共通: 最新化ボタン(目立つ位置) -----
    # このページが使うシートだけクリア(this_sheet 指定時)
    # 未指定時は全シートクリア(従来動作)
    rc1, rc2 = st.columns([1, 6])
    with rc1:
        btn_help = (
            f"このページのデータ({this_sheet})だけ最新化"
            if this_sheet else
            "全シートのキャッシュをクリアして最新データを取得"
        )
        if st.button("🔄 データを最新化", key=f"top_refresh_{page_id}",
                     help=btn_help, use_container_width=True):
            with st.spinner("最新化中..."):
                # ページローカルの @st.cache_data も含めて全クリア(確実)
                st.cache_data.clear()
                if this_sheet:
                    sheets.refresh_sheet(this_sheet)
                else:
                    sheets.clear_all_caches()
            st.success("✅ 最新化しました")
            st.rerun()

    # ----- ページ上部 折りたたみツールバー -----
    with st.expander("⚡ ツール (再読込・表示サイズ等)", expanded=False):
        c1, c2, c3, c4 = st.columns(4)

        # このシートだけ再読込
        with c1:
            if this_sheet:
                if st.button(f"⚡ {this_sheet} 再読込",
                             use_container_width=True, type="primary",
                             key=f"tb_refresh_{page_id}",
                             help="他のシートのキャッシュは保持。最速"):
                    with st.spinner(f"「{this_sheet}」を取得中..."):
                        sheets.refresh_sheet(this_sheet)
                    st.success(f"✅ 「{this_sheet}」を更新")
                    st.rerun()
            else:
                st.caption("(再読込: 当該シート無し)")

        # 全シートプリロード
        with c2:
            if st.button("🚀 全シートプリロード",
                         use_container_width=True,
                         key=f"tb_preload_{page_id}",
                         help="全シートを1回のAPIで一括取得"):
                sheets.clear_all_caches()
                preloaded = sheets.preload_all_sheets()
                st.session_state["_preloaded_sheets"] = preloaded
                st.success(f"✅ {len(preloaded)}シート プリロード完了")
                st.rerun()

        # 全データ再読込
        with c3:
            if st.button("🔄 全データ再読込",
                         use_container_width=True,
                         key=f"tb_reload_{page_id}",
                         help="全キャッシュクリア + 全シート再取得"):
                sheets.clear_all_caches()
                st.rerun()

        # 接続リセット
        with c4:
            if st.button("🔌 接続リセット",
                         use_container_width=True,
                         key=f"tb_reset_{page_id}",
                         help="権限変更後に使用"):
                st.cache_resource.clear()
                st.cache_data.clear()
                st.session_state.pop("_preloaded_sheets", None)
                st.rerun()

        # 表示サイズスライダー
        st.markdown("---")
        new_size = st.slider(
            "🔠 文字サイズ(px)",
            min_value=12, max_value=24, value=font_size, step=1,
            key=f"tb_fontsize_{page_id}",
            help="テーブル・数値・本文の文字サイズ。全ページに反映",
        )
        if new_size != font_size:
            st.session_state["_font_size_px"] = new_size
            st.rerun()

        from lib.config import CACHE_TTL_SECONDS
        preloaded = st.session_state.get("_preloaded_sheets")
        cap_parts = [f"⏱ キャッシュTTL: {CACHE_TTL_SECONDS // 60}分"]
        if preloaded:
            cap_parts.append(f"📦 {len(preloaded)}シート キャッシュ中")
        st.caption(" / ".join(cap_parts))
