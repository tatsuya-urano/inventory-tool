"""
🆕 新商品モード

新商品SKUを登録 → 在庫/販売状況を優先表示
少しでも売れたら発注検討アラート
"""
from datetime import date, datetime, timedelta
from io import StringIO

import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="新商品モード", page_icon="🆕", layout="wide")
st.title("🆕 新商品モード")
ui.sidebar_common()

NEW_SHEET = "18_新商品"

# ===========================================================
# シート初期化
# ===========================================================
def _ensure_sheet():
    sh = sheets.get_spreadsheet()
    try:
        ws = sh.worksheet(NEW_SHEET)
    except Exception:
        ws = sh.add_worksheet(title=NEW_SHEET, rows=200, cols=5)
        ws.update("A1:E1", [["SKU", "タイトル(自動)", "登録日", "発注済", "備考"]])
    return ws


# ===========================================================
# データ読込
# ===========================================================
with st.spinner("読み込み中..."):
    new_df = sheets.load_any_sheet(NEW_SHEET, header_row=1, data_start_row=2)
    inv_df = sheets.load_inventory()
    sales_df = sheets.load_sales()
    master_df = sheets.load_master()

if new_df is None or new_df.empty:
    new_df = pd.DataFrame(columns=["SKU", "タイトル(自動)", "登録日", "発注済", "備考"])

# 既存コード集合
master_codes = set()
if not master_df.empty:
    master_codes = set(master_df.iloc[:, 0].astype(str).str.strip()) - {""}
inv_codes = set()
if not inv_df.empty:
    inv_codes = set(inv_df.iloc[:, 0].astype(str).str.strip()) - {""}


def _ensure_master_inv(skus_titles: list[tuple[str, str]]) -> tuple[int, int]:
    """マスタ/04に未登録のSKUを最小列だけ追加。
    skus_titles: [(sku, title), ...]
    return: (master追加数, 04追加数)
    """
    if not skus_titles:
        return 0, 0
    ss = sheets.get_spreadsheet()
    master_added = 0
    inv_added = 0

    # マスタ追加 (A列のみ)
    new_master = [(s, t) for s, t in skus_titles if s not in master_codes]
    if new_master:
        mws = ss.worksheet("03_商品マスタ参照")
        next_r = len(mws.col_values(1)) + 1
        rows = []
        for s, t in new_master:
            row = [""] * 33
            row[0] = s   # A 商品コード
            row[1] = t   # B タイトル
            rows.append(row)
        mws.update(range_name=f"A{next_r}", values=rows, value_input_option="USER_ENTERED")
        sheets._invalidate_one("03_商品マスタ参照")
        master_added = len(new_master)
        master_codes.update(s for s, _ in new_master)

    # 04追加 (A/B/G)
    new_inv = [(s, t) for s, t in skus_titles if s not in inv_codes]
    if new_inv:
        iws = ss.worksheet("04_在庫管理")
        next_r = len(iws.col_values(1)) + 1
        rows = [[s, t, "自社経由"] for s, t in new_inv]
        iws.update(range_name=f"A{next_r}", values=rows, value_input_option="USER_ENTERED")
        sheets._invalidate_one("04_在庫管理")
        inv_added = len(new_inv)
        inv_codes.update(s for s, _ in new_inv)

    return master_added, inv_added

# ===========================================================
# 新商品 追加フォーム
# ===========================================================
st.markdown("### ➕ 新商品を登録")

with st.form("add_new_product", clear_on_submit=True):
    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        new_sku = st.text_input("SKU(商品コード)", "", placeholder="例: gipssandalL")
    with c2:
        new_memo = st.text_input("備考", "")
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("➕ 追加", type="primary", use_container_width=True)

    if submitted and new_sku.strip():
        sku_v = new_sku.strip()
        # 既に登録済みかチェック
        if not new_df.empty and sku_v in new_df.iloc[:, 0].astype(str).str.strip().tolist():
            st.warning(f"⚠ {sku_v} は既に新商品リストに登録済み")
        else:
            ws = _ensure_sheet()
            # 04 or マスタからタイトル取得
            title = ""
            if not inv_df.empty:
                inv_match = inv_df[inv_df.iloc[:, 0].astype(str).str.strip() == sku_v]
                if not inv_match.empty and len(inv_match.columns) > 1:
                    title = str(inv_match.iloc[0, 1])
            if not title and not master_df.empty:
                m_match = master_df[master_df.iloc[:, 0].astype(str).str.strip() == sku_v]
                if not m_match.empty and len(m_match.columns) > 1:
                    title = str(m_match.iloc[0, 1])

            # マスタ/04にも未登録なら追加
            m_add, i_add = _ensure_master_inv([(sku_v, title)])

            # 18_新商品 に追加
            new_row = [sku_v, title, date.today().strftime("%Y-%m-%d"), "", new_memo.strip()]
            ws.append_row(new_row, value_input_option="USER_ENTERED")
            sheets._invalidate_one(NEW_SHEET)

            extra = []
            if m_add:
                extra.append("マスタにも追加")
            if i_add:
                extra.append("04にも追加")
            tail = f" ({' / '.join(extra)})" if extra else ""
            st.success(f"✅ {sku_v} を新商品に登録{tail}")
            st.rerun()

