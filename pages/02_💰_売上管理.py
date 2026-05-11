"""
05_売上管理 編集 + CSV取り込み

シート構成（17列）:
  A 日付 | B モール | C 注文番号 | D 商品コード | E 商品名 | F SKU
  G 数量 | H 単価 | I 売上 | J 原価 | K 手数料 | L 送料
  M 楽天ポイント費用 | N 楽天クーポン費用 | O 利益額 | P 利益率 | Q 備考
"""
from datetime import date, timedelta
from io import StringIO

import pandas as pd
import streamlit as st

from lib import sheets, ui, user_prefs

st.set_page_config(page_title="売上管理", page_icon="💰", layout="wide")
st.title("💰 05_売上管理（編集可）")

SHEET_NAME = "05_売上管理"
ui.sidebar_common(this_sheet=SHEET_NAME)

with st.spinner("読み込み中..."):
    df = sheets.load_sales()

if df.empty:
    st.warning("売上データなし")
    df = pd.DataFrame()

# ===========================================================
# 💰 在庫金額サマリ
# ===========================================================
def _to_num(v):
    try:
        return float(str(v).replace(",", "").replace("¥", "").strip())
    except (ValueError, TypeError):
        return 0.0


with st.expander("💰 在庫金額サマリ", expanded=True):
    try:
        with st.spinner("在庫データ集計中..."):
            inv_df = sheets.load_inventory()
            master_df = sheets.load_master()

        # マスタ A列(商品コード) → AC列(直接入力原価) のマップ
        master_cost: dict[str, float] = {}
        if not master_df.empty:
            m_code = master_df.columns[0]
            ac_col_idx = 28
            if len(master_df.columns) > ac_col_idx:
                ac_col = master_df.columns[ac_col_idx]
                for c, p in zip(master_df[m_code].astype(str).str.strip(), master_df[ac_col]):
                    if c:
                        master_cost[c] = _to_num(p)

        # 在庫金額（販売中: H列 × 原価）
        # 04の K列が既に在庫金額数式なのでそれを優先
        sell_amount = 0.0
        order_amount = 0.0
        if not inv_df.empty:
            for _, r in inv_df.iterrows():
                code = str(r.iloc[0]).strip()
                if not code:
                    continue
                # K列(在庫金額) インデックス10
                k_val = _to_num(r.iloc[10]) if len(r) > 10 else 0
                if k_val > 0:
                    sell_amount += k_val
                # 発注済み(L列, インデックス11) × マスタ原価
                ordered_qty = _to_num(r.iloc[11]) if len(r) > 11 else 0
                if ordered_qty > 0:
                    order_amount += ordered_qty * master_cost.get(code, 0)

        # 手動入力欄（ツール外在庫）
        manual_amount = user_prefs.get_pref("manual_outside_stock_amount", 0)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📦 販売中在庫金額", f"¥{int(sell_amount):,}")
        c2.metric("🚚 発注中在庫金額", f"¥{int(order_amount):,}")
        with c3:
            new_manual = st.number_input(
                "✏️ ツール外在庫金額",
                min_value=0, value=int(manual_amount), step=1000,
                help="ツール管理外の在庫金額を手入力（永続化）",
            )
            if new_manual != manual_amount:
                user_prefs.set_pref("manual_outside_stock_amount", int(new_manual))
        total = int(sell_amount) + int(order_amount) + int(new_manual)
        c4.metric("🔵 合計在庫金額", f"¥{total:,}")
    except Exception as e:
        st.warning(f"在庫サマリ取得失敗: {e}")

# ===========================================================
# 列の同定（インデックス基準）
# ===========================================================
def _col_idx(df, idx):
    return df.columns[idx] if idx < len(df.columns) else None

COL_DATE      = _col_idx(df, 0)
COL_CHANNEL   = _col_idx(df, 1)
COL_ORDER     = _col_idx(df, 2)
COL_PRODUCT   = _col_idx(df, 3)
COL_TITLE     = _col_idx(df, 4)
COL_SKU       = _col_idx(df, 5)
COL_QTY       = _col_idx(df, 6)
COL_PRICE     = _col_idx(df, 7)
COL_AMOUNT    = _col_idx(df, 8)
COL_COST      = _col_idx(df, 9)
COL_FEE       = _col_idx(df, 10)
COL_SHIP      = _col_idx(df, 11)
COL_POINT     = _col_idx(df, 12)
COL_COUPON    = _col_idx(df, 13)
COL_PROFIT    = _col_idx(df, 14)
COL_RATE      = _col_idx(df, 15)
COL_MEMO      = _col_idx(df, 16)

