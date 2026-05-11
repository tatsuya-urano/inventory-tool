"""
新規SKU登録 — マスタ + 04_在庫管理 に同時登録

機能:
- 単発フォームで1件登録
- CSV/Excel 一括登録
- 既存SKUとの重複チェック
- マスタにあって04にないSKUを一覧表示 → 一括 04 追加
"""
from io import StringIO

import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="新規SKU登録", page_icon="➕", layout="wide")
st.title("➕ 新規SKU登録")
ui.sidebar_common(this_sheet="03_商品マスタ参照")

# ===========================================================
# 使い方（最初に必ず読む）
# ===========================================================
with st.expander("📌 このページで何ができる？(クリックして読む)", expanded=True):
    st.markdown(
        """
**一言: 新しい商品を扱い始める時 / マスタと04のズレを直す時 に使う、5つのツール詰合せページ。**

| # | セクション | 何をするか | 使う場面 |
|---|---|---|---|
| 1 | 📝 **新規SKU登録フォーム** | マスタ(03) + 04_在庫管理 に **同時登録** | 新商品を仕入れて初めて扱うとき |
| 2 | 🔄 **マスタにあって04にないSKUを追加** | マスタにあるのに04に行が無い差分を一覧 → 一括追加 | マスタを先に整備した後の同期 |
| 3 | 🧹 **04からコバリ子SKUを削除** | マスタU列(親SKU)に値があるSKUを04から除外 | コバリ運用に切り替えた直後の整理 |
| 4 | 🧹 **古ASIN行 → 楽天SKUへ統合** | 04にある `B0xxxxxxxx` 形式の行を、楽天SKUに統合してAF/AG列にAmazon SKUを記録 | プール在庫運用への移行時 |
| 5 | 🆕 **旧ASIN行を新FBA SKUに置換** | 旧ASINだった行を、新FBA SKUに付け替え（楽天SKU無し用） | FBA専売SKUの整理 |

### ⚠️ 共通の注意
- **重複チェックあり**: 既に同じ商品コードがマスタにあれば登録不可（警告表示）
- **A列同期と連動**: 商品コードを書き換えると 04 / 05 / PUSH対象 / 17_終売SKU の旧A列値も自動置換
- **AC列(手動原価)は触らない**: ここでは H列(計算原価) のみ書込
- **数式列(L利益額/M利益率)**: 自動で数式が再生成される

### 🔍 登録前の確認
ページ末尾の **「🔍 既存SKU検索」** で同じような商品が無いか先に確認すると安全。
"""
    )

with st.spinner("既存マスタ読込中..."):
    master_df = sheets.load_master()

if master_df.empty:
    st.error("マスタを読み込めませんでした")
    st.stop()

# 既存商品コード一覧（重複チェック用）
existing_codes = set(master_df.iloc[:, 0].astype(str).str.strip())
existing_codes.discard("")

c1, c2 = st.columns(2)
c1.metric("既存マスタ件数", f"{len(existing_codes):,}")

st.markdown("---")

st.markdown("### 📝 新規SKU情報を入力（個別登録）")

# ヘッダ選択 (CSV登録と同じヘッダを選択式)
ALL_FORM_FIELDS = [
    ("商品コード", "text"),
    ("タイトル", "text"),
    ("SKU番号", "text"),
    ("大分類", "text"),
    ("小分類", "text"),
    ("販売チャネル", "select_channel"),
    ("物流ルート", "select_route"),
    ("直接入力原価", "number"),
    ("チャネル別手数料", "text"),
    ("国内送料", "number"),
    ("売価", "number"),
    ("仕入先", "text"),
    ("バリエーション", "text"),
    ("商品コード(代行)", "text"),
    ("ラベル番号", "text"),
    ("オプション", "text"),
    ("オプション費用", "number"),
    ("最終発注日", "text"),
    ("親SKU", "text"),
    ("親SKU係数", "number"),
    ("セット組相手SKU", "text"),
    ("セット組備考", "text"),
    ("発注時係数", "number"),
    ("バッファ", "number"),
    ("重量", "number"),
    ("備考", "text"),
    ("楽天SKU", "text"),
    ("Amazon FBM SKU", "text"),
    ("Amazon FBA SKU", "text"),
]
# CSVテンプレと同じデフォルト21列
DEFAULT_VISIBLE = [
    "商品コード", "タイトル", "大分類", "小分類", "販売チャネル", "物流ルート",
    "直接入力原価", "チャネル別手数料", "国内送料", "売価",
    "仕入先", "バリエーション", "商品コード(代行)", "ラベル番号",
    "オプション費用", "発注時係数", "重量", "備考",
    "楽天SKU", "Amazon FBM SKU", "Amazon FBA SKU",
]

