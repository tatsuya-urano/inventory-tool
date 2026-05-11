"""
03_商品マスタ参照 編集ページ — サイドカード版

仕様:
- メイン: 編集テーブル（スクロール位置保持）
- 右サイド: 編集中の行の利益額・利益率をリアルタイム表示
- 「💾 確定保存」で全変更を一括スプシに書込
- L/M列はスプシ保存対象外（既存数式を保護）
"""
import pandas as pd
import streamlit as st

from lib import sheets, ui, pool_inventory, user_prefs

st.set_page_config(page_title="商品マスタ", page_icon="📦", layout="wide")
st.title("📦 03_商品マスタ参照（編集可）")
ui.sidebar_common(this_sheet="03_商品マスタ参照")

SHEET_NAME = "03_商品マスタ参照"

COL_CODE      = 0
COL_TITLE     = 1
COL_SMALL_CAT = 4
COL_CHANNEL   = 5
COL_COST      = 7
COL_FEE       = 8
COL_SHIP      = 9
COL_PRICE     = 10
COL_PROFIT    = 11
COL_RATE      = 12
COL_SUPPLIER  = 13
COL_AC        = 28  # 手動原価（編集禁止・保護）
COL_AD        = 29  # 当月販売数（数式・編集禁止）
COL_AE        = 30  # Amazon SKU（編集可）
COL_AF        = 31  # 楽天/FBM SKU等（拡張用、編集可）
COL_AG        = 32  # FBA SKU（拡張用、編集可）
DISPLAY_LIMIT = 33  # AG列まで表示
PROTECTED_COLS = {COL_PROFIT, COL_RATE, COL_COST, COL_AD}  # 編集不可（H列は数式・入荷時コバリ原価で使用）
EDITABLE_NUMERIC = {COL_AC, COL_FEE, COL_SHIP, COL_PRICE}  # ACは手動原価（ユーザー編集）

def to_num(v):
    if v is None or v == "":
        return 0.0
    try:
        s = str(v).replace(",", "").replace("¥", "").replace("%", "").strip()
        return float(s) if s else 0.0
    except (ValueError, TypeError):
        return 0.0

def calc_profit_rate(cost, fee, ship, price):
    price = to_num(price); cost = to_num(cost); fee = to_num(fee); ship = to_num(ship)
    if price == 0:
        return 0.0, 0.0
    fee_amount = price * fee if fee < 1 else fee
    profit = price - cost - fee_amount - ship
    return profit, profit / price

# ===========================================================
with st.spinner("読込中..."):
    df_full = sheets.load_master()
if df_full.empty:
    st.error("マスタなし"); st.stop()

df = df_full.iloc[:, :DISPLAY_LIMIT].copy()
for idx in [COL_COST, COL_FEE, COL_SHIP, COL_PRICE, COL_AC]:
    if idx < len(df.columns):
        df.iloc[:, idx] = df.iloc[:, idx].apply(to_num)

# 初期計算
profits, rates = [], []
for _, row in df.iterrows():
    p, r = calc_profit_rate(
        row.iloc[COL_COST] if len(row) > COL_COST else 0,
        row.iloc[COL_FEE] if len(row) > COL_FEE else 0,
        row.iloc[COL_SHIP] if len(row) > COL_SHIP else 0,
        row.iloc[COL_PRICE] if len(row) > COL_PRICE else 0,
    )
    profits.append(p); rates.append(r * 100)
if COL_PROFIT < len(df.columns): df.iloc[:, COL_PROFIT] = profits
if COL_RATE < len(df.columns): df.iloc[:, COL_RATE] = rates

c1, c2, c3 = st.columns(3)
c1.metric("総SKU数", f"{len(df):,}")
if COL_CHANNEL < len(df.columns):
    counts = df.iloc[:, COL_CHANNEL].value_counts()
    c2.metric("楽天専売", int(counts.get("楽天専売", 0)))
    c3.metric("両方販売", int(counts.get("両方", 0)))

st.markdown("---")