# ===========================================================
# 日付パース
# ===========================================================
def _parse_dates(series):
    s = series.astype(str).str.strip()
    parsed = pd.to_datetime(s, errors="coerce", format="mixed")
    mask = parsed.isna() & s.str.match(r"^\d+(\.\d+)?$", na=False)
    if mask.any():
        try:
            serials = pd.to_numeric(s[mask], errors="coerce")
            parsed.loc[mask] = pd.to_datetime("1899-12-30") + pd.to_timedelta(serials, unit="D")
        except Exception:
            pass
    return parsed

if COL_DATE and not df.empty:
    df[COL_DATE] = _parse_dates(df[COL_DATE])
    df = df.dropna(subset=[COL_DATE])

# 数値変換
def _to_num_series(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.replace("¥", "").str.strip(), errors="coerce").fillna(0)

NUMERIC_COLS = [COL_QTY, COL_PRICE, COL_AMOUNT, COL_COST, COL_FEE, COL_SHIP, COL_POINT, COL_COUPON, COL_PROFIT]
for c in NUMERIC_COLS:
    if c and c in df.columns:
        df[c] = _to_num_series(df[c])

# 利益率は売上・利益から再計算（原データの%表記揺れを回避）
if COL_AMOUNT and COL_PROFIT and COL_RATE and not df.empty:
    df[COL_RATE] = df.apply(
        lambda r: (float(r[COL_PROFIT]) / float(r[COL_AMOUNT]) * 100) if float(r[COL_AMOUNT]) > 0 else 0,
        axis=1,
    )

st.markdown("---")

# ===========================================================
# Tab構成
# ===========================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 閲覧・グラフ", "✏️ 編集・削除", "📥 CSV取り込み", "🔧 マスタ補完",
])