with st.expander("☝ 個別登録フォームを開く", expanded=False):
    selected_fields = st.multiselect(
        "📋 入力する項目を選択",
        options=[f[0] for f in ALL_FORM_FIELDS],
        default=DEFAULT_VISIBLE,
        key="new_sku_form_fields",
    )

    with st.form("new_sku_form"):
        field_values: dict[str, object] = {}
        cols = st.columns(2)
        for idx, (name, ftype) in enumerate(ALL_FORM_FIELDS):
            if name not in selected_fields:
                continue
            col = cols[idx % 2]
            with col:
                if ftype == "select_channel":
                    field_values[name] = st.selectbox(name, ["楽天専売", "AMA専売", "両方"], index=2, key=f"f_{name}")
                elif ftype == "select_route":
                    field_values[name] = st.selectbox(name, ["自社経由", "FBA直送"], index=0, key=f"f_{name}")
                elif ftype == "number":
                    field_values[name] = st.number_input(name, min_value=0, value=0, step=10, key=f"f_{name}")
                else:
                    placeholder = ""
                    if name == "商品コード":
                        placeholder = "例: NEWITEM-001 (必須)"
                    elif name == "チャネル別手数料":
                        placeholder = "例: 10.00%"
                    field_values[name] = st.text_input(name, placeholder=placeholder, key=f"f_{name}")

        # 既存変数に展開（後続コードと互換性）
        new_code = str(field_values.get("商品コード", "")).strip()
        new_title = str(field_values.get("タイトル", "")).strip()
        new_sku_no = str(field_values.get("SKU番号", "")).strip()
        new_big = str(field_values.get("大分類", "")).strip()
        new_small = str(field_values.get("小分類", "")).strip()
        new_channel = str(field_values.get("販売チャネル", "両方"))
        new_route = str(field_values.get("物流ルート", "自社経由"))
        new_cost = field_values.get("直接入力原価", 0) or 0
        new_fee = str(field_values.get("チャネル別手数料", "")).strip()
        new_ship = field_values.get("国内送料", 0) or 0
        new_price = field_values.get("売価", 0) or 0
        new_supplier = str(field_values.get("仕入先", "")).strip()
        new_ae = str(field_values.get("楽天SKU", "")).strip()
        new_af = str(field_values.get("Amazon FBM SKU", "")).strip()
        new_ag = str(field_values.get("Amazon FBA SKU", "")).strip()

        submitted = st.form_submit_button("💾 マスタ + 04 に登録", type="primary")

        if submitted:
            if not new_code.strip():
                st.error("商品コードは必須です")
                st.stop()
            if new_code.strip() in existing_codes:
                st.error(f"商品コード「{new_code}」は既にマスタに存在します")
                st.stop()

            with st.spinner("登録中..."):
                try:
                    ss = sheets.get_spreadsheet()
                    master_ws_tmp = ss.worksheet("03_商品マスタ参照")
                    inv_ws_tmp = ss.worksheet("04_在庫管理")

                    # 登録前の最終行 (col_values は2回まで)
                    master_before = len(master_ws_tmp.col_values(1))
                    inv_before = len(inv_ws_tmp.col_values(1))
                    next_row = master_before + 1
                    inv_next_row = inv_before + 1

                    # L/M列の数式
                    profit_formula = (
                        f'=IF(K{next_row}="","",K{next_row}'
                        f'-IF(H{next_row}="",0,H{next_row})'
                        f'-IF(I{next_row}="",0,IF(I{next_row}<1,K{next_row}*I{next_row},I{next_row}))'
                        f'-IF(J{next_row}="",0,J{next_row}))'
                    )
                    rate_formula = f'=IF(OR(K{next_row}="",K{next_row}=0),"",L{next_row}/K{next_row})'

                    # マスタ34列構成 (L/Mは数式)
                    # H列(原価)はARRAYFORMULAで自動計算なので空欄、AC列(直接入力原価)に入れる
                    master_row = [""] * 33
                    master_row[0] = new_code  # A
                    master_row[1] = new_title  # B
                    master_row[2] = new_sku_no  # C
                    master_row[3] = new_big  # D
                    master_row[4] = new_small  # E
                    master_row[5] = new_channel  # F
                    master_row[6] = new_route  # G
                    # H(原価) は ARRAYFORMULA で自動 → 空
                    master_row[8] = new_fee  # I
                    master_row[9] = new_ship  # J
                    master_row[10] = new_price  # K
                    # L(利益額) M(利益率) は ARRAYFORMULA → 空
                    master_row[13] = new_supplier  # N
                    master_row[28] = new_cost  # AC (直接入力原価)
                    master_row[30] = new_ae  # AE (楽天SKU)
                    master_row[31] = new_af  # AF (Amazon FBM SKU)
                    master_row[32] = new_ag  # AG (Amazon FBA SKU)
                    inv_row = [new_code, new_title, new_route]

                    # 書き込みは update() 2回。HTTPエラーが出れば例外を吐くので検証は不要
                    master_ws_tmp.update(
                        range_name=f"A{next_row}",
                        values=[master_row],
                        value_input_option="USER_ENTERED",
                    )
                    inv_ws_tmp.update(
                        range_name=f"A{inv_next_row}",
                        values=[inv_row],
                        value_input_option="USER_ENTERED",
                    )
                    sheets._invalidate_one("03_商品マスタ参照")
                    sheets._invalidate_one("04_在庫管理")

                    st.success(
                        f"✅ 登録完了\n\n"
                        f"- 商品コード: `{new_code}`\n"
                        f"- 03_商品マスタ参照 row{next_row} (行数 {master_before} → {master_before + 1})\n"
                        f"- 04_在庫管理 row{inv_next_row} (行数 {inv_before} → {inv_before + 1})\n\n"
                        f"⚠ スプシ画面はキャッシュで古く見える事あり。Ctrl+F5でリロード推奨"
                    )
                    st.balloons()
                except Exception as e:
                    st.error(f"登録失敗: {e}")
                    import traceback
                    st.code(traceback.format_exc())

