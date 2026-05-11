"""
17_終売SKU / 発注見送りSKU 編集ページ

- 種別列(D列)で「終売」「発注見送り」を区別
- 17_終売SKUに登録された全SKUは:
  - 04 M列(推奨発注数)=0 (ARRAYFORMULAでCOUNTIF除外)
  - FBA補充プランでも除外
- 発注見送り = 一時的に発注を止めたいSKU。終売とは違い売上記録は通常通り
"""
from datetime import date
from io import StringIO

import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="終売/発注見送りSKU", page_icon="🚫", layout="wide")
st.title("🚫 17_終売SKU / ⏸️ 発注見送りSKU（編集可）")
ui.sidebar_common()

SHEET_NAME = "17_終売SKU"

KIND_DISCONTINUED = "終売"
KIND_SKIP = "発注見送り"
KIND_OPTIONS = [KIND_DISCONTINUED, KIND_SKIP]

# ===========================================================
# 使い方
# ===========================================================
with st.expander("📌 終売SKU / 発注見送り とは？(クリックして読む)", expanded=False):
    st.markdown(
        """
**結論: どちらに登録しても「推奨発注リスト・FBA補充プランから除外」されます。**

| 種別 | 用途 | 取消 |
|---|---|---|
| 🚫 **終売** | 完全に売らなくする商品 | テーブルから行削除 |
| ⏸️ **発注見送り** | 一時的に発注を止めたいSKU。売上は通常通り集計 | 同上 |

### 🎯 登録するとどうなる？(共通)
- 🛒 **推奨発注リスト**: 自動除外
- 📦 **FBA補充プラン**: 自動除外
- 04_在庫管理 の **M列(推奨発注数) = 0**
- 売上記録は**残る**

### 📝 登録方法
1. **マスタ検索 → 一括登録**: 「➕ マスタから検索して登録」を開く
2. **テーブル直接編集**: 下部のテーブルで種別列を切り替え
3. **CSV取込**: 大量登録向き

### 🔄 取り消したい場合
- テーブルで該当行を削除 → 「💾 スプシに保存」

### 📋 列構成（D列に「種別」を追加してください）
- A: 商品コード（必須）
- B: 小分類（自動補完）
- C: 終売日（任意）
- **D: 種別**（`終売` または `発注見送り`、未入力は終売扱い）
"""
    )

# ===========================================================
# データ読込
# ===========================================================
with st.spinner("読み込み中..."):
    df = sheets.load_any_sheet(SHEET_NAME, header_row=1, data_start_row=2)

if df.empty:
    df = pd.DataFrame()

CODE_COL  = sheets.find_col(df, ["商品コード", "SKU", "コード"]) if not df.empty else None
SMALL_COL = sheets.find_col(df, ["小分類"]) if not df.empty else None
DATE_COL  = sheets.find_col(df, ["終売日", "日付"]) if not df.empty else None
KIND_COL  = sheets.find_col(df, ["種別", "区分", "type"]) if not df.empty else None

if df.empty or not CODE_COL:
    st.warning("⚠ 既存データなし or 商品コード列なし。デフォルトで初期化")
    CODE_COL, SMALL_COL, DATE_COL, KIND_COL = "商品コード", "小分類", "終売日", "種別"
    df = pd.DataFrame(columns=[CODE_COL, SMALL_COL, DATE_COL, KIND_COL])

# 種別列がなければ警告 + 仮想列で扱う(保存時はスプシD列に書き込み試行)
kind_col_exists = KIND_COL is not None
if not kind_col_exists:
    st.warning(
        "⚠ シートに「種別」列(D列)がありません。すべて『終売』として扱います。\n"
        "→ スプシのD1セルに「種別」と入力すると、終売/発注見送り を選別できます"
    )
    KIND_COL = "種別"
    df[KIND_COL] = KIND_DISCONTINUED

# 種別の正規化（空欄/想定外は終売扱い）
def _normalize_kind(v: str) -> str:
    s = str(v).strip()
    if KIND_SKIP in s or "見送" in s:
        return KIND_SKIP
    return KIND_DISCONTINUED

df[KIND_COL] = df[KIND_COL].apply(_normalize_kind)

with st.expander("🐛 デバッグ情報", expanded=False):
    st.caption(f"実ヘッダ: {list(df.columns)}")
    st.caption(
        f"検出列: 商品コード=`{CODE_COL}` / 小分類=`{SMALL_COL or '(なし)'}` "
        f"/ 終売日=`{DATE_COL or '(なし)'}` / 種別=`{KIND_COL}`{' (シート未存在)' if not kind_col_exists else ''}"
    )

