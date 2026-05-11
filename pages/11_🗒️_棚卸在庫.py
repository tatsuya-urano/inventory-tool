"""
14_棚卸在庫シート ページ

機能:
- 空なら「棚卸開始」ボタン → 04の全SKUを商品コード+小分類でA/B列に書き出し
- データありなら編集テーブル + 保存
"""
import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="棚卸在庫", page_icon="🗒️", layout="wide")
st.title("🗒️ 14_棚卸在庫シート")

SHEET_NAME = "14_棚卸在庫シート"
ui.sidebar_common(this_sheet=SHEET_NAME)

# ===========================================================
# 使い方(最初に必ず読む)
# ===========================================================
with st.expander("📌 棚卸とは？このページでの作業の流れ(クリックして読む)", expanded=True):
    st.markdown(
        """
### 🎯 目的
月1回など定期的に **倉庫の実物をカウント** して、システム上の在庫数を実態に合わせる作業です。
仕入記録と販売記録だけでは把握できない **誤差(紛失/誤発送/破損など)** を補正します。

---

### 📝 作業の流れ(順序が大事)

#### ⚠️ ステップ0: 必ず先に売上同期する
**棚卸の前に楽天/Amazonの最新注文を取り込んでおく** こと。
- GASメニュー「📦 在庫操作」→「楽天/Amazon取得」を実行
- または GAS の `intervalIncrementalSync`(10分毎) の直後を狙う
- これをやらないと、棚卸後に未同期の売上が遅れて入って、F列(自社倉庫)が **余分に減ります**

#### 1️⃣ 棚卸シートを準備する
- このページを開いた時に **空** であれば → 「📋 棚卸シート準備」ボタンで04の全SKUを書き出し
- すでにデータがあれば → そのまま編集モードに

#### 2️⃣ 実物カウントを入力する(以下のいずれか)
- **A. このページで直接編集**: テーブルの「🟢 実カウント数」列に数値を入力
- **B. 紙でカウント → CSV取込**:
  1. 「📥 CSVエクスポート」でCSVダウンロード
  2. 印刷 or タブレットで開く
  3. 倉庫を回って実数を C列に書く
  4. ページ下部「📤 CSVインポート」でアップロード
  5. インポートモード:
     - **全置換** → CSVの内容で完全に上書き
     - **C列のみ更新** → 商品コードでマッチして実カウント数だけ反映

#### 3️⃣ 入力したら保存
- 「💾 入力を保存」を押す(他PCと同期するため)

#### 4️⃣ 在庫に逆算反映
- ページ下部の **「🚀 04のG列(月初在庫)に逆算反映」** ボタンで:
  - **G(月初在庫) = 実カウント数 - I(当月入荷) + J(当月廃棄) + N(当月販売数+コバリ消費)** で逆算
  - 結果として **F列(自社倉庫) = 実カウント数** になる(数式の整合性)
  - 月途中でも正しく反映できる(月初に戻って「もし在庫がX個あったら今のFがcountになる」と逆算)
  - 反映後は棚卸シートを自動クリア(2重反映防止)

---

### 💡 なぜ「逆算」?
04のF列(自社倉庫)は数式で `F = G + I - J - N` と計算されています。
ここで `G = count` と直接入れると、月途中の入荷/廃棄/売上が二重に効いてズレます。
逆算で G を調整することで、**棚卸時点の F が count にぴったり**になります。

### ⚠️ 注意
- **実カウント数が空欄の行はスキップ** されます(0個の場合は明示的に `0` を入力)
- 04に存在しない商品コードは「未マッチ」として警告表示。マスタに追加するか行を削除して再実行
- 棚卸後に過去日付の売上が遅れて同期されると、F列が余分に減ります → ステップ0を必ず実施
"""
    )

# データ取得
with st.spinner("読込中..."):
    df = sheets.load_any_sheet(SHEET_NAME, header_row=1, data_start_row=2)