st.markdown("---")

# ===========================================================
# 📥 CSV/Excel 一括登録
# ===========================================================
st.markdown("### 📥 CSV/Excel 一括登録")
st.caption(
    "商品コード必須・他列は任意。既存SKUは自動スキップ。"
    "L列(利益額)・M列(利益率)はCSVに含めても無視され、行追加時に数式が自動生成される。"
)

# テンプレダウンロード(必要なヘッダだけ選んでDL可能)
ALL_TEMPLATE_FIELDS = [
    ("商品コード",         "例: NEWITEM-001"),
    ("タイトル",           "新商品ABC"),
    ("SKU番号",           ""),
    ("大分類",             "雑貨"),
    ("小分類",             "R999アイテム名"),
    ("販売チャネル",       "両方"),
    ("物流ルート",         "自社経由"),
    ("原価",               200),
    ("チャネル別手数料",   "10.00%"),
    ("国内送料",           187),
    ("売価",               980),
    ("仕入先",             "Rakumart"),
    ("バリエーション",     ""),
    ("商品コード(代行)",   ""),
    ("ラベル番号",         ""),
    ("オプション",         ""),
    ("オプション費用",     ""),
    ("最終発注日",         ""),
    ("親SKU",              ""),
    ("親SKU係数",          ""),
    ("セット組相手SKU",    ""),
    ("セット組備考",       ""),
    ("発注時係数",         1),
    ("バッファ",           0),
    ("重量",               100),
    ("備考",               ""),
    ("直接入力原価",       ""),
    ("楽天SKU",            "newitem-001-rk"),
    ("Amazon FBM SKU",     "newitem-001-fbm"),
    ("Amazon FBA SKU",     ""),
]
ALL_FIELD_NAMES = [k for k, _ in ALL_TEMPLATE_FIELDS]
DEFAULT_TEMPLATE_FIELDS = [
    "商品コード", "タイトル", "大分類", "小分類", "販売チャネル", "物流ルート",
    "原価", "チャネル別手数料", "国内送料", "売価",
    "仕入先", "バリエーション", "商品コード(代行)", "ラベル番号",
    "オプション費用", "発注時係数", "重量", "備考",
    "楽天SKU", "Amazon FBM SKU", "Amazon FBA SKU",
]

