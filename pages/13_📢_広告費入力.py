"""
広告費入力 編集ページ（実ヘッダ検出型）

GAS仕様の7列構成を想定するが、実シートのヘッダを検出して柔軟に対応
"""
import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="広告費入力", page_icon="📢", layout="wide")
st.title("📢 広告費入力（編集可）")
st.caption("月×チャネル別の広告費・アフィリエイト費を管理。15_サマリで自動参照")
ui.sidebar_common()

SHEET_NAME = "広告費入力"

with st.spinner("読み込み中..."):
    df = sheets.load_any_sheet(SHEET_NAME, header_row=1, data_start_row=2)

if df.empty:
    df = pd.DataFrame()

MONTH_COL    = sheets.find_col(df, ["月", "Month"]) if not df.empty else None
CHANNEL_COL  = sheets.find_col(df, ["チャネル", "モール"]) if not df.empty else None
AD_NET_COL   = sheets.find_col(df, ["広告(税抜)", "広告税抜", "広告費(税抜)"]) if not df.empty else None
AD_INC_COL   = sheets.find_col(df, ["広告(税込)", "広告税込", "広告費(税込)"]) if not df.empty else None
AFF_NET_COL  = sheets.find_col(df, ["アフィリ(税抜)", "アフィリエイト(税抜)"]) if not df.empty else None
AFF_INC_COL  = sheets.find_col(df, ["アフィリ(手数料込)", "アフィリエイト(手数料込)"]) if not df.empty else None
MEMO_COL     = sheets.find_col(df, ["備考", "メモ"]) if not df.empty else None

if df.empty or not MONTH_COL:
    st.warning("⚠ 既存データなし or 月列なし。デフォルト7列で初期化")
    MONTH_COL, CHANNEL_COL = "月", "チャネル"
    AD_NET_COL, AD_INC_COL = "広告(税抜)", "広告(税込)"
    AFF_NET_COL, AFF_INC_COL = "アフィリ(税抜)", "アフィリ(手数料込)"
    MEMO_COL = "備考"
    df = pd.DataFrame(columns=[
        MONTH_COL, CHANNEL_COL, AD_NET_COL, AD_INC_COL,
        AFF_NET_COL, AFF_INC_COL, MEMO_COL
    ])

with st.expander("🐛 デバッグ情報", expanded=False):
    st.caption(f"実ヘッダ: {list(df.columns) if not df.empty else '(空)'}")
    st.caption(
        f"検出列: 月=`{MONTH_COL}` / チャネル=`{CHANNEL_COL or '(なし)'}` / "
        f"広告税抜=`{AD_NET_COL or '(なし)'}` / アフィリ税抜=`{AFF_NET_COL or '(なし)'}`"
    )

# 数値変換
for c in [AD_NET_COL, AD_INC_COL, AFF_NET_COL, AFF_INC_COL]:
    if c and c in df.columns:
        df[c] = pd.to_numeric(
            df[c].astype(str).str.replace(",", ""), errors="coerce"
        ).fillna(0)

# 入力時点でD/F列を計算して表示（編集後の自動保存でスプシ反映）
if AD_NET_COL and AD_INC_COL and AD_NET_COL in df.columns:
    df[AD_INC_COL] = (pd.to_numeric(df[AD_NET_COL], errors="coerce").fillna(0) * 1.1).round(0)
if AFF_NET_COL and AFF_INC_COL and AFF_NET_COL in df.columns:
    df[AFF_INC_COL] = (pd.to_numeric(df[AFF_NET_COL], errors="coerce").fillna(0) * 1.3).round(0)

st.metric("登録行数", f"{len(df):,}")

st.info(
    "💡 **広告(税抜)→税込 は ×1.1**、**アフィリ(税抜)→手数料込 は ×1.3** で自動計算。"
    "編集→Enter で即スプシに反映されます。"
)


# ===========================================================
# タブ分割: 🏪 楽天 (アフィリあり) / 📦 Amazon (アフィリなし)
# ===========================================================
RAKUTEN_CHANNELS = ["楽天"]
AMAZON_CHANNELS = ["Amazon FBA", "Amazon"]

# チャネル別にdfを分割
if CHANNEL_COL and CHANNEL_COL in df.columns:
    rakuten_df = df[df[CHANNEL_COL].isin(RAKUTEN_CHANNELS)].reset_index(drop=True).copy()
    amazon_df = df[df[CHANNEL_COL].isin(AMAZON_CHANNELS)].reset_index(drop=True).copy()
    other_df = df[~df[CHANNEL_COL].isin(RAKUTEN_CHANNELS + AMAZON_CHANNELS)].reset_index(drop=True).copy()
else:
    rakuten_df = df.copy()
    amazon_df = df.iloc[0:0].copy()
    other_df = df.iloc[0:0].copy()


def _merge_and_save(updated_subset: pd.DataFrame, channels_handled: list[str]):
    """指定チャネルのrowsだけ更新してシート全体を保存。他チャネル/その他は保持"""
    keep = df[~df[CHANNEL_COL].isin(channels_handled)] if CHANNEL_COL in df.columns else df.iloc[0:0]
    combined = pd.concat([keep, updated_subset], ignore_index=True)
    # 税抜→税込/手数料込 一括再計算
    if AD_NET_COL and AD_INC_COL and AD_NET_COL in combined.columns:
        combined[AD_INC_COL] = (pd.to_numeric(combined[AD_NET_COL], errors="coerce").fillna(0) * 1.1).round(0)
    if AFF_NET_COL and AFF_INC_COL and AFF_NET_COL in combined.columns:
        combined[AFF_INC_COL] = (pd.to_numeric(combined[AFF_NET_COL], errors="coerce").fillna(0) * 1.3).round(0)
    # 月空行除外
    if MONTH_COL and MONTH_COL in combined.columns:
        combined = combined[combined[MONTH_COL].astype(str).str.strip() != ""]
    sheets.replace_sheet_data(SHEET_NAME, combined, header_row=1, data_start_row=2)
    sheets._invalidate_one(SHEET_NAME)
    return len(combined)


