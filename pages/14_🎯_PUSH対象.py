"""
PUSH対象シート 編集ページ

機能:
- A列: 商品コード
- B列: 小分類（GAS自動補完）
- C列: 今すぐPUSH（チェックボックス）
- 実ヘッダ検出型なので列ズレ事故なし
- CSV取込 / テンプレートダウンロード
"""
from io import StringIO

import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="PUSH対象", page_icon="🎯", layout="wide")
st.title("🎯 PUSH対象（編集可）")
ui.sidebar_common()


# ===========================================================
# 🌐 全SKU自動PUSHモード ON/OFF
# ===========================================================
def _get_push_all_mode() -> str:
    """01_設定 から PUSH_ALL_MODE 値を読む"""
    try:
        ss = sheets.get_spreadsheet()
        ws = ss.worksheet("01_設定")
        all_v = ws.get_all_values()
        for i, r in enumerate(all_v, start=1):
            if r and "全SKU自動PUSH" in str(r[0] if len(r) > 0 else ""):
                return str(r[1] if len(r) > 1 else "OFF").strip().upper()
    except Exception:
        return "OFF"
    return "OFF"


def _set_push_all_mode(value: str) -> None:
    """01_設定 の PUSH_ALL_MODE 値を更新"""
    ss = sheets.get_spreadsheet()
    ws = ss.worksheet("01_設定")
    all_v = ws.get_all_values()
    for i, r in enumerate(all_v, start=1):
        if r and "全SKU自動PUSH" in str(r[0] if len(r) > 0 else ""):
            ws.update(
                range_name=f"B{i}", values=[[value]],
                value_input_option="USER_ENTERED",
            )
            return
    raise RuntimeError("01_設定 に '全SKU自動PUSHモード' 行が見つかりません")


with st.expander("🌐 全SKU自動PUSHモード ON/OFF", expanded=True):
    cur = _get_push_all_mode()
    is_on = cur == "ON"

    pc1, pc2 = st.columns([1, 3])
    with pc1:
        st.metric("現在の状態", "🟢 ON" if is_on else "⚪ OFF")
    with pc2:
        if is_on:
            st.success(
                "✅ **全SKU PUSH 中**: 04の全SKUが10分毎に楽天+Amazon FBM両方へ自動PUSH"
            )
        else:
            st.info(
                "⚪ **限定PUSH**: 「PUSH対象シート」のSKU + コバリ親子 + 売れたSKU のみが10分毎にPUSH"
            )

    if is_on:
        if st.button("⚪ OFFにする (限定PUSHに戻す)", key="push_mode_off",
                     use_container_width=True):
            try:
                _set_push_all_mode("OFF")
                st.success("✅ OFFにしました。次の10分毎トリガーから限定PUSHに戻ります")
                st.rerun()
            except Exception as e:
                st.error(f"切替失敗: {e}")
    else:
        if st.button("🟢 ONにする (全SKU自動PUSHを有効化)", type="primary",
                     key="push_mode_on", use_container_width=True):
            try:
                _set_push_all_mode("ON")
                st.success("✅ ONにしました。次の10分毎トリガーから全SKUがPUSHされます")
                st.balloons()
                st.rerun()
            except Exception as e:
                st.error(f"切替失敗: {e}")

    st.caption(
        "💡 GAS側 (`intervalIncrementalSync`) が この値を読んで動作を切替えます。"
        "GAS側はスクリプトプロパティ `PUSH_ALL_MODE` でも同じ動作可能(GASメニューで切替も可)"
    )

# ===========================================================
# 動作仕様（最初に必ず読む）
# ===========================================================
with st.expander("📌 このシートに入れたら自動でPUSHされる？(クリックして読む)", expanded=True):
    st.markdown(
        """
**結論: ✅ YES。商品コードを行に入れた時点で、次の自動PUSH（最大10分以内）に在庫が反映されます。**

### ⏰ タイミング
- GASトリガー **`intervalIncrementalSync`** が **10分毎** に走る
- そのときこのシートに居る SKU **すべて**（＋コバリ親子＋直近で売れたSKU）が PUSH対象になる
- ⇒ **ここに行を追加しただけで自動で楽天/Amazon FBMへ反映**される

### ☑️ 「今すぐPUSH」チェックボックスの意味
| シーン | チェックの効き方 |
|---|---|
| 自動PUSH（10分毎・このシートが拾う） | **無関係**。登録されたSKU全部が対象 |
| 在庫PUSH画面の「🎯 選択SKUだけPUSH」（手動） | チェック☑分のみ。0件なら全部 |

⇒ **自動PUSHだけ使う運用なら、チェックは触らなくてOK**

### 📡 PUSH先の決まり方
- **楽天**: マスタの **AE列(楽天SKU)** が出ていれば楽天RMSへ
- **Amazon FBM**: マスタの **AF列(FBM SKU)** が出ていれば Amazon SP-APIへ
- どちらも空なら A列(商品コード)で送信を試みる
- マスタにそもそもない商品コード → スキップ（ログに警告）

### ❓ よくある質問
- **何度もPUSHされる？** → 10分毎に毎回。在庫が変わってなければ実質ノーオペ
- **取り消したい** → 行を削除して保存すれば次回からPUSH対象外
- **PUSHが効いてない** → 33_📜 ログ履歴 で確認。429エラーは自動リトライ
- **大量に入れたら遅い？** → 1回のPUSHは数秒〜数十秒。10分間隔の中で完走する想定
"""
    )