# ===========================================================
# サマリ
# ===========================================================
n_disc = int((df[KIND_COL] == KIND_DISCONTINUED).sum())
n_skip = int((df[KIND_COL] == KIND_SKIP).sum())
c1, c2, c3 = st.columns(3)
c1.metric("🚫 終売", f"{n_disc:,}")
c2.metric("⏸️ 発注見送り", f"{n_skip:,}")
c3.metric("合計", f"{len(df):,}")

st.markdown("---")

# ===========================================================
# マスタ検索 → 一括登録
# ===========================================================
with st.expander("➕ マスタから検索して一括登録", expanded=True):
    with st.spinner("マスタ読込中..."):
        master_df = sheets.load_master()

    # 種別選択 (登録ボタンの横)
    add_kind = st.radio(
        "登録する種別",
        KIND_OPTIONS,
        horizontal=True,
        index=1,  # 初期値は発注見送り(終売は手動編集の方が安全)
        key="add_kind_radio",
    )

    keyword_add = st.text_input(
        "🔍 商品コード or タイトルで検索（部分一致）",
        "",
        key="master_search_for_add",
        placeholder="例: gipssandal / ギプス",
    )

    if keyword_add.strip() and not master_df.empty:
        m_code = master_df.columns[0]
        m_title = master_df.columns[1] if len(master_df.columns) > 1 else None
        mask = master_df[m_code].astype(str).str.contains(keyword_add, case=False, na=False)
        if m_title:
            mask |= master_df[m_title].astype(str).str.contains(keyword_add, case=False, na=False)
        hits = master_df[mask].head(50)

        if hits.empty:
            st.info("マスタにヒットなし")
        else:
            st.caption(f"ヒット {len(hits)}件 (上位50)")
            display = hits[[m_code] + ([m_title] if m_title else [])].copy()
            display.columns = ["商品コード"] + (["タイトル"] if m_title else [])

            # 既存登録済みコードを排除して候補とする
            existing_codes = set(df[CODE_COL].astype(str).str.strip())
            options = [c for c in display["商品コード"].tolist() if c not in existing_codes]
            already = [c for c in display["商品コード"].tolist() if c in existing_codes]
            if already:
                st.caption(f"※ 登録済みのため候補から除外: {', '.join(already[:10])}{'...' if len(already)>10 else ''}")

            sel_codes = st.multiselect(
                f"✅ {add_kind} として登録するSKUを選択",
                options,
                key="discontinued_select",
            )

            new_date = (
                st.date_input("終売日(任意)", value=date.today(), key="discontinued_date")
                if DATE_COL else None
            )

            st.dataframe(display, use_container_width=True, hide_index=True, height=300)

            btn_label = f"➕ 選択 {len(sel_codes)}件 を「{add_kind}」として登録"
            if st.button(
                btn_label,
                type="primary",
                disabled=(len(sel_codes) == 0),
            ):
                code_to_title = {}
                if m_title:
                    for c, t in zip(
                        master_df[m_code].astype(str).str.strip(),
                        master_df[m_title].astype(str),
                    ):
                        if c:
                            code_to_title[c] = t

                title_col_in_disc = df.columns[1] if len(df.columns) > 1 else None
                rows_to_add = []
                for c in sel_codes:
                    value_map = {CODE_COL: c}
                    if title_col_in_disc:
                        value_map[title_col_in_disc] = code_to_title.get(c, "")
                    if DATE_COL and new_date and add_kind == KIND_DISCONTINUED:
                        value_map[DATE_COL] = new_date.strftime("%Y-%m-%d")
                    if kind_col_exists:
                        value_map[KIND_COL] = add_kind
                    rows_to_add.append(sheets.build_row_by_header(df.columns, value_map))
                with st.spinner(f"{add_kind} に追加中..."):
                    sheets.append_rows(SHEET_NAME, rows_to_add)
                if not kind_col_exists and add_kind == KIND_SKIP:
                    st.warning(
                        "⚠ シートに種別列がないため、追加した行は『終売』として扱われます。\n"
                        "スプシのD1に「種別」を入れてから、各行のD列に「発注見送り」を記入してください"
                    )
                st.success(f"✅ {len(sel_codes)}件を「{add_kind}」として追加")
                sheets._invalidate_one(SHEET_NAME)
                st.rerun()
    else:
        st.caption("商品コードかタイトルで検索すると、マスタから候補が出ます")

st.markdown("---")
st.markdown("### 🔍 検索 / ✏️ 編集（行削除可）")

# 種別フィルタ
fc1, fc2 = st.columns([1, 3])
with fc1:
    kind_filter = st.selectbox(
        "種別フィルタ",
        ["（全て）", f"🚫 {KIND_DISCONTINUED}", f"⏸️ {KIND_SKIP}"],
        index=0,
        key="kind_filter",
    )