# -----------------------------------------------------------
# Tab 1: 閲覧（フィルタ条件で1つの集計表 + 1つのグラフ）
# -----------------------------------------------------------
with tab1:
    if df.empty:
        st.warning("データなし")
    else:
        # デフォルト = 今月 / 全チャネル
        today = date.today()
        month_start = today.replace(day=1)
        min_d = df[COL_DATE].min().date()
        max_d = df[COL_DATE].max().date()
        default_start = max(min_d, month_start)
        default_end = min(max_d, today)

        with st.expander("🔍 フィルタ", expanded=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                date_range = st.date_input(
                    "期間",
                    value=(default_start, default_end),
                    min_value=min_d, max_value=max_d,
                )
            with col2:
                if COL_CHANNEL:
                    ch_opts = ["（全て）"] + sorted(df[COL_CHANNEL].dropna().unique().tolist())
                    sel_ch = st.selectbox("モール", ch_opts, key="view_ch")
                else:
                    sel_ch = "（全て）"
            with col3:
                keyword = st.text_input("商品コード・タイトル検索", "", key="view_kw")

        # フィルタ適用
        filtered = df.copy()
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start, end = date_range
            filtered = filtered[(filtered[COL_DATE].dt.date >= start) & (filtered[COL_DATE].dt.date <= end)]
        if COL_CHANNEL and sel_ch != "（全て）":
            filtered = filtered[filtered[COL_CHANNEL] == sel_ch]
        if keyword and COL_PRODUCT:
            mask = filtered[COL_PRODUCT].astype(str).str.contains(keyword, case=False, na=False)
            if COL_TITLE in filtered.columns:
                mask |= filtered[COL_TITLE].astype(str).str.contains(keyword, case=False, na=False)
            filtered = filtered[mask]

        # === 1つの集計表 ===
        st.markdown("### 📊 集計結果")
        period_str = ""
        if isinstance(date_range, tuple) and len(date_range) == 2:
            period_str = f"{date_range[0]} 〜 {date_range[1]}"
        st.caption(f"期間: {period_str} / モール: {sel_ch} / 検索: {keyword or '（なし）'} / 件数: {len(filtered):,}")

        if filtered.empty:
            st.info("該当データなし")
        else:
            # デバッグ用
            with st.expander("🐛 デバッグ"):
                st.write({
                    "COL_AMOUNT": COL_AMOUNT,
                    "COL_PROFIT": COL_PROFIT,
                    "COL_CHANNEL": COL_CHANNEL,
                    "filtered.columns": list(filtered.columns),
                    "filtered[COL_AMOUNT].dtype": str(filtered[COL_AMOUNT].dtype) if COL_AMOUNT in filtered.columns else "N/A",
                    "filtered[COL_AMOUNT] head": filtered[COL_AMOUNT].head().tolist() if COL_AMOUNT in filtered.columns else [],
                    "filtered[COL_AMOUNT].sum()": float(filtered[COL_AMOUNT].sum()) if COL_AMOUNT in filtered.columns else 0,
                    "filtered[COL_PROFIT] head": filtered[COL_PROFIT].head().tolist() if COL_PROFIT in filtered.columns else [],
                    "filtered[COL_PROFIT].sum()": float(filtered[COL_PROFIT].sum()) if COL_PROFIT in filtered.columns else 0,
                })

            # チャネル別 + 合計の集計表
            summary_rows = []
            channels_in_data = sorted(filtered[COL_CHANNEL].dropna().unique().tolist()) if COL_CHANNEL else []
            for ch in channels_in_data:
                sub = filtered[filtered[COL_CHANNEL] == ch]
                s = float(sub[COL_AMOUNT].sum()) if COL_AMOUNT else 0
                p = float(sub[COL_PROFIT].sum()) if COL_PROFIT else 0
                summary_rows.append({
                    "モール": ch,
                    "注文数": len(sub),
                    "売上": s,
                    "利益": p,
                    "利益率": (p / s * 100) if s > 0 else 0,
                })
            # 合計行
            total_s = float(filtered[COL_AMOUNT].sum()) if COL_AMOUNT else 0
            total_p = float(filtered[COL_PROFIT].sum()) if COL_PROFIT else 0
            summary_rows.append({
                "モール": "🟦 合計",
                "注文数": len(filtered),
                "売上": total_s,
                "利益": total_p,
                "利益率": (total_p / total_s * 100) if total_s > 0 else 0,
            })

            summary_df = pd.DataFrame(summary_rows)
            st.dataframe(
                summary_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "売上":   st.column_config.NumberColumn(format="¥%d"),
                    "利益":   st.column_config.NumberColumn(format="¥%d"),
                    "利益率": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

            # === 棒グラフ: 日次推移（チャネル別積み上げ）===
            if COL_CHANNEL and COL_AMOUNT:
                st.markdown("### 📈 日次売上推移")
                pivot = filtered.pivot_table(
                    index=filtered[COL_DATE].dt.date,
                    columns=COL_CHANNEL,
                    values=COL_AMOUNT,
                    aggfunc="sum",
                    fill_value=0,
                )
                st.bar_chart(pivot, height=520, use_container_width=True)

            # ----- 表示列カスタマイズ（永続化、注文一覧の外） -----
            SALES_PREF_KEY = "page02_sales_visible_cols"
            sales_all_cols = list(filtered.columns)

            if "_sales_visible_cols" not in st.session_state:
                st.session_state["_sales_visible_cols"] = user_prefs.get_pref(
                    SALES_PREF_KEY, sales_all_cols
                )
            sales_saved = [c for c in st.session_state["_sales_visible_cols"] if c in sales_all_cols]
            if not sales_saved:
                sales_saved = sales_all_cols

            def _apply_sales_cols(cols):
                st.session_state["_sales_visible_cols"] = cols
                user_prefs.set_pref(SALES_PREF_KEY, cols)

            with st.expander(
                f"📐 注文一覧の表示列カスタマイズ（現在 {len(sales_saved)}/{len(sales_all_cols)}列）",
                expanded=False,
            ):
                st.caption("プリセット（クリックで即適用・永続化）")
                sp1, sp2, sp3 = st.columns(3)
                if sp1.button("全て表示", use_container_width=True, key="sales_cols_all"):
                    _apply_sales_cols(sales_all_cols)
                    st.rerun()
                if sp2.button("コア指標のみ", use_container_width=True, key="sales_cols_core",
                              help="日付/モール/商品コード/数量/売上/利益額/利益率"):
                    core = [c for c in [COL_DATE, COL_CHANNEL, COL_PRODUCT, COL_QTY,
                                        COL_AMOUNT, COL_PROFIT, COL_RATE]
                            if c and c in sales_all_cols]
                    _apply_sales_cols(core)
                    st.rerun()
                if sp3.button("金額系", use_container_width=True, key="sales_cols_money",
                              help="日付/商品コード/売上/原価/手数料/送料/利益額/利益率"):
                    money = [c for c in [COL_DATE, COL_PRODUCT, COL_AMOUNT, COL_COST,
                                         COL_FEE, COL_SHIP, COL_PROFIT, COL_RATE]
                             if c and c in sales_all_cols]
                    _apply_sales_cols(money)
                    st.rerun()

                st.markdown("---")
                st.caption("カスタム選択（×で外す/プルダウンから追加 → 「✅ 適用」で反映・永続化）")
                smc1, smc2 = st.columns([4, 1])
                with smc1:
                    sales_pending = st.multiselect(
                        "表示する列",
                        options=sales_all_cols,
                        default=sales_saved,
                        key="_sales_visible_cols_ms",
                        label_visibility="collapsed",
                    )
                with smc2:
                    if st.button("✅ 適用", use_container_width=True, type="primary",
                                 key="sales_cols_apply"):
                        _apply_sales_cols(sales_pending if sales_pending else sales_all_cols)
                        st.rerun()
                if sales_pending != sales_saved:
                    st.info(f"📝 選択中: {len(sales_pending)}列 — 「✅ 適用」を押して反映")

            # === 注文一覧（折りたたみ）===
            with st.expander(f"📋 注文一覧（{len(filtered):,}件）"):
                order_column_config = {}
                for c in [COL_AMOUNT, COL_COST, COL_FEE, COL_SHIP, COL_PROFIT, COL_POINT, COL_COUPON]:
                    if c and c in filtered.columns:
                        order_column_config[c] = st.column_config.NumberColumn(format="¥%d")
                if COL_RATE and COL_RATE in filtered.columns:
                    order_column_config[COL_RATE] = st.column_config.NumberColumn(format="%.1f%%")
                if COL_QTY and COL_QTY in filtered.columns:
                    order_column_config[COL_QTY] = st.column_config.NumberColumn(format="%d")

                display_filtered = filtered[sales_saved]
                st.dataframe(
                    display_filtered.sort_values(COL_DATE, ascending=False) if COL_DATE in display_filtered.columns else display_filtered,
                    use_container_width=True,
                    height=500,
                    hide_index=True,
                    column_config=order_column_config,
                )
                csv = filtered.to_csv(index=False).encode("utf-8-sig")
                st.download_button("💾 CSV出力", csv,
                                   file_name=f"sales_{len(filtered)}rows.csv",
                                   mime="text/csv")

# -----------------------------------------------------------
# Tab 2: 編集・削除
# -----------------------------------------------------------
with tab2:
    if df.empty:
        st.warning("データなし")
    else:
        st.caption("⚠ 12,000行超は重いので、必ず期間で絞ってから編集してください")
        col1, col2 = st.columns(2)
        with col1:
            edit_start = st.date_input(
                "編集対象 開始日",
                value=df[COL_DATE].max().date() - timedelta(days=7),
                key="edit_start",
            )
        with col2:
            edit_end = st.date_input(
                "編集対象 終了日",
                value=df[COL_DATE].max().date(),
                key="edit_end",
            )

        edit_target = df[(df[COL_DATE].dt.date >= edit_start) & (df[COL_DATE].dt.date <= edit_end)].copy()
        st.caption(f"編集対象: {len(edit_target):,} 件")

        if len(edit_target) > 500:
            st.warning(f"⚠ {len(edit_target)}件は多すぎます。期間を狭めてください")
        elif len(edit_target) > 0:
            edited = st.data_editor(
                edit_target,
                use_container_width=True,
                height=500,
                hide_index=True,
                num_rows="dynamic",  # 行削除可
                key="sales_editor",
            )

            # 変更検出
            removed = len(edit_target) - len(edited)
            cell_changes = 0
            for idx in edited.index:
                if idx in edit_target.index:
                    for c in edit_target.columns:
                        if str(edit_target.at[idx, c]) != str(edited.at[idx, c]):
                            cell_changes += 1
                            break

            st.markdown("---")
            mc1, mc2 = st.columns(2)
            mc1.metric("削除予定行", removed)
            mc2.metric("セル変更行", cell_changes)

            if removed > 0 or cell_changes > 0:
                st.warning(f"⚠ {removed}行削除、{cell_changes}行セル変更があります")

                if st.button("💾 編集対象期間を保存", type="primary"):
                    with st.spinner("保存中..."):
                        try:
                            ss = sheets.get_spreadsheet()
                            ws = ss.worksheet(SHEET_NAME)
                            # 編集対象期間の行範囲
                            start_row = edit_target.index.min() + 2  # ヘッダ行=1, データ=2〜
                            end_row = edit_target.index.max() + 2
                            # まずクリア
                            ws.batch_clear([f"A{start_row}:Z{end_row}"])
                            # 編集後データ書込
                            if not edited.empty:
                                values = edited.fillna("").astype(str).values.tolist()
                                ws.update(
                                    range_name=f"A{start_row}",
                                    values=values,
                                    value_input_option="USER_ENTERED"
                                )
                            sheets._invalidate_one(SHEET_NAME)
                            st.success(f"✅ 保存完了（{len(edited)}行）")
                            st.balloons()
                            st.rerun()
                        except Exception as e:
                            st.error(f"保存失敗: {e}")
            else:
                st.info("変更なし")

# -----------------------------------------------------------
# Tab 3: CSV取り込み
# -----------------------------------------------------------
with tab3:
    st.subheader("CSV取り込み（売上データ追加）")
    st.caption("楽天・Amazonからエクスポートした売上CSVを取り込み")

    has_header = st.checkbox("✅ CSV/貼り付けの 1行目はヘッダ", value=True, key="sales_csv_header")

    uploaded = st.file_uploader(
        "ファイル選択（.csv / .tsv / .xlsx）",
        type=["csv", "tsv", "xlsx", "xls"],
        key="sales_uploader",
    )
    pasted = st.text_area(
        "またはここに貼り付け",
        height=150,
        key="sales_paste",
    )

    new_data = None
    read_kwargs = dict(dtype=str, header=0 if has_header else None)

    if uploaded is not None:
        try:
            if uploaded.name.endswith((".xlsx", ".xls")):
                new_data = pd.read_excel(uploaded, **read_kwargs).fillna("")
            else:
                content = uploaded.read().decode("utf-8-sig", errors="replace")
                first = content.split("\n")[0] if content else ""
                sep = "\t" if first.count("\t") > first.count(",") else ","
                new_data = pd.read_csv(StringIO(content), sep=sep, **read_kwargs).fillna("")
            st.success(f"読込: {len(new_data)}行 × {len(new_data.columns)}列")
        except Exception as e:
            st.error(f"読込失敗: {e}")
    elif pasted.strip():
        try:
            sep = "\t" if pasted.split("\n")[0].count("\t") > pasted.split("\n")[0].count(",") else ","
            new_data = pd.read_csv(StringIO(pasted), sep=sep, **read_kwargs).fillna("")
            st.success(f"読込: {len(new_data)}行 × {len(new_data.columns)}列")
        except Exception as e:
            st.error(f"読込失敗: {e}")

    if not has_header and new_data is not None:
        new_data.columns = [f"位置{i+1}" for i in range(len(new_data.columns))]

    if new_data is not None and not new_data.empty:
        st.markdown("**プレビュー（先頭5行）**")
        st.dataframe(new_data.head(), use_container_width=True, hide_index=True)

        if not df.empty:
            st.markdown("---")
            st.markdown("### 🔗 列マッピング: シート列 ← CSV列")
            csv_options = ["（空欄）"] + list(new_data.columns)
            mapping = {}

            for sheet_col in df.columns:
                # 自動推定
                default_idx = 0
                for i, csv_col in enumerate(new_data.columns):
                    if str(sheet_col) == str(csv_col) or str(sheet_col) in str(csv_col):
                        default_idx = i + 1
                        break

                cc1, cc2 = st.columns([2, 5])
                with cc1:
                    st.caption(f"📌 {sheet_col}")
                with cc2:
                    chosen = st.selectbox(
                        f"src_{sheet_col}",
                        csv_options,
                        index=default_idx,
                        key=f"sales_map_{sheet_col}",
                        label_visibility="collapsed",
                    )
                mapping[sheet_col] = chosen

            # マッピング後プレビュー
            mapped_rows = []
            for _, row in new_data.iterrows():
                d = {}
                for sc, src in mapping.items():
                    d[sc] = "" if src == "（空欄）" else row[src]
                mapped_rows.append(d)
            mapped_df = pd.DataFrame(mapped_rows, columns=list(df.columns))

            st.markdown("**👀 マッピング後プレビュー**")
            st.dataframe(mapped_df.head(), use_container_width=True, hide_index=True)

            if st.button("📤 売上管理シートに追加", type="primary", key="add_sales"):
                with st.spinner("追加中..."):
                    rows = mapped_df.fillna("").astype(str).values.tolist()
                    sheets.append_rows(SHEET_NAME, rows)
                st.success(f"✅ {len(rows)}件追加")
                st.balloons()
                st.rerun()
        else:
            st.info("シート空。CSVをそのままシート化")
            if st.button("📤 シート化", type="primary"):
                sheets.create_or_replace_sheet(SHEET_NAME, new_data)
                st.rerun()

# -----------------------------------------------------------
# Tab 4: マスタ補完（原価=0行をマスタから引き直し）
# -----------------------------------------------------------
with tab4:
    st.subheader("🔧 原価=0の売上行をマスタから補完")
    st.caption(
        "GASの楽天/Amazon取得時、SKUの先頭0が落ちて"
        "マスタと一致しなかった行などを後から補完。"
        "商品コードは**文字列比較**（先頭0保持）。"
    )

    if df.empty:
        st.warning("売上データなし")
    else:
        master = sheets.load_master()
        if master.empty:
            st.error("マスタ読込失敗")
        else:
            def _f(v) -> float:
                try:
                    return float(str(v).replace("¥", "").replace(",", "").strip())
                except (ValueError, TypeError):
                    return 0.0

            def _fee(v) -> float:
                """手数料セル: '10.00%' → 0.10、'120' → 120 のように両対応"""
                s = str(v).replace("¥", "").replace(",", "").strip()
                if not s:
                    return 0.0
                if s.endswith("%"):
                    try:
                        return float(s.rstrip("%")) / 100
                    except ValueError:
                        return 0.0
                try:
                    return float(s)
                except ValueError:
                    return 0.0

            # マスタ列定義
            m_cols = list(master.columns)
            m_a = m_cols[0] if len(m_cols) > 0 else None       # 商品コード
            m_h = m_cols[7] if len(m_cols) > 7 else None       # 原価
            m_i = m_cols[8] if len(m_cols) > 8 else None       # 手数料(率 or 実数)
            m_j = m_cols[9] if len(m_cols) > 9 else None       # 送料
            m_ae = m_cols[30] if len(m_cols) > 30 else None    # 楽天SKU
            m_af = m_cols[31] if len(m_cols) > 31 else None    # Amazon FBM SKU
            m_ag = m_cols[32] if len(m_cols) > 32 else None    # Amazon FBA SKU

            # ルックアップ辞書: 任意のSKU文字列 → (cost, fee, ship)
            lookup: dict[str, tuple[float, float, float]] = {}
            for _, mr in master.iterrows():
                tup = (_f(mr[m_h]) if m_h else 0,
                       _fee(mr[m_i]) if m_i else 0,
                       _f(mr[m_j]) if m_j else 0)
                for kc in [m_a, m_ae, m_af, m_ag]:
                    if kc is None:
                        continue
                    k = str(mr[kc]).strip()
                    if k and k not in lookup:
                        lookup[k] = tup

            # 補完対象 = 原価/手数料/送料 のいずれかが0、かつ商品コードあり
            target_mask = (
                ((df[COL_COST] == 0) | (df[COL_FEE] == 0) | (df[COL_SHIP] == 0))
                & (df[COL_PRODUCT].astype(str).str.strip() != "")
            )
            target_count = int(target_mask.sum())

            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("売上総行数", f"{len(df):,}")
            cc2.metric("原価=0", f"{target_count:,}")
            cc3.metric("マスタSKU辞書", f"{len(lookup):,}")

            if target_count == 0:
                st.success("✅ 原価=0 の行はありません")
            else:
                # 試算
                hit, miss, miss_codes = [], [], []
                for idx in df[target_mask].index:
                    row = df.loc[idx]
                    code = str(row[COL_PRODUCT]).strip()
                    sku = str(row[COL_SKU]).strip() if COL_SKU else ""
                    # 通常 → SKU → 先頭0除去版 の順で引く
                    m = lookup.get(code) or (lookup.get(sku) if sku else None)
                    if m is None and code.startswith("0"):
                        m = lookup.get(code.lstrip("0"))
                    if m is None and sku.startswith("0"):
                        m = lookup.get(sku.lstrip("0"))
                    if m is None:
                        miss.append(idx)
                        if code not in miss_codes:
                            miss_codes.append(code)
                        continue
                    cost_unit, fee_unit, ship_unit = m
                    qty = _f(row[COL_QTY]) if COL_QTY else 1
                    amount = _f(row[COL_AMOUNT]) if COL_AMOUNT else 0
                    cost = round(cost_unit * qty, 2)
                    fee = round(amount * fee_unit if fee_unit < 1 else fee_unit * qty, 2)
                    ship = round(ship_unit * qty, 2) if ship_unit else 0
                    point = _f(row[COL_POINT]) if COL_POINT else 0
                    coupon = _f(row[COL_COUPON]) if COL_COUPON else 0
                    profit = round(amount - cost - fee - ship - point - coupon, 2)
                    # P列(利益率)はパーセント書式なので0〜1の比率で書込
                    rate = round(profit / amount, 4) if amount > 0 else 0
                    hit.append({
                        "_sheet_row": idx + 2,  # ヘッダ行=1
                        "商品コード": code,
                        "数量": qty,
                        "売上": amount,
                        "原価(計算)": cost,
                        "手数料(計算)": fee,
                        "送料(計算)": ship,
                        "利益額(計算)": profit,
                        "利益率(計算)": rate,
                    })

                hc1, hc2 = st.columns(2)
                hc1.metric("✅ 補完可能", f"{len(hit):,}")
                hc2.metric("⚠ マスタ未登録", f"{len(miss):,}")

                if miss:
                    with st.expander(f"⚠ マスタ未登録の商品コード（先頭{min(50, len(miss_codes))}件）"):
                        st.write(miss_codes[:50])

                if hit:
                    with st.expander(f"📋 補完プレビュー（先頭20件）"):
                        st.dataframe(
                            pd.DataFrame(hit[:20]).drop(columns=["_sheet_row"]),
                            use_container_width=True, hide_index=True,
                            column_config={
                                "売上": st.column_config.NumberColumn(format="¥%d"),
                                "原価(計算)": st.column_config.NumberColumn(format="¥%d"),
                                "手数料(計算)": st.column_config.NumberColumn(format="¥%d"),
                                "送料(計算)": st.column_config.NumberColumn(format="¥%d"),
                                "利益額(計算)": st.column_config.NumberColumn(format="¥%d"),
                                "利益率(計算)": st.column_config.NumberColumn(format="%.1f%%"),
                            },
                        )

                    if st.button(f"🔧 {len(hit)}件 一括補完実行", type="primary",
                                 use_container_width=True, key="refill_run"):
                        with st.spinner(f"{len(hit)}件 書込中..."):
                            try:
                                ss = sheets.get_spreadsheet()
                                ws = ss.worksheet(SHEET_NAME)
                                requests = []
                                for h in hit:
                                    r = h["_sheet_row"]
                                    requests.extend([
                                        {"range": f"J{r}", "values": [[h["原価(計算)"]]]},
                                        {"range": f"K{r}", "values": [[h["手数料(計算)"]]]},
                                        {"range": f"L{r}", "values": [[h["送料(計算)"]]]},
                                        {"range": f"O{r}", "values": [[h["利益額(計算)"]]]},
                                        {"range": f"P{r}", "values": [[h["利益率(計算)"]]]},
                                    ])
                                ws.batch_update(requests, value_input_option="USER_ENTERED")
                                sheets._invalidate_one(SHEET_NAME)
                                st.success(f"✅ {len(hit)}件 補完完了")
                                st.balloons()
                                st.rerun()
                            except Exception as e:
                                st.error(f"補完失敗: {e}")