SHEET_NAME = "PUSH対象"

with st.spinner("読み込み中..."):
    df = sheets.load_any_sheet(SHEET_NAME, header_row=1, data_start_row=2)

if df.empty:
    df = pd.DataFrame()

# 列検出
CODE_COL  = sheets.find_col(df, ["商品コード", "SKU", "コード"]) if not df.empty else None
SMALL_COL = sheets.find_col(df, ["小分類", "区分"]) if not df.empty else None
PUSH_COL  = sheets.find_col(df, ["今すぐPUSH", "PUSH", "チェック"]) if not df.empty else None

# 空シートならデフォルト
if df.empty or not CODE_COL:
    st.warning("⚠ 既存データなし or 商品コード列なし。デフォルト3列で初期化")
    CODE_COL, SMALL_COL, PUSH_COL = "商品コード", "小分類", "今すぐPUSH"
    df = pd.DataFrame(columns=[CODE_COL, SMALL_COL, PUSH_COL])

# チェックボックス列を bool に
if PUSH_COL and PUSH_COL in df.columns:
    df[PUSH_COL] = df[PUSH_COL].apply(
        lambda x: str(x).strip().upper() in ("TRUE", "1", "YES", "✓", "☑")
    )

with st.expander("🐛 デバッグ情報", expanded=False):
    st.caption(f"実ヘッダ: {list(df.columns) if not df.empty else '(空)'}")
    st.caption(
        f"検出列: 商品コード=`{CODE_COL}` / 小分類=`{SMALL_COL or '(なし)'}` / PUSH=`{PUSH_COL or '(なし)'}`"
    )

# サマリ
c1, c2, c3 = st.columns(3)
c1.metric("登録SKU数", f"{len(df):,}")
if PUSH_COL:
    c2.metric("PUSH予約", int(df[PUSH_COL].sum()))
    c3.metric("待機中", int((~df[PUSH_COL]).sum()))

st.markdown("---")

# 編集テーブル
st.markdown("### ✏️ 編集（行追加・削除・チェック切替）")
column_config = {}
if CODE_COL:
    column_config[CODE_COL] = st.column_config.TextColumn(required=True)
if SMALL_COL:
    column_config[SMALL_COL] = st.column_config.TextColumn(disabled=True, help="GAS側で自動補完")
if PUSH_COL:
    column_config[PUSH_COL] = st.column_config.CheckboxColumn()

edited = st.data_editor(
    df,
    use_container_width=True,
    height=500,
    hide_index=True,
    num_rows="dynamic",
    column_config=column_config,
    key="push_editor",
)

st.markdown("---")

# 保存
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    if st.button("💾 スプシに保存", type="primary"):
        with st.spinner("書込中..."):
            if CODE_COL and CODE_COL in edited.columns:
                to_save = edited[edited[CODE_COL].astype(str).str.strip() != ""].copy()
            else:
                to_save = edited.copy()
            # bool → "TRUE"/"FALSE"
            if PUSH_COL and PUSH_COL in to_save.columns:
                to_save[PUSH_COL] = to_save[PUSH_COL].map({True: "TRUE", False: "FALSE"})
            sheets.replace_sheet_data(SHEET_NAME, to_save, header_row=1, data_start_row=2)
        st.success(f"✅ {len(to_save)}件保存")

with col2:
    if st.button("🔄 再読込"):
        sheets.clear_all_caches()
        st.rerun()

with col3:
    st.caption("💡 保存後、GAS の `intervalIncrementalSync`（10分毎）が拾ってPUSH実行します")

st.markdown("---")
st.markdown("### 📥 CSV取込 / テンプレ")

# ----- テンプレダウンロード -----
template_df = pd.DataFrame([
    {"商品コード": "例: cameraholder2K", "今すぐPUSH": "TRUE"},
    {"商品コード": "例: 605",            "今すぐPUSH": "FALSE"},
])
template_csv = template_df.to_csv(index=False).encode("utf-8-sig")