# ===========================================================
# 📥 CSV 一括登録
# ===========================================================
with st.expander("📥 CSV / Excel で一括登録", expanded=False):
    st.caption(
        "1列目に SKU(商品コード) を入れたCSV/Excel/貼付。"
        "タイトルは04から自動取得。重複は自動スキップ。"
    )

    # テンプレダウンロード
    template_df = pd.DataFrame({"SKU": ["例: gipssandalL", "例: NEWITEM-001"], "備考": ["", ""]})
    st.download_button(
        "📄 テンプレCSVダウンロード",
        template_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="newproduct_template.csv",
        mime="text/csv",
    )

    up = st.file_uploader(
        "CSV / TSV / Excel", type=["csv", "tsv", "xlsx", "xls"], key="new_uploader",
    )
    pasted = st.text_area("または貼付(タブ or カンマ区切り、1列目=SKU)", height=100, key="new_paste")

    csv_df = None
    if up is not None:
        try:
            if up.name.lower().endswith((".xlsx", ".xls")):
                csv_df = pd.read_excel(up, dtype=str).fillna("")
            else:
                content = up.read().decode("utf-8-sig", errors="replace")
                first = content.split("\n")[0]
                sep = "\t" if first.count("\t") > first.count(",") else ","
                csv_df = pd.read_csv(StringIO(content), sep=sep, dtype=str).fillna("")
            st.success(f"読込: {len(csv_df)}行")
        except Exception as e:
            st.error(f"読込失敗: {e}")
    elif pasted.strip():
        try:
            first = pasted.split("\n")[0]
            sep = "\t" if first.count("\t") > first.count(",") else ","
            csv_df = pd.read_csv(StringIO(pasted), sep=sep, dtype=str).fillna("")
            # ヘッダなし(1列のみ + 1行目もデータ)対応
            if len(csv_df.columns) == 1 and not csv_df.columns[0].lower().startswith(("sku", "商品", "code")):
                # 1行目もSKU扱いにするため再パース
                lines = [line for line in pasted.strip().split("\n") if line.strip()]
                csv_df = pd.DataFrame({"SKU": lines})
            st.success(f"読込: {len(csv_df)}行")
        except Exception as e:
            st.error(f"読込失敗: {e}")

    if csv_df is not None and not csv_df.empty:
        # SKU列推定 (1列目)
        sku_col = csv_df.columns[0]
        memo_col = csv_df.columns[1] if len(csv_df.columns) > 1 else None

        csv_df[sku_col] = csv_df[sku_col].astype(str).str.strip()
        csv_df = csv_df[csv_df[sku_col] != ""].reset_index(drop=True)

        # 重複判定
        existing = set()
        if not new_df.empty:
            existing = set(new_df.iloc[:, 0].astype(str).str.strip().tolist())
        is_dup = csv_df[sku_col].isin(existing)
        new_count = int((~is_dup).sum())
        dup_count = int(is_dup.sum())

        c1m, c2m, c3m = st.columns(3)
        c1m.metric("CSV総行数", len(csv_df))
        c2m.metric("✅ 新規", new_count)
        c3m.metric("⚠ 重複", dup_count)

        if new_count > 0:
            preview = csv_df[~is_dup].head(10)
            st.markdown("**プレビュー(先頭10件)**")
            st.dataframe(preview, use_container_width=True, hide_index=True)

            if st.button(f"📤 {new_count}件を新商品リストに登録", type="primary",
                         use_container_width=True, key="csv_new_register"):
                with st.spinner("登録中..."):
                    try:
                        ws = _ensure_sheet()
                        today = date.today().strftime("%Y-%m-%d")
                        # タイトル逆引き (04 → master)
                        title_map = {}
                        if not inv_df.empty:
                            for _, ir in inv_df.iterrows():
                                code = str(ir.iloc[0]).strip()
                                if code and len(inv_df.columns) > 1:
                                    title_map[code] = str(ir.iloc[1])
                        if not master_df.empty:
                            for _, mr in master_df.iterrows():
                                code = str(mr.iloc[0]).strip()
                                if code and code not in title_map and len(master_df.columns) > 1:
                                    title_map[code] = str(mr.iloc[1])

                        rows = []
                        sku_title_pairs = []
                        for _, r in csv_df[~is_dup].iterrows():
                            sku_val = str(r[sku_col]).strip()
                            memo = str(r[memo_col]).strip() if memo_col else ""
                            t = title_map.get(sku_val, "")
                            rows.append([sku_val, t, today, "", memo])
                            sku_title_pairs.append((sku_val, t))

                        # マスタ/04にも未登録なら追加
                        m_add, i_add = _ensure_master_inv(sku_title_pairs)

                        if rows:
                            next_row = len(ws.col_values(1)) + 1
                            ws.update(
                                range_name=f"A{next_row}",
                                values=rows,
                                value_input_option="USER_ENTERED",
                            )
                            sheets._invalidate_one(NEW_SHEET)
                        msg = f"✅ {len(rows)}件登録"
                        if m_add:
                            msg += f" / マスタ{m_add}件追加"
                        if i_add:
                            msg += f" / 04に{i_add}件追加"
                        if dup_count:
                            msg += f" / {dup_count}件スキップ"
                        st.success(msg)
                        st.balloons()
                        st.rerun()
                    except Exception as e:
                        st.error(f"登録失敗: {e}")
                        import traceback
                        st.code(traceback.format_exc())