if df.empty:
    st.info("📦 棚卸シートは空です（棚卸期間以外はクリアされる仕様）")
    st.markdown(
        """
### 棚卸の流れ

1. **棚卸開始** → 下のボタンで04の全SKUを書き出し
2. **実物カウント** → スプシまたはこのページでC列に実数を入力
3. **在庫に反映** → GASメニュー「📦 在庫操作」→「棚卸結果を在庫に反映」
4. **クリア** → 反映後シートは自動クリア
"""
    )

    if st.button("📋 棚卸シート準備（04の全SKUを書き出し）", type="primary"):
        with st.spinner("04のSKUを取得中..."):
            inv = sheets.load_inventory()
            master = sheets.load_master()
            if inv.empty:
                st.error("04_在庫管理が空")
                st.stop()

            # マスタから商品コード→小分類マップ
            small_map = {}
            if not master.empty and len(master.columns) > 4:
                for code, small in zip(master.iloc[:, 0].astype(str).str.strip(),
                                        master.iloc[:, 4].astype(str)):
                    if code:
                        small_map[code] = small

            rows = []
            for _, r in inv.iterrows():
                code = str(r.iloc[0]).strip()
                if not code:
                    continue
                small = small_map.get(code, "")
                rows.append([code, small, ""])

            new_df = pd.DataFrame(rows, columns=["商品コード", "小分類", "実カウント数"])

            with st.spinner(f"{len(new_df)}件 書込中..."):
                sheets.create_or_replace_sheet(SHEET_NAME, new_df)
            st.success(f"✅ {len(new_df)}件のSKUを棚卸シートに書出し")
            st.balloons()
            st.rerun()
    st.stop()

# データあり: 編集モード
st.metric("登録SKU数", f"{len(df):,}")

# 列の同定
CODE_COL = sheets.find_col(df, ["商品コード", "SKU"])
SMALL_COL = sheets.find_col(df, ["小分類"])
COUNT_COL = sheets.find_col(df, ["実カウント", "実数", "カウント"])

if not CODE_COL or not COUNT_COL:
    st.warning(f"列構造が想定と違います。列: {list(df.columns)}")
    st.dataframe(df, use_container_width=True, height=500, hide_index=True)
    st.stop()

# 数値変換
df[COUNT_COL] = pd.to_numeric(df[COUNT_COL], errors="coerce")
counted = df[df[COUNT_COL].notna()].shape[0]
st.metric("カウント済み", f"{counted} / {len(df)}")

# 検索 + 並び替え
col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
with col_s1:
    keyword = st.text_input("商品コード・小分類検索", "")
with col_s2:
    sort_options = [c for c in [CODE_COL, SMALL_COL, COUNT_COL] if c]
    sort_col = st.selectbox("並び替え列", sort_options, index=0)
with col_s3:
    sort_order = st.radio("順序", ["昇順", "降順"], horizontal=True)

filtered = df.copy()
if keyword:
    mask = filtered[CODE_COL].astype(str).str.contains(keyword, case=False, na=False)
    if SMALL_COL:
        mask |= filtered[SMALL_COL].astype(str).str.contains(keyword, case=False, na=False)
    filtered = filtered[mask]

# 並び替え（実カウント数は数値、他は文字列）
ascending = (sort_order == "昇順")
if sort_col == COUNT_COL:
    # NaNを最後に
    filtered = filtered.sort_values(sort_col, ascending=ascending, na_position="last")
else:
    filtered = filtered.sort_values(sort_col, ascending=ascending, na_position="last", key=lambda s: s.astype(str))

st.caption(f"表示中: {len(filtered):,} / {len(df):,} 件")

# column_config
col_cfg = {
    CODE_COL: st.column_config.TextColumn(disabled=True),
    COUNT_COL: st.column_config.NumberColumn(label="🟢 実カウント数", min_value=0, step=1),
}
if SMALL_COL:
    col_cfg[SMALL_COL] = st.column_config.TextColumn(disabled=True)

edited = st.data_editor(
    filtered,
    use_container_width=True,
    height=600,
    hide_index=True,
    num_rows="fixed",
    column_config=col_cfg,
    key="stocktaking_editor",
)

# 保存
st.markdown("---")
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    if st.button("💾 入力を保存", type="primary"):
        with st.spinner("書込中..."):
            sheets.replace_sheet_data(SHEET_NAME, edited, header_row=1, data_start_row=2)
        st.success("✅ 保存完了")
        st.balloons()