# フィルタ
with st.expander("🔍 フィルタ", expanded=True):
    fcol1, fcol2 = st.columns([3, 1])
    with fcol1:
        keyword = st.text_input("商品コード・タイトル・小分類検索", "")
    with fcol2:
        ch_opts = ["（全て）"]
        if COL_CHANNEL < len(df.columns):
            ch_opts += sorted(df.iloc[:, COL_CHANNEL].dropna().unique().tolist())
        sel_ch = st.selectbox("チャネル区分", ch_opts)
    sel_sup = "（全て）"  # 仕入先フィルタは廃止

filtered = df.copy()
if keyword:
    cs = [filtered.columns[i] for i in [COL_CODE, COL_TITLE, COL_SMALL_CAT] if i < len(filtered.columns)]
    mask = pd.Series(False, index=filtered.index)
    for c in cs:
        mask |= filtered[c].astype(str).str.contains(keyword, case=False, na=False)
    filtered = filtered[mask]
if sel_ch != "（全て）" and COL_CHANNEL < len(filtered.columns):
    filtered = filtered[filtered.iloc[:, COL_CHANNEL] == sel_ch]
if sel_sup != "（全て）" and COL_SUPPLIER < len(filtered.columns):
    filtered = filtered[filtered.iloc[:, COL_SUPPLIER] == sel_sup]

st.caption(f"表示中: {len(filtered):,} / {len(df):,} 件")

# ===========================================================
# まず編集状態を判定するため一旦テーブルを描画してから判定
# → 未編集なら全幅、編集中なら左7:右3 のレイアウト
# ===========================================================
st.markdown("**凡例**: 🟢 編集可 / 🔒 自動計算（売価などを編集すると右サイドにカード出現）")

cols = list(filtered.columns)
column_config = {}
for i, col in enumerate(cols):
    if i in (COL_CODE, COL_TITLE):
        column_config[col] = st.column_config.TextColumn(label=f"🟢 {col}")
    elif i == COL_PROFIT:
        column_config[col] = st.column_config.NumberColumn(label=f"🔒 {col}", disabled=True, format="¥%d")
    elif i == COL_RATE:
        column_config[col] = st.column_config.NumberColumn(label=f"🔒 {col}", disabled=True, format="%.1f%%")
    elif i == COL_COST:
        column_config[col] = st.column_config.NumberColumn(
            label=f"🔒 H 原価(数式)", disabled=True, format="¥%d",
            help="数式由来。入荷時のコバリ原価計算で使用。手動入力する場合はAC列へ",
        )
    elif i == COL_AC:
        column_config[col] = st.column_config.NumberColumn(
            label=f"🟢 AC 手動原価", min_value=0, step=1, format="¥%d",
            help="手動入力する原価。スクリプトからの自動上書きはしない",
        )
    elif i == COL_AD:
        column_config[col] = st.column_config.TextColumn(label=f"🔒 AD当月販売数", disabled=True, help="数式・自動計算")
    elif i == COL_AE:
        column_config[col] = st.column_config.TextColumn(label=f"🟢 AE 楽天SKU", help="楽天店舗での商品管理番号")
    elif i == COL_AF:
        column_config[col] = st.column_config.TextColumn(label=f"🟢 AF Amazon FBM SKU", help="自社配送(FBM)用Amazon SKU")
    elif i == COL_AG:
        column_config[col] = st.column_config.TextColumn(label=f"🟢 AG Amazon FBA SKU", help="FBA倉庫保管用Amazon SKU")
    elif i == COL_CHANNEL:
        # データ内の既存値を全部選択肢に含める（未知値エラー回避）
        existing_channels = sorted(set(
            str(v).strip() for v in filtered.iloc[:, COL_CHANNEL].dropna().tolist() if str(v).strip()
        ))
        # 標準選択肢を最初に、既存の追加分を後ろに
        std_opts = ["", "楽天専売", "AMA専売", "両方"]
        all_opts = std_opts + [v for v in existing_channels if v not in std_opts]
        column_config[col] = st.column_config.SelectboxColumn(
            label=f"🟢 {col}",
            options=all_opts,
            help="楽天専売 / AMA専売 / 両方 から選択",
        )
    elif i == COL_FEE:
        column_config[col] = st.column_config.NumberColumn(
            label=f"🟢 {col}",
            min_value=0,
            step=0.001,
            format="%.4f",
            help="<1なら率（例: 0.088 = 8.8%）、≥1なら実数（例: 120 = 120円）",
        )
    elif i in EDITABLE_NUMERIC:
        column_config[col] = st.column_config.NumberColumn(label=f"🟢 {col}", min_value=0, step=1)
    else:
        column_config[col] = st.column_config.TextColumn(label=f"🟢 {col}")