with st.expander("📄 テンプレCSVダウンロード(含めるヘッダを選択)", expanded=False):
    st.caption("不要な列のチェックを外してダウンロードできます。商品コードは必須(自動チェック)")

    # プリセットボタン
    pc1, pc2, pc3 = st.columns(3)
    if pc1.button(f"基本セット({len(DEFAULT_TEMPLATE_FIELDS)}列)", use_container_width=True, key="tmpl_basic"):
        st.session_state["_tmpl_fields"] = list(DEFAULT_TEMPLATE_FIELDS)
        st.rerun()
    if pc2.button("商品コードのみ", use_container_width=True, key="tmpl_min"):
        st.session_state["_tmpl_fields"] = ["商品コード"]
        st.rerun()
    if pc3.button("全て(30列)", use_container_width=True, key="tmpl_all"):
        st.session_state["_tmpl_fields"] = list(ALL_FIELD_NAMES)
        st.rerun()

    saved_fields = st.session_state.get("_tmpl_fields", DEFAULT_TEMPLATE_FIELDS)
    saved_fields = [f for f in saved_fields if f in ALL_FIELD_NAMES]
    if "商品コード" not in saved_fields:
        saved_fields.insert(0, "商品コード")

    selected_fields = st.multiselect(
        "含めるヘッダを選択(順番は元のマスタ順)",
        options=ALL_FIELD_NAMES,
        default=saved_fields,
        key="_tmpl_fields_ms",
    )
    if "商品コード" not in selected_fields:
        selected_fields = ["商品コード"] + selected_fields
    # 元の順序を保持
    final_fields = [f for f in ALL_FIELD_NAMES if f in selected_fields]
    st.session_state["_tmpl_fields"] = final_fields

    # テンプレ生成
    sample_map = dict(ALL_TEMPLATE_FIELDS)
    template_df = pd.DataFrame([{f: sample_map.get(f, "") for f in final_fields}])
    template_csv = template_df.to_csv(index=False).encode("utf-8-sig")

    st.markdown(f"**プレビュー({len(final_fields)}列)**")
    st.dataframe(template_df, use_container_width=True, hide_index=True)

    st.download_button(
        f"📄 テンプレCSVダウンロード({len(final_fields)}列)",
        template_csv,
        file_name=f"master_register_template_{len(final_fields)}cols.csv",
        mime="text/csv",
        use_container_width=True,
        type="primary",
    )

st.caption(
    "💡 インポート時は CSV のどんなヘッダ名でも、下のマッピングでマスタ列に割り当てられます。"
    "先頭0付きSKUは Excelで開くと0が落ちるのでメモ帳/VSCode 推奨"
)

uploaded = st.file_uploader(
    "CSV / TSV / Excel ファイル", type=["csv", "tsv", "xlsx", "xls"], key="master_uploader",
)
pasted = st.text_area("または貼り付け(タブ or カンマ区切り)", height=120, key="master_paste")

new_data = None
if uploaded is not None:
    try:
        if uploaded.name.lower().endswith((".xlsx", ".xls")):
            new_data = pd.read_excel(uploaded, dtype=str).fillna("")
        else:
            content = uploaded.read().decode("utf-8-sig", errors="replace")
            sep = "\t" if content.split("\n")[0].count("\t") > content.split("\n")[0].count(",") else ","
            new_data = pd.read_csv(StringIO(content), sep=sep, dtype=str).fillna("")
        st.success(f"読込: {len(new_data)}行 × {len(new_data.columns)}列")
    except Exception as e:
        st.error(f"読込失敗: {e}")