with col2:
    # D列に販売チャネルを追加してCSV出力
    export_df = df.copy()
    try:
        master_df = sheets.load_master()
        if not master_df.empty:
            m_code_col = master_df.columns[0]
            m_channel_col = master_df.columns[5] if len(master_df.columns) > 5 else None
            if m_channel_col is not None:
                code_to_channel = dict(zip(
                    master_df[m_code_col].astype(str).str.strip(),
                    master_df[m_channel_col].astype(str),
                ))
                # 棚卸シートのA列(商品コード)からチャネル取得
                first_col = export_df.columns[0]
                channels = export_df[first_col].astype(str).str.strip().map(code_to_channel).fillna("")
                # D列(index 3)に挿入
                if "販売チャネル" not in export_df.columns:
                    export_df.insert(min(3, len(export_df.columns)), "販売チャネル", channels)
                else:
                    export_df["販売チャネル"] = channels
    except Exception as e:
        st.caption(f"⚠ 販売チャネル取得失敗: {e}")

    csv_export = export_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 CSVエクスポート(全件)",
        csv_export,
        file_name=f"stocktaking_{len(export_df)}rows.csv",
        mime="text/csv",
    )

with col3:
    st.caption(
        "💡 入力後は下の **🚀 04に反映** で在庫(G列 月初在庫)に上書き"
    )

# ===========================================================
# 🚀 04_在庫管理 G列(月初在庫)に反映
# ===========================================================
st.markdown("---")
st.markdown("### 🚀 04_在庫管理に反映")
st.caption(
    "**実カウント数が入っている行のみ** を 04のG列(月初在庫)に上書きします。"
    " カウント空欄の行はスキップ。F列(自社倉庫)は 月初+入荷-廃棄-売上 で自動再計算されます。"
)

# 反映対象を試算
to_apply = df[df[COUNT_COL].notna()].copy()
preview_n = len(to_apply)

ac1, ac2 = st.columns([1, 3])
with ac1:
    st.metric("反映予定", f"{preview_n}件")
with ac2:
    if preview_n == 0:
        st.info("実カウント数が入っている行がないので反映できません。先に値を入れてください")

if preview_n > 0:
    st.warning(
        "⚠ **反映前に売上同期(GASの楽天/Amazon取得 or 10分sync)が完了していること**を確認してください。\n"
        "未同期の売上があると、後で同期されたタイミングで F列が余分に減ります。"
    )
    clear_after = st.checkbox(
        "✅ 反映後、棚卸シートをクリアする",
        value=True,
        help="2重反映を防ぐため、反映済みは消す",
        key="clear_after_apply",
    )
    if st.button(f"🚀 {preview_n}件を 04のG列(月初在庫)に逆算反映", type="primary", key="apply_to_inv"):
        with st.spinner("反映中..."):
            try:
                ss = sheets.get_spreadsheet()
                ws_inv = ss.worksheet("04_在庫管理")
                # 04 のA列→行番号マップ + I/J/N列値を取得
                # 月途中の棚卸でも正しく反映するため逆算式: G = count - I + J + N
                all_inv = ws_inv.get("A7:N2000", value_render_option="UNFORMATTED_VALUE")
                code_to_data = {}  # code → (row, I, J, N)
                for i, r in enumerate(all_inv, start=7):
                    if not r or not str(r[0] if len(r) > 0 else "").strip():
                        continue
                    code = str(r[0]).strip()

                    def _n(v):
                        try:
                            return float(v) if v not in (None, "") else 0
                        except (ValueError, TypeError):
                            return 0
                    i_val = _n(r[8] if len(r) > 8 else 0)   # I列(当月入荷)
                    j_val = _n(r[9] if len(r) > 9 else 0)   # J列(当月廃棄)
                    n_val = _n(r[13] if len(r) > 13 else 0)  # N列(当月販売数+コバリ消費)
                    code_to_data[code] = (i, i_val, j_val, n_val)

                requests = []
                matched, unmatched = [], []
                for _, r in to_apply.iterrows():
                    code = str(r[CODE_COL]).strip()
                    try:
                        count = int(float(r[COUNT_COL]))
                    except (ValueError, TypeError):
                        continue
                    if code in code_to_data:
                        ws_row, i_val, j_val, n_val = code_to_data[code]
                        # 逆算: G = count - I + J + N → F = G + I - J - N = count になる
                        g_new = int(count - i_val + j_val + n_val)
                        requests.append({"range": f"G{ws_row}", "values": [[g_new]]})
                        matched.append(code)
                    else:
                        unmatched.append(code)

                if requests:
                    sheets.safe_batch_update(ws_inv, requests, value_input_option="USER_ENTERED")
                    sheets._invalidate_one("04_在庫管理")

                st.success(
                    f"✅ {len(matched)}件を逆算してG列(月初在庫)に反映 → F列が実カウント数と一致"
                    + (f" / ⚠ 未マッチ {len(unmatched)}件" if unmatched else "")
                )
                if unmatched:
                    with st.expander(f"⚠ 04に存在しない商品コード {len(unmatched)}件"):
                        st.write(unmatched)

                # シートクリア
                if clear_after:
                    empty_df = pd.DataFrame(columns=df.columns)
                    sheets.replace_sheet_data(SHEET_NAME, empty_df, header_row=1, data_start_row=2)
                    st.info("🧹 棚卸シートをクリアしました")

                st.balloons()
                st.rerun()
            except Exception as e:
                st.error(f"反映失敗: {e}")
                import traceback
                st.code(traceback.format_exc())