# 過去の編集状態（session_state）から、サイドカードを出すかを判定
prev_state = st.session_state.get("master_editor_side", {})
has_edits = bool(prev_state.get("edited_rows"))

# サイドカード（編集中の計算結果）の表示ON/OFF
if "show_sidecard" not in st.session_state:
    st.session_state["show_sidecard"] = True

# 編集中なら表示モード切替UI（テーブル上部に大きく表示）
if has_edits:
    st.markdown("---")
    if st.session_state["show_sidecard"]:
        if st.button("✕ 編集中のサイドカードを閉じる（テーブルを全幅にする）", key="hide_sidecard"):
            st.session_state["show_sidecard"] = False
            st.rerun()
    else:
        if st.button("💡 編集中のサイドカードを表示", key="show_sidecard_btn"):
            st.session_state["show_sidecard"] = True
            st.rerun()
    st.markdown("---")

# サイドカード非表示モードのときは has_edits でも全幅にする
# 紐づけ専用モードでは常にサイドカード非表示（売価編集ないので）
is_link_mode = "紐づけ専用" in st.session_state.get("master_view_mode", "")
show_sidecard = has_edits and st.session_state.get("show_sidecard", True) and not is_link_mode

# ===========================================================
# 表示モード切替（全列 / 紐づけ専用 = A,B,E,AE,AF）
# ===========================================================
view_mode = st.radio(
    "表示モード",
    ["📋 全列", "🔗 紐づけ専用（A/B/E/AE/AF列のみ）"],
    horizontal=True,
    key="master_view_mode",
)