dc1, dc2 = st.columns([1, 3])
with dc1:
    st.download_button(
        "📄 テンプレCSVダウンロード",
        template_csv,
        file_name="push_target_template.csv",
        mime="text/csv",
        use_container_width=True,
    )
with dc2:
    st.caption(
        "📝 列: `商品コード`(必須), `今すぐPUSH`(任意, TRUE/FALSE)。"
        "先頭0付きSKUは Excelで開くと0が落ちるので、メモ帳/VSCode 推奨"
    )

# ----- CSV取込 -----
upload_mode = st.radio(
    "取込モード",
    ["➕ 追加（既存にプラス）", "♻️ 置換（既存を全削除して入替）"],
    horizontal=True,
    key="push_upload_mode",
)

uploaded = st.file_uploader(
    "CSV / TSV / Excel ファイル",
    type=["csv", "tsv", "xlsx", "xls"],
    key="push_uploader",
)
pasted = st.text_area(
    "または貼り付け（タブ区切り or カンマ区切り）",
    height=120,
    key="push_paste",
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
    # 列マッピング: 商品コード列を特定
    code_candidates = [c for c in new_data.columns if any(
        kw in str(c) for kw in ["商品コード", "SKU", "コード", "product"]
    )]
    push_candidates = [c for c in new_data.columns if any(
        kw in str(c) for kw in ["PUSH", "プッシュ", "今すぐ", "対象"]
    )]

    mc1, mc2 = st.columns(2)
    with mc1:
        sel_code = st.selectbox(
            "商品コード列",
            options=list(new_data.columns),
            index=(list(new_data.columns).index(code_candidates[0])
                   if code_candidates else 0),
            key="push_csv_code",
        )
    with mc2:
        push_options = ["（無視・全部FALSE）"] + list(new_data.columns)
        sel_push = st.selectbox(
            "今すぐPUSH列（任意）",
            options=push_options,
            index=(push_options.index(push_candidates[0])
                   if push_candidates else 0),
            key="push_csv_push",
        )

    # マッピング後DF構築
    def _to_bool(v: str) -> bool:
        return str(v).strip().upper() in ("TRUE", "1", "YES", "✓", "☑", "ON", "Y")

    mapped = pd.DataFrame()
    mapped["商品コード"] = new_data[sel_code].astype(str).str.strip()
    if sel_push != "（無視・全部FALSE）":
        mapped["今すぐPUSH"] = new_data[sel_push].apply(_to_bool).map({True: "TRUE", False: "FALSE"})
    else:
        mapped["今すぐPUSH"] = "FALSE"
    # 空コード行除外
    mapped = mapped[mapped["商品コード"] != ""].reset_index(drop=True)

    st.markdown("**👀 マッピング後プレビュー（先頭10件）**")
    st.dataframe(mapped.head(10), use_container_width=True, hide_index=True)
    st.caption(f"取込予定: {len(mapped)}件 / 既存: {len(df)}件")

    if st.button("📤 取込実行", type="primary", use_container_width=True, key="push_csv_apply"):
        with st.spinner("書込中..."):
            try:
                if upload_mode.startswith("♻️"):
                    # 置換: マスタを mapped で完全置換
                    final_df = mapped[["商品コード", "今すぐPUSH"]].copy()
                    final_df.insert(1, "小分類", "")  # B列(GASが自動補完)
                    sheets.replace_sheet_data(SHEET_NAME, final_df, header_row=1, data_start_row=2)
                    st.success(f"✅ 置換完了: {len(final_df)}件")
                else:
                    # 追加: 既存に append。重複コードは警告のみ
                    existing_codes = (
                        set(df[CODE_COL].astype(str).str.strip().tolist())
                        if CODE_COL and CODE_COL in df.columns else set()
                    )
                    dup = [c for c in mapped["商品コード"] if c in existing_codes]
                    new_rows = mapped[~mapped["商品コード"].isin(existing_codes)]
                    if not new_rows.empty:
                        rows_2d = [[r["商品コード"], "", r["今すぐPUSH"]] for _, r in new_rows.iterrows()]
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

st.markdown("---")
with st.expander("ℹ️ 列ごとの仕様（参考）"):
    st.markdown(
        """
- **商品コード**: マスタA列の値。先頭0付き(例 `01GL1`)も保持される
- **小分類**: 入力不要。GASが自動補完
- **今すぐPUSH(チェック)**: 手動の「選択SKUだけPUSH」ボタン用。**自動PUSHには関係なし**

詳細フローは上の「📌 このシートに入れたら自動でPUSHされる？」を参照
"""
    )