with fc2:
    search_kw = st.text_input(
        "商品コード or タイトルで絞り込み（カンマ区切り複数可）",
        "",
        key="discontinued_search",
    )

view_df = df.copy()
if kind_filter.endswith(KIND_DISCONTINUED):
    view_df = view_df[view_df[KIND_COL] == KIND_DISCONTINUED]
elif kind_filter.endswith(KIND_SKIP):
    view_df = view_df[view_df[KIND_COL] == KIND_SKIP]

if search_kw.strip():
    keywords = [k.strip() for k in search_kw.split(",") if k.strip()]
    masks = []
    for k in keywords:
        m = view_df.iloc[:, 0].astype(str).str.contains(k, case=False, na=False)
        if len(view_df.columns) > 1:
            m |= view_df.iloc[:, 1].astype(str).str.contains(k, case=False, na=False)
        masks.append(m)
    if masks:
        combined = masks[0]
        for m in masks[1:]:
            combined |= m
        view_df = view_df[combined]

st.caption(f"絞り込み中: {len(view_df):,} / {len(df):,} 件")

# 種別列をセレクトボックス化
column_config = {}
if KIND_COL in view_df.columns:
    column_config[KIND_COL] = st.column_config.SelectboxColumn(
        label=f"🟢 {KIND_COL}",
        options=KIND_OPTIONS,
        required=False,
    )

edited = st.data_editor(
    view_df,
    use_container_width=True,
    height=500,
    hide_index=True,
    num_rows="dynamic",
    column_config=column_config,
    key="discontinued_editor",
)

col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    if st.button("💾 スプシに保存", type="primary"):
        with st.spinner("書込中..."):
            # 検索/種別フィルタ中なら、表示外の行も保持してマージ
            is_filtered = (kind_filter != "（全て）") or bool(search_kw.strip())
            if is_filtered and CODE_COL and CODE_COL in edited.columns:
                visible_codes = set(view_df[CODE_COL].astype(str).str.strip())
                outside_df = df[~df[CODE_COL].astype(str).str.strip().isin(visible_codes)]
                merged = pd.concat([outside_df, edited], ignore_index=True)
                to_save = merged[merged[CODE_COL].astype(str).str.strip() != ""]
            elif CODE_COL and CODE_COL in edited.columns:
                to_save = edited[edited[CODE_COL].astype(str).str.strip() != ""]
            else:
                to_save = edited

            # 種別列がシートに無い場合は保存対象から除外
            if not kind_col_exists and KIND_COL in to_save.columns:
                to_save = to_save.drop(columns=[KIND_COL])

            # マスタ存在チェック
            try:
                master_df_check = sheets.load_master()
                master_codes = set(master_df_check.iloc[:, 0].astype(str).str.strip())
                if CODE_COL and CODE_COL in to_save.columns:
                    code_strs = to_save[CODE_COL].astype(str).str.strip()
                    in_master = code_strs.isin(master_codes)
                    excluded = to_save[~in_master]
                    to_save = to_save[in_master]
                    if len(excluded) > 0:
                        st.warning(
                            f"⚠ マスタにないSKU {len(excluded)}件を除外: "
                            f"{excluded[CODE_COL].head(20).tolist()}"
                        )
            except Exception as e:
                st.error(f"マスタチェック失敗: {e}")

            sheets.replace_sheet_data(SHEET_NAME, to_save, header_row=1, data_start_row=2)
        st.success(f"✅ {len(to_save)}件保存")
        sheets._invalidate_one(SHEET_NAME)
        st.rerun()
with col2:
    if st.button("🔄 再読込"):
        sheets.clear_all_caches()
        st.rerun()
with col3:
    st.caption("💡 種別を変更したら「💾 スプシに保存」")

# ===========================================================
# CSV取込 / テンプレ
# ===========================================================
st.markdown("---")
st.markdown("### 📥 CSV取込 / テンプレ")

today_str = date.today().strftime("%Y-%m-%d")
template_df = pd.DataFrame([
    {"商品コード": "例: cameraholder2K", "終売日": today_str,    "種別": "終売"},
    {"商品コード": "例: 01GL1",          "終売日": "",             "種別": "発注見送り"},
])
template_csv = template_df.to_csv(index=False).encode("utf-8-sig")

dc1, dc2 = st.columns([1, 3])
with dc1:
    st.download_button(
        "📄 テンプレCSVダウンロード",
        template_csv,
        file_name="discontinued_template.csv",
        mime="text/csv",
        use_container_width=True,
    )
with dc2:
    st.caption(
        "📝 列: `商品コード`(必須), `終売日`(任意), `種別`(`終売`/`発注見送り`、未入力は終売)"
    )

