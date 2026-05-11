"""
レビュープレゼント 編集ページ

機能:
- 楽天の発送CSV/エクセルを貼り付け or アップロード → 一括追加
- マッピングプリセット保存（次回から1クリック適用）
- 1件ずつの手入力フォーム
- 既存データの編集・削除
"""
import json
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd
import streamlit as st

from lib import sheets, ui, inventory_ops

# プリセット保存先
PRESET_PATH = Path(__file__).parent.parent / ".streamlit" / "review_present_mapping.json"


def _load_preset():
    if PRESET_PATH.exists():
        try:
            return json.loads(PRESET_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_preset(mapping_dict):
    PRESET_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRESET_PATH.write_text(json.dumps(mapping_dict, ensure_ascii=False, indent=2), encoding="utf-8")

st.set_page_config(page_title="レビュープレゼント", page_icon="🎁", layout="wide")
st.title("🎁 レビュープレゼント（編集可）")

SHEET_NAME = "レビュープレゼント"
ui.sidebar_common(this_sheet=SHEET_NAME)

# ===========================================================
# 使い方（最初に必ず読む）
# ===========================================================
with st.expander("📌 レビュープレゼントとは？登録すると何が起こる？(クリックして読む)", expanded=True):
    st.markdown(
        """
**結論: 楽天レビュー記載特典として無償発送した商品を記録 → 在庫から自動で引かれる仕組み。**

### 🎯 登録するとどうなる？
- ⚡ 「**04に反映実行**」ボタンを押すと:
  - 04_在庫管理 の **J列(当月廃棄)** に個数を **加算**
  - 反映済みの行は **このシートから自動削除**（マスタにないSKUのみ警告表示で残る）
- 当月廃棄に入る = **販売可能在庫から減る** = ステータス計算・推奨発注に反映

### 📝 登録方法
1. **CSV取込タブ**: 楽天の発送CSVをそのまま貼り付け／アップロード
   - 列マッピング後、**プリセット保存**で次回から1クリック適用
2. **1件追加タブ**: 手動でSKU+個数+注文番号
3. **編集・削除タブ**: 既存行をテーブルで直接編集

### 🔄 反映後の動き
- 「⚡ 04に反映」 → J列加算 → このシートから該当行削除
- マスタに無いSKUは**残ったまま警告表示**（マスタ追加 or 行削除で対処）

### 📋 列の意味
- **商品管理番号 / 商品コード / SKU**: マスタA列の値（必須）
- **個数**: 何個プレゼントしたか（必須）
- **注文番号**: 任意（重複防止のキー）
"""
    )

with st.spinner("読み込み中..."):
    df = sheets.load_any_sheet(SHEET_NAME, header_row=1, data_start_row=2)

if df.empty:
    df = pd.DataFrame()

# 主要列の検出（任意・あれば使う）
CODE_COL  = sheets.find_col(df, ["商品管理番号", "SKU管理番号", "商品コード", "SKU"]) if not df.empty else None
QTY_COL   = sheets.find_col(df, ["個数", "数量"]) if not df.empty else None
ORDER_COL = sheets.find_col(df, ["注文番号"]) if not df.empty else None

with st.expander("🐛 デバッグ情報", expanded=False):
    st.caption(f"実ヘッダ ({len(df.columns)}列): {list(df.columns) if not df.empty else '(空)'}")
    st.caption(
        f"検出列: 商品管理番号=`{CODE_COL or '(なし)'}` / 個数=`{QTY_COL or '(なし)'}` / 注文番号=`{ORDER_COL or '(なし)'}`"
    )

st.metric("登録件数", f"{len(df):,}")

# ===========================================================
# 🚀 楽天 Send_List CSV → 一発取込 + 04反映
# ===========================================================
st.markdown("---")
st.markdown("### 🚀 楽天 Send_List CSV を一発で処理")
st.caption(
    "楽天RMSの「おまけ送付リスト」CSVをアップ → \n"
    "「おまけ商品」列をSKU、数量1、発送日=今日 として登録 → 04のJ列(廃棄)に即反映します"
)


def _decode_smart_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace"), "utf-8-sig"
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace"), "cp932(force)"


send_list = st.file_uploader(
    "📁 Send_List_*.csv",
    type=["csv"],
    key="send_list_oneshot_uploader",
)

if send_list is not None:
    try:
        raw = send_list.read()
        content, used_enc = _decode_smart_bytes(raw)
        sl_df = pd.read_csv(StringIO(content), dtype=str).fillna("")
        st.success(f"✅ 読込: {len(sl_df)}行 / encoding={used_enc}")

        # 「おまけ商品」列を探す
        omake_col = None
        for c in sl_df.columns:
            if "おまけ" in str(c) or "プレゼント" in str(c) or "ノベルティ" in str(c):
                omake_col = c
                break
        if omake_col is None:
            st.error(
                f"⚠ 「おまけ商品」列が見つかりません。CSVヘッダ: {list(sl_df.columns)}\n"
                "下の通常CSV取込から手動マッピングしてください"
            )
        else:
            st.caption(f"検出: SKU列 = `{omake_col}` / 数量=1固定 / 発送日={date.today():%Y-%m-%d}")
            # SKU を抽出 (空欄行は除外)
            skus = [s.strip() for s in sl_df[omake_col].astype(str).tolist() if s.strip()]
            if not skus:
                st.warning("おまけ商品列が全部空でした")
            else:
                # 集計プレビュー: SKU → 件数
                from collections import Counter
                sku_count = Counter(skus)
                preview_df = pd.DataFrame(
                    [(s, c) for s, c in sku_count.most_common()],
                    columns=["SKU(おまけ商品)", "登録件数"],
                )
                st.dataframe(preview_df, use_container_width=True, hide_index=True, height=250)
                st.caption(f"合計 {len(skus)} 件 / ユニークSKU {len(sku_count)} 種")

                if st.button(
                    f"🎁 {len(skus)}件 を レビューシート登録 + 04反映",
                    type="primary",
                    key="oneshot_apply_btn",
                ):
                    with st.spinner("登録 → 04反映 中..."):
                        # 1) レビューシートに append (3列: SKU, 数量, 発送日)
                        today_str = date.today().strftime("%Y-%m-%d")
                        rows_to_add = [[s, 1, today_str] for s in skus]
                        # シートのヘッダに合わせる
                        if not df.empty:
                            normalized = []
                            for s in skus:
                                vmap = {df.columns[0]: s}
                                if len(df.columns) > 1:
                                    vmap[df.columns[1]] = 1
                                if len(df.columns) > 2:
                                    vmap[df.columns[2]] = today_str
                                normalized.append(sheets.build_row_by_header(df.columns, vmap))
                            rows_to_add = normalized
                        sheets.append_rows(SHEET_NAME, rows_to_add)
                        st.success(f"✅ レビューシートに {len(rows_to_add)} 件 追加")

                        # 2) 04に即反映
                        try:
                            result = inventory_ops.apply_review_present()
                            st.success(
                                f"✅ 04反映完了\n\n"
                                f"- J列(廃棄)に加算: {result['processed']}件\n"
                                f"- マスタにないSKU(残存): {result['remaining']}件"
                            )
                            if result.get("not_found"):
                                with st.expander(f"⚠ マスタ未登録SKU {len(result['not_found'])}件"):
                                    st.write(result["not_found"])
                            st.balloons()
                        except Exception as e:
                            st.error(f"04反映失敗: {e}")
    except Exception as e:
        st.error(f"処理失敗: {e}")
        import traceback
        st.code(traceback.format_exc())

# ===========================================================
# 🚀 04_在庫管理に反映（Python版・GAS不要）
# ===========================================================
st.markdown("---")
st.markdown("### 🚀 04_在庫管理に反映")
st.caption(
    "登録済みのSKUを 04_在庫管理 のJ列(当月廃棄)に加算 → 反映済み行を自動削除\n"
    "（マスタにないSKUは残す）"
)

col_btn, col_msg = st.columns([1, 3])
with col_btn:
    if st.button("⚡ 04に反映実行", type="primary", key="apply_to_inv"):
        with st.spinner("処理中..."):
            try:
                result = inventory_ops.apply_review_present()
            except Exception as e:
                st.error(f"反映失敗: {e}")
                result = None

        if result:
            st.success(
                f"✅ 反映完了\n\n"
                f"- 処理件数: {result['processed']}件\n"
                f"- マスタにないSKU(残存): {result['remaining']}件\n"
                f"- 元の総行数: {result['total']}件"
            )
            if result["not_found"]:
                with st.expander(f"⚠ マスタにないSKU ({len(result['not_found'])}件)"):
                    st.write(result["not_found"])
            st.balloons()

with col_msg:
    st.caption(
        "💡 GASメニューを使わずにこのボタンだけで完結。\n"
        "実行後、レビュープレゼントシートと04_在庫管理が同期されます"
    )

# ===========================================================
# クイック追加（常時表示・連続入力用）
# ===========================================================
st.markdown("---")
st.markdown("### ⚡ クイック追加（連続入力）")
st.caption("商品コード入れて Enter → 追加 → 次のコードへ。最後に上の「⚡ 04に反映実行」を押す")

QUICK_CODE_COL = CODE_COL or "商品管理番号"
QUICK_QTY_COL = QTY_COL or "個数"

# 入力フィールドを毎回新規ウィジェットで作るためのカウンタ
if "input_counter" not in st.session_state:
    st.session_state["input_counter"] = 0

ic = st.session_state["input_counter"]
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    quick_code = st.text_input("商品コード", "", key=f"quick_code_{ic}")
with c2:
    quick_qty = st.number_input("個数", min_value=1, value=1, step=1, key=f"quick_qty_{ic}")
with c3:
    st.markdown("<br>", unsafe_allow_html=True)
    add_clicked = st.button("➕ 追加", type="primary", use_container_width=True, key=f"add_btn_{ic}")

if add_clicked and quick_code.strip():
    code_value = quick_code.strip()
    qty_value = int(quick_qty)
    if df.empty:
        new_row = [code_value, qty_value]
        sheets.append_rows(SHEET_NAME, [new_row])
    else:
        value_map = {QUICK_CODE_COL: code_value}
        if QTY_COL:
            value_map[QTY_COL] = qty_value
        new_row = sheets.build_row_by_header(df.columns, value_map)
        sheets.append_rows(SHEET_NAME, [new_row])
    # 履歴
    if "added_history" not in st.session_state:
        st.session_state["added_history"] = []
    st.session_state["added_history"].append(f"{code_value} × {qty_value}")
    # 次の入力のためカウンタを進める（widgetが新規になり値が空に戻る）
    st.session_state["input_counter"] += 1
    st.rerun()

# セッション履歴の表示
if st.session_state.get("added_history"):
    history = st.session_state["added_history"]
    with st.container():
        col_h1, col_h2 = st.columns([5, 1])
        with col_h1:
            st.success(f"✅ 今セッションで追加 {len(history)} 件:")
            for i, h in enumerate(reversed(history), 1):
                st.markdown(f"  {i}. **{h}**")
        with col_h2:
            if st.button("履歴クリア", key="clear_history"):
                st.session_state["added_history"] = []
                st.rerun()

# ===========================================================
# Tab で補助機能
# ===========================================================
tab1, tab3 = st.tabs(["📥 CSV/エクセル一括追加", "✏️ 編集・削除"])

# -----------------------------------------------------------
# Tab 1: CSV/エクセル一括追加
# -----------------------------------------------------------
with tab1:
    st.subheader("CSV/エクセルファイルから一括追加")
    st.caption("楽天の発送CSV等を取り込み、既存シートの末尾に追加")

    has_header = st.checkbox(
        "✅ CSV/貼り付けの 1行目はヘッダ",
        value=False,
        help="OFFの場合、既存シートの列順で位置ベースで追加します",
    )

    uploaded = st.file_uploader(
        "ファイル選択（.csv / .tsv / .xlsx）",
        type=["csv", "tsv", "xlsx", "xls"],
    )

    pasted = st.text_area(
        "またはここに貼り付け（タブ or カンマ区切り）",
        height=150,
        placeholder="414562-...\t熊野\t征浩\t918\t...",
    )

    new_data = None
    read_kwargs = dict(dtype=str, header=0 if has_header else None)

    def _decode_smart(raw: bytes) -> tuple[str, str]:
        """楽天RMS等のCSVは cp932(Shift_JIS) が多い。複数エンコーディングを試す。
        戻り値: (decoded_text, used_encoding)
        """
        # BOM があれば utf-8-sig が安全
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw.decode("utf-8-sig", errors="replace"), "utf-8-sig"
        # UTF-16 BOM
        if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
            return raw.decode("utf-16", errors="replace"), "utf-16"
        # 各エンコーディングで試して、文字化けが少ない方を採用
        candidates = ["utf-8", "cp932", "shift_jis", "euc-jp"]
        best = None
        for enc in candidates:
            try:
                txt = raw.decode(enc)
                # 完全成功
                return txt, enc
            except UnicodeDecodeError:
                continue
        # 全部失敗 → cp932 で強制 (楽天系が圧倒的に多いので)
        return raw.decode("cp932", errors="replace"), "cp932(force)"

    if uploaded is not None:
        try:
            if uploaded.name.endswith(".xlsx") or uploaded.name.endswith(".xls"):
                new_data = pd.read_excel(uploaded, **read_kwargs).fillna("")
                used_enc = "xlsx"
            else:
                raw = uploaded.read()
                content, used_enc = _decode_smart(raw)
                first_line = content.split("\n")[0] if content else ""
                sep = "\t" if first_line.count("\t") > first_line.count(",") else ","
                new_data = pd.read_csv(StringIO(content), sep=sep, **read_kwargs).fillna("")
            st.success(f"✅ ファイル読み込み: {len(new_data)}行 × {len(new_data.columns)}列  (encoding={used_enc})")
        except Exception as e:
            st.error(f"ファイル読み込み失敗: {e}")

    elif pasted.strip():
        try:
            sep = "\t" if pasted.split("\n")[0].count("\t") > pasted.split("\n")[0].count(",") else ","
            new_data = pd.read_csv(StringIO(pasted), sep=sep, **read_kwargs).fillna("")
            st.success(f"✅ 貼り付け解析: {len(new_data)}行 × {len(new_data.columns)}列")
        except Exception as e:
            st.error(f"パース失敗: {e}")

    # ヘッダなしモードの場合、CSV列に「位置1」「位置2」...という名前をつける
    if new_data is not None and not has_header:
        new_data.columns = [f"位置{i+1}" for i in range(len(new_data.columns))]

    if new_data is not None and not new_data.empty:
        # プレビュー
        st.markdown("**📋 CSVプレビュー（先頭5行）**")
        st.dataframe(new_data.head(), use_container_width=True, hide_index=True)

        # ===========================
        # 列マッピングUI（CSV → シート）
        # ===========================
        if not df.empty:
            st.markdown("---")
            st.markdown("### 🔗 列マッピング: シート列 ← CSV列を選択")

            preset = _load_preset()
            TODAY_OPTION = "📅 今日の日付（自動）"
            csv_options = ["（空欄/手入力）", TODAY_OPTION] + list(new_data.columns)
            mapping = {}

            # プリセット適用ボタン
            cprev, cpres, _ = st.columns([1, 1, 2])
            with cprev:
                if st.button("📂 プリセット適用", help="前回保存したマッピングを呼び出す"):
                    for sc, val in preset.items():
                        if isinstance(val, dict):
                            st.session_state[f"map_{sc}"] = val.get("source", "（空欄/手入力）")
                            if val.get("source") == "（空欄/手入力）":
                                st.session_state[f"default_{sc}"] = val.get("default", "")
                    st.rerun()

            # シート列ごとに「どのCSV列から取るか」のドロップダウン
            for sheet_col in df.columns:
                # 自動推定 or プリセットからの初期値
                preset_source = preset.get(sheet_col, {}).get("source") if isinstance(preset.get(sheet_col), dict) else None
                default_idx = 0
                if preset_source and preset_source in csv_options:
                    default_idx = csv_options.index(preset_source)
                else:
                    # 「発送日」「日付」を含むシート列は今日の日付を自動推定
                    if any(k in str(sheet_col) for k in ["発送日", "日付", "Date"]):
                        default_idx = csv_options.index(TODAY_OPTION)
                    else:
                        for i, csv_col in enumerate(new_data.columns):
                            if sheet_col == csv_col or sheet_col in str(csv_col) or str(csv_col) in sheet_col:
                                default_idx = i + 2  # offset (空欄+今日)
                                break

                cols = st.columns([2, 3, 2])
                with cols[0]:
                    st.caption(f"📌 **{sheet_col}**")
                with cols[1]:
                    chosen = st.selectbox(
                        f"{sheet_col} のソース",
                        csv_options,
                        index=default_idx,
                        key=f"map_{sheet_col}",
                        label_visibility="collapsed",
                    )
                with cols[2]:
                    default_value = ""
                    if chosen == "（空欄/手入力）":
                        preset_default = preset.get(sheet_col, {}).get("default", "") if isinstance(preset.get(sheet_col), dict) else ""
                        default_value = st.text_input(
                            f"{sheet_col} の固定値",
                            preset_default,
                            key=f"default_{sheet_col}",
                            label_visibility="collapsed",
                            placeholder="（空欄）or 固定値",
                        )
                    elif chosen == TODAY_OPTION:
                        st.caption(f"→ {date.today().strftime('%Y-%m-%d')}")
                mapping[sheet_col] = (chosen, default_value if chosen == "（空欄/手入力）" else None)

            # マッピング後のプレビュー
            today_str = date.today().strftime("%Y-%m-%d")
            mapped_rows = []
            for _, row in new_data.iterrows():
                new_row_dict = {}
                for sheet_col, (csv_src, default_val) in mapping.items():
                    if csv_src == "（空欄/手入力）":
                        new_row_dict[sheet_col] = default_val or ""
                    elif csv_src == TODAY_OPTION:
                        new_row_dict[sheet_col] = today_str
                    else:
                        new_row_dict[sheet_col] = row[csv_src]
                mapped_rows.append(new_row_dict)
            mapped_df = pd.DataFrame(mapped_rows, columns=list(df.columns))

            st.markdown("**👀 マッピング後のプレビュー（先頭5行）**")
            st.dataframe(mapped_df.head(), use_container_width=True, hide_index=True)

            # 追加実行
            col1, col2 = st.columns([1, 3])
            with col1:
                if st.button("📤 既存シートに追加", type="primary", key="bulk_append"):
                    with st.spinner("追加中..."):
                        rows_to_append = mapped_df.fillna("").astype(str).values.tolist()
                        sheets.append_rows(SHEET_NAME, rows_to_append)
                    st.success(f"✅ {len(mapped_df)}件を追加しました")
                    st.rerun()
            with col2:
                st.caption("マッピング設定を確認 → ボタンで追加")
        else:
            # シート空: そのまま全列を新規シートに書く
            st.info("既存シートが空なので、CSVをそのままシートにします")
            if st.button("📤 シートに書込", type="primary"):
                sheets.create_or_replace_sheet(SHEET_NAME, new_data)
                st.success(f"✅ {len(new_data)}件をシート化")
                st.rerun()

# -----------------------------------------------------------
# Tab 3: 編集・削除
# -----------------------------------------------------------
with tab3:
    st.subheader("既存データの編集・削除")
    st.caption("行を直接編集 or 削除して「保存」")

    if df.empty:
        st.info("データなし")
    else:
        edited = st.data_editor(
            df,
            use_container_width=True,
            height=500,
            hide_index=True,
            num_rows="dynamic",
            key="review_editor",
        )

        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("💾 スプシに保存", type="primary"):
                with st.spinner("書込中..."):
                    if CODE_COL and CODE_COL in edited.columns:
                        to_save = edited[edited[CODE_COL].astype(str).str.strip() != ""]
                    else:
                        to_save = edited
                    sheets.replace_sheet_data(
                        SHEET_NAME, to_save, header_row=1, data_start_row=2
                    )
                st.success(f"✅ {len(to_save)}件保存")
        with col2:
            if st.button("🔄 再読込"):
                sheets.clear_all_caches()
                st.rerun()