# CSVインポート
st.markdown("---")
st.markdown("### 📤 CSVインポート（紙でカウント→PCで一括入力する用）")
st.caption("上のCSVエクスポートしたファイルにC列を入力 → ここでアップロード")

uploaded = st.file_uploader("CSV選択（同じ列構造）", type=["csv"], key="stocktaking_upload")
if uploaded:
    try:
        from io import StringIO
        content = uploaded.read().decode("utf-8-sig", errors="replace")
        new_df = pd.read_csv(StringIO(content), dtype=str).fillna("")
        st.success(f"✅ 読込: {len(new_df)}行 × {len(new_df.columns)}列")
        st.dataframe(new_df.head(10), use_container_width=True, hide_index=True)

        # 列マッピング確認
        if CODE_COL in new_df.columns and COUNT_COL in new_df.columns:
            st.info(f"列構造OK: {CODE_COL} / {COUNT_COL} あり")

            col_imp1, col_imp2 = st.columns([1, 3])
            with col_imp1:
                mode = st.radio("インポートモード", ["全置換", "C列のみ更新"], key="import_mode")
            with col_imp2:
                st.caption(
                    "**全置換**: スプシの内容をCSVで完全に上書き\n\n"
                    "**C列のみ更新**: 商品コード一致でC列(実カウント)だけ更新、他列は維持"
                )

            if st.button("📤 スプシに書込", type="primary", key="import_btn"):
                with st.spinner("書込中..."):
                    if mode == "全置換":
                        sheets.replace_sheet_data(SHEET_NAME, new_df, header_row=1, data_start_row=2)
                    else:
                        # C列のみ更新（商品コードでマッチ）
                        update_map = {}
                        for _, r in new_df.iterrows():
                            code = str(r[CODE_COL]).strip()
                            count = str(r[COUNT_COL]).strip()
                            if code:
                                update_map[code] = count
                        # 既存dfのC列を更新
                        df_updated = df.copy()
                        for idx in df_updated.index:
                            code = str(df_updated.at[idx, CODE_COL]).strip()
                            if code in update_map:
                                df_updated.at[idx, COUNT_COL] = update_map[code]
                        sheets.replace_sheet_data(SHEET_NAME, df_updated, header_row=1, data_start_row=2)
                st.success(f"✅ {len(new_df)}件インポート完了")
                st.balloons()
                st.rerun()
        else:
            st.error(
                f"列構造が違います。必要列: {CODE_COL}, {COUNT_COL}\n"
                f"CSV内の列: {list(new_df.columns)}"
            )
    except Exception as e:
        st.error(f"読込失敗: {e}")