if view_mode.startswith("🔗"):
    # 紐づけ専用モード: A/B/E/F/AE/AF列
    keep_indices = [COL_CODE, COL_TITLE, COL_SMALL_CAT, COL_CHANNEL, COL_AE, COL_AF, COL_AG]
    keep_cols = [filtered.columns[i] for i in keep_indices if i < len(filtered.columns)]
    display_df_view = filtered[keep_cols].copy()
    column_config_view = {c: column_config[c] for c in keep_cols if c in column_config}

    # ===== A列同期: AE(楽天)→AF(FBM)→AG(FBA)優先順でA列を更新 =====
    with st.expander("🔄 A列(主コード)を AE→AF→AG 優先順で同期", expanded=False):
        st.caption(
            "新仕様: AE=楽天SKU / AF=FBM SKU / AG=FBA SKU\n"
            "AE > AF > AG の優先順位で「最も優先度高いSKU」をA列に設定する"
        )

        # 対象抽出: A列 != AE/AF/AG優先のSKU
        # 優先順位ロジック:
        # - 楽天で売ってる(F=楽天専売 or 両方) → AE優先
        # - Amazon専売(F=AMA専売) → AF or AG
        target_rows = []
        m_code_n = filtered.columns[COL_CODE]
        m_ch_n = filtered.columns[COL_CHANNEL] if COL_CHANNEL < len(filtered.columns) else None
        m_ae_n = filtered.columns[COL_AE] if COL_AE < len(filtered.columns) else None
        m_af_n = filtered.columns[COL_AF] if COL_AF < len(filtered.columns) else None
        m_ag_n = filtered.columns[COL_AG] if COL_AG < len(filtered.columns) else None

        warnings = []  # 楽天系なのにAE未入力警告
        for idx, r in filtered.iterrows():
            current_a = str(r[m_code_n]).strip()
            ch = str(r[m_ch_n]).strip() if m_ch_n else ""
            ae = str(r[m_ae_n]).strip() if m_ae_n else ""
            af = str(r[m_af_n]).strip() if m_af_n else ""
            ag = str(r[m_ag_n]).strip() if m_ag_n else ""

            # 楽天で売ってる商品はAE必須、AE未入力なら同期スキップ+警告
            is_rakuten_selling = ch in ("楽天専売", "両方")

            if is_rakuten_selling:
                if ae:
                    ideal = ae  # AE優先
                else:
                    # 楽天売ってるのにAE空 → 警告して同期しない
                    warnings.append(f"{current_a}: F={ch} なのにAE楽天SKU未入力。AE埋めるまでA列同期スキップ")
                    continue
            else:
                # Amazon専売 etc. → AF > AG
                ideal = af or ag

            if ideal and ideal != current_a:
                target_rows.append({
                    "更新する": True,
                    "現A列": current_a,
                    "→ 新A列": ideal,
                    "F販売チャネル": ch,
                    "AE楽天": ae,
                    "AF FBM": af,
                    "AG FBA": ag,
                })

        if warnings:
            st.warning(f"⚠ {len(warnings)}件: 楽天売ってるのにAE楽天SKU未入力（A列同期スキップ）")
            show_warnings = st.checkbox("警告詳細を表示", value=False, key="show_a_sync_warnings")
            if show_warnings:
                for w in warnings[:30]:
                    st.caption(w)
                if len(warnings) > 30:
                    st.caption(f"...他 {len(warnings)-30}件")

        st.metric("変更対象行", len(target_rows))

        if len(target_rows) > 0:
            tg_df = pd.DataFrame(target_rows)
            edited_tg = st.data_editor(
                tg_df,
                use_container_width=True,
                height=300,
                hide_index=True,
                column_config={
                    "更新する": st.column_config.CheckboxColumn(),
                    "現A列": st.column_config.TextColumn(disabled=True),
                    "→ 新A列": st.column_config.TextColumn(disabled=True),
                    "AE楽天": st.column_config.TextColumn(disabled=True),
                    "AF FBM": st.column_config.TextColumn(disabled=True),
                    "AG FBA": st.column_config.TextColumn(disabled=True),
                },
                key="a_sync_editor",
            )

            st.warning(
                "⚠ A列を変更すると 04_在庫管理 / 05_売上管理 / PUSH対象 / 17_終売SKU "
                "などの 旧A列値も新値に置換します（連動更新）"
            )

            if st.button("🔄 チェック分のA列を一括更新（他シートも連動）", type="primary", key="a_sync_btn"):
                to_update = edited_tg[edited_tg["更新する"] == True]
                if len(to_update) == 0:
                    st.warning("チェックされた行がありません")
                else:
                    with st.spinner(f"{len(to_update)}件 更新中..."):
                        try:
                            # 1) マスタA列をbatch_update
                            ss = sheets.get_spreadsheet()
                            ws_master = ss.worksheet("03_商品マスタ参照")
                            master_codes = ws_master.col_values(1)
                            code_to_row = {}
                            for i, c in enumerate(master_codes):
                                if i + 1 < 7:
                                    continue
                                cs = str(c or "").strip()
                                if cs:
                                    code_to_row[cs] = i + 1

                            # 旧→新マップ
                            rename_map = {}
                            updates = []
                            for _, p in to_update.iterrows():
                                old = str(p["現A列"]).strip()
                                new = str(p["→ 新A列"]).strip()
                                if old in code_to_row and old != new:
                                    rename_map[old] = new
                                    updates.append({"range": f"A{code_to_row[old]}", "values": [[new]]})
                            if updates:
                                ws_master.batch_update(updates, value_input_option="USER_ENTERED")

                            # 2) 04 / 05 / PUSH対象 / 17_終売SKU の同じSKUを置換
                            def _replace_in_sheet(sheet_name, col_idx_1based, header_row=1):
                                try:
                                    ws = ss.worksheet(sheet_name)
                                    col_letter = sheets._col_index_to_letter(col_idx_1based)
                                    last_row = ws.row_count
                                    if last_row <= header_row:
                                        return 0
                                    cells = ws.range(f"{col_letter}{header_row+1}:{col_letter}{last_row}")
                                    n_changed = 0
                                    for cell in cells:
                                        v = str(cell.value or "").strip()
                                        if v in rename_map:
                                            cell.value = rename_map[v]
                                            n_changed += 1
                                    if n_changed > 0:
                                        ws.update_cells(cells, value_input_option="USER_ENTERED")
                                    return n_changed
                                except Exception as e:
                                    return f"error: {e}"

                            replace_results = {}
                            replace_results["04"] = _replace_in_sheet("04_在庫管理", 1, header_row=6)
                            replace_results["05"] = _replace_in_sheet("05_売上管理", 4, header_row=6)
                            replace_results["PUSH対象"] = _replace_in_sheet("PUSH対象", 1, header_row=1)
                            replace_results["17_終売SKU"] = _replace_in_sheet("17_終売SKU", 1, header_row=1)

                            sheets.clear_all_caches()
                            st.success(
                                f"✅ {len(updates)}件のマスタA列更新完了\n"
                                f"連動更新:\n"
                                + "\n".join(f"- {k}: {v}件" for k, v in replace_results.items())
                            )
                            st.balloons()
                            st.rerun()
                        except Exception as e:
                            st.error(f"失敗: {e}")
                            import traceback
                            st.code(traceback.format_exc())
        else:
            st.success("✅ A列はAE/AF/AG優先順位と一致してます")

    # ===== 紐づけ専用モード内に「整合性チェック」を表示 =====
    with st.expander("🔧 チャネル整合性チェック（AE/AF列あり×単一チャネル を一括「両方」化）", expanded=False):
        m_code_n = filtered.columns[COL_CODE]
        m_ae_n = filtered.columns[COL_AE] if COL_AE < len(filtered.columns) else None
        m_af_n = filtered.columns[COL_AF] if COL_AF < len(filtered.columns) else None
        m_ch_n = filtered.columns[COL_CHANNEL] if COL_CHANNEL < len(filtered.columns) else None

        if m_ae_n and m_ch_n:
            ae_filled = filtered[m_ae_n].astype(str).str.strip() != ""
            af_filled = filtered[m_af_n].astype(str).str.strip() != "" if m_af_n else False
            amazon_linked = ae_filled | af_filled
            ch_series = filtered[m_ch_n].astype(str).str.strip()
            problem = filtered[amazon_linked & ch_series.isin(["楽天専売", "AMA専売"])]

            st.metric("⚠ AE/AFあり×単一チャネル", len(problem))

            if len(problem) > 0:
                show_p = problem[[m_code_n, filtered.columns[COL_TITLE], m_ch_n, m_ae_n]].copy()
                if m_af_n:
                    show_p[m_af_n] = problem[m_af_n]
                show_p.insert(0, "両方に変更", True)

                edited_p = st.data_editor(
                    show_p,
                    use_container_width=True,
                    height=300,
                    hide_index=True,
                    column_config={
                        "両方に変更": st.column_config.CheckboxColumn(),
                        m_code_n: st.column_config.TextColumn(disabled=True),
                        m_ch_n: st.column_config.TextColumn(disabled=True, label="現チャネル"),
                    },
                    key="channel_fix_editor",
                )

                if st.button("🔧 チェック分を「両方」に一括変更", type="primary", key="channel_fix_btn"):
                    to_fix = edited_p[edited_p["両方に変更"] == True]
                    if len(to_fix) == 0:
                        st.warning("チェックされた行がありません")
                    else:
                        with st.spinner(f"{len(to_fix)}件 更新中..."):
                            ss = sheets.get_spreadsheet()
                            ws = ss.worksheet("03_商品マスタ参照")
                            master_codes = ws.col_values(1)
                            code_to_row = {str(c or "").strip(): i+1 for i, c in enumerate(master_codes) if i+1 >= 7 and str(c or "").strip()}
                            f_letter = sheets._col_index_to_letter(COL_CHANNEL + 1)
                            updates = []
                            for _, p in to_fix.iterrows():
                                code = str(p[m_code_n]).strip()
                                if code in code_to_row:
                                    updates.append({"range": f"{f_letter}{code_to_row[code]}", "values": [["両方"]]})
                            if updates:
                                ws.batch_update(updates, value_input_option="USER_ENTERED")
                            sheets._invalidate_one("03_商品マスタ参照")
                        st.success(f"✅ {len(to_fix)}件 「両方」に変更")
                        st.balloons()
                        st.rerun()
            else:
                st.success("✅ 不整合なし")