upload_mode = st.radio(
    "取込モード",
    ["➕ 追加（既存にプラス）", "♻️ 置換（既存を全削除して入替）"],
    horizontal=True,
    key="disc_upload_mode",
)

uploaded = st.file_uploader(
    "CSV / TSV / Excel ファイル",
    type=["csv", "tsv", "xlsx", "xls"],
    key="disc_uploader",
)
pasted = st.text_area(
    "または貼り付け（タブ or カンマ区切り）",
    height=120,
    key="disc_paste",
)

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
    code_candidates = [c for c in new_data.columns if any(
        kw in str(c) for kw in ["商品コード", "SKU", "コード", "product"]
    )]
    date_candidates = [c for c in new_data.columns if any(
        kw in str(c) for kw in ["終売日", "終売", "日付", "date"]
    )]
    kind_candidates = [c for c in new_data.columns if any(
        kw in str(c) for kw in ["種別", "区分", "type", "kind"]
    )]

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        sel_code = st.selectbox(
            "商品コード列",
            options=list(new_data.columns),
            index=(list(new_data.columns).index(code_candidates[0])
                   if code_candidates else 0),
            key="disc_csv_code",
        )
    with mc2:
        date_options = ["（無視・空欄で取込）"] + list(new_data.columns)
        sel_date = st.selectbox(
            "終売日列（任意）",
            options=date_options,
            index=(date_options.index(date_candidates[0])
                   if date_candidates else 0),
            key="disc_csv_date",
        )
    with mc3:
        kind_options = ["（一括指定）"] + list(new_data.columns)
        sel_kind = st.selectbox(
            "種別列（任意）",
            options=kind_options,
            index=(kind_options.index(kind_candidates[0])
                   if kind_candidates else 0),
            key="disc_csv_kind",
        )
        default_kind = st.selectbox(
            "↑が無い場合の一括種別",
            KIND_OPTIONS,
            index=0,
            key="disc_csv_default_kind",
        )

    mapped = pd.DataFrame()
    mapped["商品コード"] = new_data[sel_code].astype(str).str.strip()
    mapped["小分類"] = ""
    if sel_date != "（無視・空欄で取込）":
        mapped["終売日"] = new_data[sel_date].astype(str).str.strip()
    else:
        mapped["終売日"] = ""
    if sel_kind != "（一括指定）":
        mapped["種別"] = new_data[sel_kind].astype(str).apply(_normalize_kind)
    else:
        mapped["種別"] = default_kind
    mapped = mapped[mapped["商品コード"] != ""].reset_index(drop=True)

    st.markdown("**👀 マッピング後プレビュー（先頭10件）**")
    st.dataframe(mapped.head(10), use_container_width=True, hide_index=True)
    n_d = int((mapped["種別"] == KIND_DISCONTINUED).sum())
    n_s = int((mapped["種別"] == KIND_SKIP).sum())
    st.caption(f"取込予定: {len(mapped)}件 (🚫終売 {n_d} / ⏸️発注見送り {n_s}) / 既存: {len(df)}件")

    if st.button("📤 取込実行", type="primary", use_container_width=True, key="disc_csv_apply"):
        with st.spinner("書込中..."):
            try:
                if upload_mode.startswith("♻️"):
                    save_df = mapped if kind_col_exists else mapped.drop(columns=["種別"])
                    sheets.replace_sheet_data(
                        SHEET_NAME, save_df, header_row=1, data_start_row=2,
                    )
                    st.success(f"✅ 置換完了: {len(mapped)}件")
                else:
                    existing_codes = (
                        set(df[CODE_COL].astype(str).str.strip().tolist())
                        if CODE_COL and CODE_COL in df.columns else set()
                    )
                    dup = [c for c in mapped["商品コード"] if c in existing_codes]
                    new_rows = mapped[~mapped["商品コード"].isin(existing_codes)]
                    if not new_rows.empty:
                        if kind_col_exists:
                            rows_2d = [
                                [r["商品コード"], "", r["終売日"], r["種別"]]
                                for _, r in new_rows.iterrows()
                            ]
                        else:
                            rows_2d = [
                                [r["商品コード"], "", r["終売日"]]
                                for _, r in new_rows.iterrows()
                            ]
                        sheets.append_rows(SHEET_NAME, rows_2d)
                    st.success(
                        f"✅ 追加完了: 新規{len(new_rows)}件"
                        + (f" / 重複スキップ{len(dup)}件" if dup else "")
                    )
                sheets._invalidate_one(SHEET_NAME)
                st.balloons()
                st.rerun()
            except Exception as e:
                st.error(f"取込失敗: {e}")