st.markdown("---")

# ===========================================================
# 新商品リスト表示 (優先情報をJOIN)
# ===========================================================
st.markdown(f"### 📊 新商品リスト ({len(new_df)}件)")

if new_df.empty:
    st.info("新商品が登録されていません")
    st.stop()


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("¥", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


# 30日以内の売上をSKU別集計
sku_recent_sales: dict[str, dict] = {}
if not sales_df.empty:
    cutoff = datetime.now() - timedelta(days=30)
    date_col = sales_df.columns[0]
    sku_col = sales_df.columns[3]
    qty_col = sales_df.columns[6]
    amt_col = sales_df.columns[8]

    sales_df["_date_parsed"] = pd.to_datetime(sales_df[date_col], errors="coerce")
    recent = sales_df[sales_df["_date_parsed"] >= cutoff]
    for _, r in recent.iterrows():
        sku = str(r[sku_col]).strip()
        if not sku:
            continue
        info = sku_recent_sales.setdefault(sku, {"30日販売": 0, "30日売上": 0})
        info["30日販売"] += _f(r[qty_col])
        info["30日売上"] += _f(r[amt_col])

# 04 在庫情報マップ
inv_map: dict[str, dict] = {}
if not inv_df.empty:
    for _, r in inv_df.iterrows():
        code = str(r.iloc[0]).strip()
        if not code:
            continue
        inv_map[code] = {
            "FBA在庫": _f(r.iloc[3]) if len(r) > 3 else 0,
            "自社倉庫": _f(r.iloc[5]) if len(r) > 5 else 0,
            "販売可能合計": _f(r.iloc[7]) if len(r) > 7 else 0,
            "発注済": _f(r.iloc[11]) if len(r) > 11 else 0,
            "推奨発注": _f(r.iloc[12]) if len(r) > 12 else 0,
            "ステータス": str(r.iloc[19]) if len(r) > 19 else "",
        }

# マスタ AE/AF/AG → A列(商品コード) 逆引きマップ
# 18にFBA SKU/楽天SKU/FBM SKU を登録した場合に商品コードへ正規化
sku_to_code: dict[str, str] = {}
if not master_df.empty:
    for _, mr in master_df.iterrows():
        code = str(mr.iloc[0]).strip()
        if not code:
            continue
        sku_to_code[code] = code  # 自身
        for col_idx in (30, 31, 32):  # AE, AF, AG
            if len(mr) > col_idx:
                alt = str(mr.iloc[col_idx]).strip()
                if alt and alt not in sku_to_code:
                    sku_to_code[alt] = code

# 表示用テーブル構築
display_rows = []
sku_first_col = new_df.columns[0]
title_col = new_df.columns[1] if len(new_df.columns) > 1 else None
date_col_n = new_df.columns[2] if len(new_df.columns) > 2 else None
memo_col = new_df.columns[4] if len(new_df.columns) > 4 else None

for _, r in new_df.iterrows():
    sku = str(r[sku_first_col]).strip()
    if not sku:
        continue
    # マスタAE/AF/AG経由で商品コードに正規化してから04参照
    code = sku_to_code.get(sku, sku)
    inv = inv_map.get(code, {})
    sales = sku_recent_sales.get(sku, {"30日販売": 0, "30日売上": 0})
    days = ""
    if date_col_n:
        try:
            reg_d = datetime.strptime(str(r[date_col_n]), "%Y-%m-%d")
            days = (datetime.now() - reg_d).days
        except (ValueError, TypeError):
            pass
    qty30 = sales["30日販売"]
    # 発注検討フラグ
    flag = ""
    if qty30 > 0:
        flag = "🔥 発注検討"
    elif inv.get("販売可能合計", 0) <= 0:
        flag = "⚪ 在庫切れ"
    elif days != "" and days >= 30:
        flag = "⌛ 30日経過(売上なし)"

    display_rows.append({
        "🔥": flag,
        "SKU": sku,
        "タイトル": r[title_col] if title_col else "",
        "登録日": r[date_col_n] if date_col_n else "",
        "経過日": days,
        "FBA": int(inv.get("FBA在庫", 0)),
        "自社": int(inv.get("自社倉庫", 0)),
        "販売可能": int(inv.get("販売可能合計", 0)),
        "30日販売": int(qty30),
        "30日売上": int(sales["30日売上"]),
        "発注済": int(inv.get("発注済", 0)),
        "推奨発注": int(inv.get("推奨発注", 0)),
        "ステータス": inv.get("ステータス", ""),
        "備考": r[memo_col] if memo_col else "",
    })

display_df = pd.DataFrame(display_rows)

# 発注検討を上に
display_df = display_df.sort_values(
    by="🔥",
    key=lambda s: s.map({"🔥 発注検討": 0, "⚪ 在庫切れ": 1, "⌛ 30日経過(売上なし)": 2, "": 3}).fillna(9),
)

# 3か月(90日)経過 = 卒業候補
expired_mask = display_df["経過日"].apply(lambda x: isinstance(x, int) and x >= 90)
expired_df = display_df[expired_mask].copy()

# サマリ
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("総新商品数", len(display_df))
c2.metric("🔥 発注検討", (display_df["🔥"] == "🔥 発注検討").sum())
c3.metric("⚪ 在庫切れ", (display_df["🔥"] == "⚪ 在庫切れ").sum())
c4.metric("⏰ 3か月経過", len(expired_df))
c5.metric("30日合計売上", f"¥{int(display_df['30日売上'].sum()):,}")

# ===========================================================
# 🚨 3か月経過アラーム + 卒業処理
# ===========================================================
if not expired_df.empty:
    st.warning(
        f"🚨 {len(expired_df)}件のSKUが登録から3か月経過しました。"
        f"新商品リストから卒業させましょう"
    )
    with st.expander(f"⏰ 3か月経過SKU 一覧 ({len(expired_df)}件) — 許可で削除", expanded=True):
        st.dataframe(
            expired_df[["SKU", "タイトル", "登録日", "経過日", "FBA", "自社", "販売可能",
                        "30日販売", "30日売上", "備考"]],
            use_container_width=True, hide_index=True,
        )

        # レポートCSV
        report_csv = expired_df.to_csv(index=False).encode("utf-8-sig")
        rc1, rc2 = st.columns(2)
        rc1.download_button(
            "📄 レポートCSV出力",
            report_csv,
            file_name=f"new_product_expired_{date.today().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        # 許可削除ボタン
        confirm = rc2.checkbox("☑ 削除を許可する", key="confirm_expired_delete")
        if rc2.button("🗑 許可して削除実行", disabled=not confirm,
                      type="primary", use_container_width=True, key="delete_expired"):
            with st.spinner("削除中..."):
                expired_skus = set(expired_df["SKU"].tolist())
                ws = sheets.get_spreadsheet().worksheet(NEW_SHEET)
                all_v = ws.get_all_values()
                kept = [all_v[0]]
                for row in all_v[1:]:
                    if row and row[0].strip() not in expired_skus:
                        kept.append(row)
                ws.clear()
                ws.update("A1", kept, value_input_option="USER_ENTERED")
                sheets._invalidate_one(NEW_SHEET)
                st.success(f"✅ {len(expired_skus)}件を新商品リストから卒業させました")
                st.rerun()

st.markdown("---")
st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    height=600,
    column_config={
        "30日売上": st.column_config.NumberColumn(format="¥%d"),
    },
)

# ===========================================================
# 削除 (新商品から外す)
# ===========================================================
st.markdown("---")
with st.expander("🗑 新商品から外す"):
    sku_options = display_df["SKU"].tolist()
    to_remove = st.multiselect("外すSKUを選択", sku_options)
    if st.button("削除実行", disabled=not to_remove):
        ws = sheets.get_spreadsheet().worksheet(NEW_SHEET)
        all_v = ws.get_all_values()
        new_data = [all_v[0]]  # ヘッダ
        for row in all_v[1:]:
            if row and row[0].strip() not in to_remove:
                new_data.append(row)
        ws.clear()
        ws.update("A1", new_data, value_input_option="USER_ENTERED")
        sheets._invalidate_one(NEW_SHEET)
        st.success(f"✅ {len(to_remove)}件削除")
        st.rerun()