else:
    # 全列モード: 表示列カスタマイズ（永続化）
    MASTER_PREF_KEY = "page03_master_visible_cols"
    master_all_cols = list(filtered.columns)

    if "_master_visible_cols" not in st.session_state:
        st.session_state["_master_visible_cols"] = user_prefs.get_pref(
            MASTER_PREF_KEY, master_all_cols
        )
    master_saved = [c for c in st.session_state["_master_visible_cols"] if c in master_all_cols]
    if not master_saved:
        master_saved = master_all_cols

    def _apply_master_cols(cols):
        st.session_state["_master_visible_cols"] = cols
        user_prefs.set_pref(MASTER_PREF_KEY, cols)

    with st.expander(
        f"📐 表示列カスタマイズ(現在 {len(master_saved)}/{len(master_all_cols)}列)",
        expanded=False,
    ):
        st.caption("プリセット(クリックで即適用・永続化)")
        mp1, mp2, mp3, mp4 = st.columns(4)
        if mp1.button("全て表示", use_container_width=True, key="master_cols_all"):
            _apply_master_cols(master_all_cols)
            st.rerun()
        if mp2.button("基本のみ", use_container_width=True, key="master_cols_basic",
                      help="商品コード/タイトル/小分類/チャネル/原価/手数料/送料/売価/利益額/利益率"):
            basic_idx = [COL_CODE, COL_TITLE, COL_SMALL_CAT, COL_CHANNEL,
                         COL_COST, COL_FEE, COL_SHIP, COL_PRICE, COL_PROFIT, COL_RATE]
            basic = [master_all_cols[i] for i in basic_idx if i < len(master_all_cols)]
            _apply_master_cols(basic)
            st.rerun()
        if mp3.button("価格・利益", use_container_width=True, key="master_cols_money",
                      help="商品コード/タイトル/原価/売価/利益額/利益率/AC手動原価"):
            money_idx = [COL_CODE, COL_TITLE, COL_COST, COL_PRICE, COL_PROFIT, COL_RATE, COL_AC]
            money = [master_all_cols[i] for i in money_idx if i < len(master_all_cols)]
            _apply_master_cols(money)
            st.rerun()
        if mp4.button("紐づけ系", use_container_width=True, key="master_cols_linking",
                      help="商品コード/タイトル/小分類/チャネル/楽天SKU/FBM/FBA"):
            link_idx = [COL_CODE, COL_TITLE, COL_SMALL_CAT, COL_CHANNEL,
                        COL_AE, COL_AF, COL_AG]
            link = [master_all_cols[i] for i in link_idx if i < len(master_all_cols)]
            _apply_master_cols(link)
            st.rerun()

        st.markdown("---")
        st.caption("カスタム選択(×で外す/プルダウンから追加 → 「✅ 適用」で反映・永続化)")
        mmc1, mmc2 = st.columns([4, 1])
        with mmc1:
            master_pending = st.multiselect(
                "表示する列",
                options=master_all_cols,
                default=master_saved,
                key="_master_visible_cols_ms",
                label_visibility="collapsed",
            )
        with mmc2:
            if st.button("✅ 適用", use_container_width=True, type="primary",
                         key="master_cols_apply"):
                _apply_master_cols(master_pending if master_pending else master_all_cols)
                st.rerun()
        if master_pending != master_saved:
            st.info(f"📝 選択中: {len(master_pending)}列 — 「✅ 適用」を押して反映")

    # AC(手動原価)とH(原価) の表示位置を入れ替える
    # ユーザーが普段見たいのは AC(手動原価)、H は数式で参照用
    h_name = master_all_cols[COL_COST] if COL_COST < len(master_all_cols) else None
    ac_name = master_all_cols[COL_AC] if COL_AC < len(master_all_cols) else None
    saved_for_display = list(master_saved)
    if h_name and ac_name and h_name in saved_for_display and ac_name in saved_for_display:
        i_h = saved_for_display.index(h_name)
        i_ac = saved_for_display.index(ac_name)
        saved_for_display[i_h], saved_for_display[i_ac] = saved_for_display[i_ac], saved_for_display[i_h]

    display_df_view = filtered[saved_for_display]
    column_config_view = {c: column_config[c] for c in saved_for_display if c in column_config}