elif pasted.strip():
    try:
        first = pasted.split("\n")[0]
        sep = "\t" if first.count("\t") > first.count(",") else ","
        new_data = pd.read_csv(StringIO(pasted), sep=sep, dtype=str).fillna("")
        st.success(f"読込: {len(new_data)}行 × {len(new_data.columns)}列")
    except Exception as e:
        st.error(f"読込失敗: {e}")

if new_data is not None and not new_data.empty:
    # マスタ列マッピング (CSV列名 → スプシ列インデックス)
    # マスタ34列のうち、数式列(L=11, M=12, AD=29, AH=33)は自動生成のため除外
    # それ以外30列は全てマッピング可能
    COL_CANDIDATES = {
        0:  ("A 商品コード(必須)", ["商品コード", "SKU", "code", "管理番号"]),
        1:  ("B タイトル", ["タイトル", "商品名", "title"]),
        2:  ("C SKU番号", ["SKU番号"]),
        3:  ("D 大分類", ["大分類"]),
        4:  ("E 小分類", ["小分類"]),
        5:  ("F 販売チャネル", ["販売チャネル", "チャネル", "チャネル区分"]),
        6:  ("G 物流ルート", ["物流ルート", "ルート"]),
        # H列(7)は数式列なので除外。「原価」ヘッダはAC列(28)にマッピングする
        # 7:  ("H 原価", ["原価", "cost"]),  # ← 数式列のため除外
        8:  ("I チャネル別手数料", ["手数料", "手数料率"]),
        9:  ("J 国内送料", ["国内送料", "送料", "ship"]),
        10: ("K 売価", ["売価", "price", "販売価格"]),
        13: ("N 仕入先", ["仕入先", "supplier"]),
        14: ("O バリエーション", ["バリエーション"]),
        15: ("P 商品コード(代行)", ["商品コード(代行)", "代行コード"]),
        16: ("Q ラベル番号", ["ラベル番号", "FNSKU"]),
        17: ("R オプション", ["オプション"]),
        18: ("S オプション費用", ["オプション費用"]),
        19: ("T 最終発注日", ["最終発注日"]),
        20: ("U 親SKU", ["親SKU"]),
        21: ("V 親SKU係数", ["親SKU係数"]),
        22: ("W セット組相手SKU", ["セット組相手", "セット組"]),
        23: ("X セット組備考", ["セット組備考"]),
        24: ("Y 発注時係数", ["発注時係数"]),
        25: ("Z バッファ", ["バッファ"]),
        26: ("AA 重量", ["重量", "weight"]),
        27: ("AB 備考", ["備考", "メモ"]),
        28: ("AC 直接入力原価", ["直接入力原価", "手動原価", "原価", "cost"]),
        30: ("AE 楽天SKU", ["楽天SKU", "rakuten"]),
        31: ("AF Amazon FBM SKU", ["Amazon FBM", "FBM SKU", "FBM"]),
        32: ("AG Amazon FBA SKU", ["Amazon FBA", "FBA SKU", "FBA"]),
    }

    st.markdown("**🔗 列マッピング(自動推定済み・必要なら変更)**")
    csv_cols = list(new_data.columns)
    csv_options = ["（無視）"] + csv_cols

    mapping: dict[int, str] = {}
    cols_per_row = 3
    items = list(COL_CANDIDATES.items())
    for row_start in range(0, len(items), cols_per_row):
        cols_ui = st.columns(cols_per_row)
        for offset, (sheet_idx, (label, kws)) in enumerate(items[row_start:row_start + cols_per_row]):
            # 自動推定
            guess_idx = 0
            for i, csv_c in enumerate(csv_cols):
                if any(kw in str(csv_c) for kw in kws):
                    guess_idx = i + 1
                    break
            with cols_ui[offset]:
                sel = st.selectbox(
                    label,
                    csv_options, index=guess_idx,
                    key=f"map_{sheet_idx}",
                )
                if sel != "（無視）":
                    mapping[sheet_idx] = sel

    if 0 not in mapping:
        st.error("商品コード列を選択してください")
        st.stop()

    # 既存マスタ商品コード set (重複検出用)
    existing_codes_lc = {c.strip(): c for c in existing_codes}

    # 取込予定 + 重複/新規判定
    code_csv_col = mapping[0]
    new_data[code_csv_col] = new_data[code_csv_col].astype(str).str.strip()
    new_data = new_data[new_data[code_csv_col] != ""].reset_index(drop=True)

    is_dup = new_data[code_csv_col].isin(existing_codes_lc.keys())
    dup_count = int(is_dup.sum())
    new_count = len(new_data) - dup_count

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("CSV総行数", len(new_data))
    mc2.metric("✅ 新規登録", new_count)
    mc3.metric("⚠ 重複(スキップ)", dup_count)

    if dup_count > 0:
        with st.expander(f"⚠ 重複SKU {dup_count}件 (登録スキップ)"):
            st.write(new_data[is_dup][code_csv_col].tolist()[:50])

    # プレビュー
    if new_count > 0:
        preview_df = new_data[~is_dup].head(10).copy()
        st.markdown("**👀 新規登録プレビュー(先頭10件)**")
        st.dataframe(preview_df, use_container_width=True, hide_index=True)

        # 04_在庫管理にも追加するか
        also_add_inv = st.checkbox(
            "✅ 04_在庫管理 にも同時に追加 (商品コード/タイトル/物流ルート)",
            value=True,
            key="also_add_inv",
        )

        if st.button(f"📤 {new_count}件をマスタに登録", type="primary",
                     use_container_width=True, key="csv_register"):
            with st.spinner("登録中..."):
                try:
                    ss = sheets.get_spreadsheet()
                    master_ws = ss.worksheet("03_商品マスタ参照")
                    inv_ws = ss.worksheet("04_在庫管理")

                    # マスタ最終行を取得
                    next_row = len(master_ws.col_values(1)) + 1

                    # 各行を構築 (33列 = A〜AG、行番号で数式生成)
                    master_rows = []
                    inv_rows = []
                    for offset, (_, r) in enumerate(new_data[~is_dup].iterrows()):
                        row_num = next_row + offset
                        # 33列空配列
                        row = [""] * 33
                        for sheet_idx, csv_c in mapping.items():
                            row[sheet_idx] = str(r[csv_c]).strip()
                        # L列(11) M列(12) は ARRAYFORMULA で全行一括計算されているので
                        # 個別の数式を書き込まない（書き込むとARRAYFORMULAが壊れる）
                        # row[11], row[12] は空のままにする
                        master_rows.append(row)

                        # 04 用
                        if also_add_inv:
                            code = row[0]
                            title = row[1]
                            route = row[6] or "自社経由"
                            inv_rows.append([code, title, route])

                    # マスタに一括追加
                    if master_rows:
                        master_ws.update(
                            range_name=f"A{next_row}",
                            values=master_rows,
                            value_input_option="USER_ENTERED",
                        )
                        sheets._invalidate_one("03_商品マスタ参照")

                    # 04に追加
                    if also_add_inv and inv_rows:
                        inv_next_row = len(inv_ws.col_values(1)) + 1
                        inv_ws.update(
                            range_name=f"A{inv_next_row}",
                            values=inv_rows,
                            value_input_option="USER_ENTERED",
                        )
                        sheets._invalidate_one("04_在庫管理")

                    st.success(
                        f"✅ {len(master_rows)}件 マスタに登録"
                        + (f" / {len(inv_rows)}件 04にも追加" if also_add_inv else "")
                        + (f" / {dup_count}件 重複スキップ" if dup_count else "")
                    )
                    st.balloons()
                    st.rerun()
                except Exception as e:
                    st.error(f"登録失敗: {e}")
                    import traceback
                    st.code(traceback.format_exc())

st.markdown("---")


st.markdown("---")

# 既存SKU検索（重複防止用）
with st.expander("🔍 既存SKU検索（登録前の重複確認）"):
    search = st.text_input("商品コード or タイトルで検索", "")
    if search:
        mask = master_df.iloc[:, 0].astype(str).str.contains(search, case=False, na=False)
        if len(master_df.columns) > 1:
            mask |= master_df.iloc[:, 1].astype(str).str.contains(search, case=False, na=False)
        results = master_df[mask].head(20)
        st.caption(f"{len(results)}件ヒット（最大20件表示）")
        st.dataframe(results.iloc[:, :5], use_container_width=True, hide_index=True)