tab_rk, tab_am = st.tabs([
    f"🏪 楽天({len(rakuten_df)}件) — 広告 + アフィリ",
    f"📦 Amazon({len(amazon_df)}件) — 広告のみ",
])

# ----------- 楽天タブ -----------
with tab_rk:
    cc_rk = {}
    if MONTH_COL:
        cc_rk[MONTH_COL] = st.column_config.TextColumn(help="例: 2026-04")
    if CHANNEL_COL:
        cc_rk[CHANNEL_COL] = st.column_config.SelectboxColumn(options=RAKUTEN_CHANNELS, default="楽天")
    if AD_NET_COL:
        cc_rk[AD_NET_COL] = st.column_config.NumberColumn(label=f"🟢 {AD_NET_COL}", min_value=0, step=100, format="¥%d")
    if AD_INC_COL:
        cc_rk[AD_INC_COL] = st.column_config.NumberColumn(label=f"🔒 {AD_INC_COL}(×1.1)", disabled=True, format="¥%d")
    if AFF_NET_COL:
        cc_rk[AFF_NET_COL] = st.column_config.NumberColumn(label=f"🟢 {AFF_NET_COL}", min_value=0, step=100, format="¥%d")
    if AFF_INC_COL:
        cc_rk[AFF_INC_COL] = st.column_config.NumberColumn(label=f"🔒 {AFF_INC_COL}(×1.3)", disabled=True, format="¥%d")
    if MEMO_COL:
        cc_rk[MEMO_COL] = st.column_config.TextColumn()

    edited_rk = st.data_editor(
        rakuten_df, use_container_width=True, height=400,
        hide_index=True, num_rows="dynamic",
        column_config=cc_rk, key="ad_editor_rk",
    )
    state_rk = st.session_state.get("ad_editor_rk", {})
    if state_rk.get("edited_rows") or state_rk.get("added_rows") or state_rk.get("deleted_rows"):
        try:
            # 新規行のチャネル空欄を「楽天」に補完
            if CHANNEL_COL in edited_rk.columns:
                edited_rk[CHANNEL_COL] = edited_rk[CHANNEL_COL].replace("", "楽天").fillna("楽天")
            n = _merge_and_save(edited_rk, RAKUTEN_CHANNELS)
            st.toast(f"💾 楽天 自動保存(全{n}件)", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"❌ 楽天 保存失敗: {e}")
    else:
        st.caption("✅ 変更なし(編集→Enterで自動保存)")

# ----------- Amazonタブ -----------
with tab_am:
    # アフィリ列を非表示（Amazonには無い）
    amazon_visible_cols = [c for c in [MONTH_COL, CHANNEL_COL, AD_NET_COL, AD_INC_COL, MEMO_COL] if c]
    amazon_display = amazon_df[amazon_visible_cols].copy() if all(c in amazon_df.columns for c in amazon_visible_cols) else amazon_df.copy()

    cc_am = {}
    if MONTH_COL:
        cc_am[MONTH_COL] = st.column_config.TextColumn(help="例: 2026-04")
    if CHANNEL_COL:
        cc_am[CHANNEL_COL] = st.column_config.SelectboxColumn(options=AMAZON_CHANNELS, default="Amazon FBA")
    if AD_NET_COL:
        cc_am[AD_NET_COL] = st.column_config.NumberColumn(label=f"🟢 {AD_NET_COL}", min_value=0, step=100, format="¥%d")
    if AD_INC_COL:
        cc_am[AD_INC_COL] = st.column_config.NumberColumn(label=f"🔒 {AD_INC_COL}(×1.1)", disabled=True, format="¥%d")
    if MEMO_COL:
        cc_am[MEMO_COL] = st.column_config.TextColumn()

    edited_am = st.data_editor(
        amazon_display, use_container_width=True, height=400,
        hide_index=True, num_rows="dynamic",
        column_config=cc_am, key="ad_editor_am",
    )
    state_am = st.session_state.get("ad_editor_am", {})
    if state_am.get("edited_rows") or state_am.get("added_rows") or state_am.get("deleted_rows"):
        try:
            # 編集後のAmazon dfに アフィリ列を 0 で復元
            full_amazon = edited_am.copy()
            if AFF_NET_COL:
                full_amazon[AFF_NET_COL] = 0
            if AFF_INC_COL:
                full_amazon[AFF_INC_COL] = 0
            # チャネル空欄補完
            if CHANNEL_COL in full_amazon.columns:
                full_amazon[CHANNEL_COL] = full_amazon[CHANNEL_COL].replace("", "Amazon FBA").fillna("Amazon FBA")
            # 列順をオリジナルに揃える
            full_amazon = full_amazon[[c for c in df.columns if c in full_amazon.columns]]
            n = _merge_and_save(full_amazon, AMAZON_CHANNELS)
            st.toast(f"💾 Amazon 自動保存(全{n}件)", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Amazon 保存失敗: {e}")
    else:
        st.caption("✅ 変更なし(編集→Enterで自動保存)")

if not other_df.empty:
    with st.expander(f"⚠ その他チャネル({len(other_df)}件) — `{', '.join(other_df[CHANNEL_COL].unique())}`"):
        st.caption("楽天 / Amazon FBA / Amazon 以外のチャネル名が入ってる行。スプシで直接修正推奨")
        st.dataframe(other_df, use_container_width=True, hide_index=True)

st.markdown("---")
if st.button("🔄 再読込"):
    sheets.clear_all_caches()
    st.rerun()