if show_sidecard:
    # 編集中: 左テーブル + 右サイドカード
    main_col, side_col = st.columns([7, 3])
    with main_col:
        edited = st.data_editor(
            display_df_view,
            use_container_width=True,
            height=600,
            hide_index=True,
            num_rows="fixed",
            column_config=column_config_view,
            key="master_editor_side",
        )

    # 編集された行を抽出
    changed_indices = []
    for pos in range(len(filtered)):
        for col_pos in EDITABLE_NUMERIC:
            if col_pos >= len(filtered.columns):
                continue
            old = to_num(filtered.iloc[pos, col_pos])
            new = to_num(edited.iloc[pos, col_pos])
            if abs(old - new) > 0.0001:
                changed_indices.append(pos)
                break

    with side_col:
        st.markdown("### 💡 編集中")
        st.caption(f"{len(changed_indices)}行")
        for pos in changed_indices[:20]:
            row = edited.iloc[pos]
            code  = row.iloc[COL_CODE]
            title = row.iloc[COL_TITLE] if len(row) > COL_TITLE else ""
            cost  = to_num(row.iloc[COL_COST])  if len(row) > COL_COST  else 0
            fee   = to_num(row.iloc[COL_FEE])   if len(row) > COL_FEE   else 0
            ship  = to_num(row.iloc[COL_SHIP])  if len(row) > COL_SHIP  else 0
            price = to_num(row.iloc[COL_PRICE]) if len(row) > COL_PRICE else 0
            profit, rate = calc_profit_rate(cost, fee, ship, price)

            old_price  = to_num(filtered.iloc[pos, COL_PRICE])
            old_profit = to_num(filtered.iloc[pos, COL_PROFIT])

            with st.container(border=True):
                st.markdown(f"**{code}**")
                st.caption(f"{title[:25]}")
                st.metric(
                    "売価", f"¥{int(price):,}",
                    delta=f"{int(price - old_price):+,}" if abs(price - old_price) > 0 else None
                )
                st.metric(
                    "利益額", f"¥{int(profit):,}",
                    delta=f"{int(profit - old_profit):+,}" if abs(profit - old_profit) > 0 else None
                )
                st.metric("利益率", f"{rate*100:.1f}%")
        if len(changed_indices) > 20:
            st.caption(f"...他 {len(changed_indices) - 20}行")
else:
    # 未編集: 全幅テーブル
    edited = st.data_editor(
        display_df_view,
        use_container_width=True,
        height=600,
        hide_index=True,
        num_rows="fixed",
        column_config=column_config_view,
        key="master_editor_side",
    )

# ===========================================================
# 変更検出 + 一括保存
# ===========================================================
# 変更検出: edited(表示中)の列だけを見る
# edited の列が filtered の何列目に対応するかマップ
diffs = []
edited_cols = list(edited.columns)
# edited の各列について、filtered での実際の列番号(0-indexed)を求める
edited_to_filtered_pos = {}
for ec in edited_cols:
    if ec in filtered.columns:
        edited_to_filtered_pos[ec] = list(filtered.columns).index(ec)

for pos in range(len(filtered)):
    orig_idx = filtered.index[pos]
    for col_name in edited_cols:
        if col_name not in edited_to_filtered_pos:
            continue
        col_pos = edited_to_filtered_pos[col_name]
        # 保護列は保存対象外
        if col_pos in PROTECTED_COLS:
            continue
        old_val = filtered.iloc[pos][col_name]
        new_val = edited.iloc[pos][col_name]
        if col_pos in EDITABLE_NUMERIC:
            if abs(to_num(old_val) - to_num(new_val)) < 0.0001:
                continue
        else:
            if str(old_val) == str(new_val):
                continue
        diffs.append({
            "行": orig_idx + 7,
            "商品コード": filtered.iloc[pos, COL_CODE],
            "列": col_name,
            "旧": old_val,
            "新": new_val,
            "_sheet_row": orig_idx + 7,
            "_sheet_col": col_pos + 1,
        })

st.markdown("---")
st.markdown("### 💾 変更を確定")
st.caption(f"🐛 検出した変更件数: {len(diffs)}")

if len(diffs) > 0:
    st.warning(f"⚠ {len(diffs)} 件の変更（保存待ち）")
    diff_df = pd.DataFrame(diffs)[["行", "商品コード", "列", "旧", "新"]]
    st.dataframe(diff_df, use_container_width=True, hide_index=True, height=200)

    # AE列(Amazon SKU)に変更があったか検出
    ae_col_idx = 31  # AE列 = 1-indexed 31
    ae_changes = [d for d in diffs if d["_sheet_col"] == ae_col_idx]
    has_ae_change = len(ae_changes) > 0

    if has_ae_change:
        st.info(
            f"💡 AE列(Amazon SKU)に **{len(ae_changes)}件** の変更があります。\n"
            f"保存後、対応する楽天SKUとAmazon SKUの **プール在庫式を自動再設定**します"
        )

    if st.button("💾 全変更を確定保存", type="primary", use_container_width=True):
        with st.spinner(f"{len(diffs)}件 保存中..."):
            try:
                ss = sheets.get_spreadsheet()
                ws = ss.worksheet(SHEET_NAME)
                requests = []
                for d in diffs:
                    cell = f"{sheets._col_index_to_letter(d['_sheet_col'])}{d['_sheet_row']}"
                    val = d["新"]
                    if d["_sheet_col"] == COL_RATE + 1:
                        try:
                            val = float(val) / 100
                        except (ValueError, TypeError):
                            pass
                    requests.append({"range": cell, "values": [[val]]})
                ws.batch_update(requests, value_input_option="USER_ENTERED")
                sheets._invalidate_one(SHEET_NAME)
                st.success(f"✅ {len(diffs)}件保存完了")

                # AE列変更があった場合、プール在庫を自動再設定
                if has_ae_change:
                    with st.spinner("🔄 プール在庫式を自動更新中..."):
                        try:
                            # 全プールペアを再設定（マスタ最新版で）
                            result = pool_inventory.apply_pool_setup()
                            # K列ARRAYFORMULAも更新
                            all_pairs = pool_inventory.get_pool_pairs()
                            amazon_skus = [a for _, a in all_pairs]
                            pool_inventory.update_k_arrayformula(amazon_skus)
                            st.success(
                                f"🔄 プール在庫自動更新完了\n\n"
                                f"- 楽天SKU行 F列: {result['master_updated']}件\n"
                                f"- Amazon SKU行 F列: {result['mirror_updated']}件\n"
                                f"- K列(在庫金額)も二重カウント防止"
                            )
                        except Exception as e:
                            st.warning(f"⚠ プール在庫の自動更新に失敗: {e}")
                            st.caption("手動で「🔄 プール在庫設定」ページから再実行してください")

                st.balloons()
                st.rerun()
            except Exception as e:
                st.error(f"保存失敗: {e}")
else:
    st.info("変更なし")

st.markdown("---")
st.info("➕ 新規SKU追加は サイドバー「**➕ 新規SKU登録**」ページから")
