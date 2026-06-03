"""
09_大分類別販売集計（Python計算版・キャッシュ高速化）

大分類 × チャネル群（楽天/Amazon） × 月 の3次元集計
+ 月次サマリタブ: 売上/原価/利益/在庫/広告費/ROAS/ACOS
"""
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from lib import sheets, ui

# 楽天広告管理スプシID（毎月「データ可視化YYYY年M月」を新規作成→ここを差し替え＆SAに共有）
RAKUTEN_AD_SS_ID = "16EhgbZz8euBMlvNfGhCz0n5yusahlUob9dLDm2vLwZo"  # データ可視化2026年6月

st.set_page_config(page_title="大分類別販売集計", page_icon="📊", layout="wide")
st.title("📊 大分類別販売集計")
ui.sidebar_common()

# ===========================================================
# 📥 Amazon広告レポート 手動アップロード
# ===========================================================
import json as _json
import subprocess as _sub
import sys as _sys
import tempfile as _tmp
from datetime import datetime as _dt

_AD_CACHE = Path(__file__).resolve().parents[2] / "08_自動実行" / "logs" / "amazon_ad_costs.json"
_IMPORT_SCRIPT = Path(__file__).resolve().parents[2] / "08_自動実行" / "import_amazon_ads.py"


def _ad_cache_info():
    if not _AD_CACHE.exists():
        return None, None
    try:
        data = _json.loads(_AD_CACHE.read_text(encoding="utf-8"))
        ts = data.get("updated_at")
        dt = _dt.fromisoformat(ts) if ts else None
        months = list((data.get("months") or {}).keys())
        return dt, months
    except Exception:
        return None, None


with st.expander("📥 Amazon広告レポート(xlsx) 手動取込", expanded=False):
    cached_dt, cached_months = _ad_cache_info()
    if cached_dt:
        st.caption(f"📊 現在のキャッシュ: 最終取込 {cached_dt:%Y-%m-%d %H:%M} / 月別: {', '.join(cached_months)}")
    else:
        st.caption("📊 現在キャッシュなし")

    st.markdown(
        "Amazon広告コンソール → レポート → **「スポンサープロダクト広告 広告対象商品 レポート」** "
        "(概要レポート) を手動DLしてアップロードしてください。日次は不要。"
    )
    uploaded = st.file_uploader(
        "xlsxを選択",
        type=["xlsx"],
        key="amazon_ad_upload",
    )
    if uploaded:
        # 一時保存
        with _tmp.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name
        st.info(f"📁 {uploaded.name} ({uploaded.size:,} bytes)")

        if st.button("📥 取込実行", type="primary", key="amazon_ad_import_btn"):
            try:
                proc = _sub.run(
                    [_sys.executable, str(_IMPORT_SCRIPT), tmp_path],
                    capture_output=True, text=True, timeout=180,
                    encoding="utf-8", errors="replace",
                )
                if proc.returncode == 0:
                    st.success(f"✅ 取込完了")
                    st.code(proc.stdout, language="text")
                    st.rerun()
                else:
                    st.error(f"❌ 取込失敗 rc={proc.returncode}")
                    st.code((proc.stderr or proc.stdout or "")[:500], language="text")
            except Exception as e:
                st.error(f"❌ 起動失敗: {e}")

st.markdown("---")


# ===========================================================
# 重い前処理をキャッシュ（売上に「大分類」「チャネル群」列を付与）
# ===========================================================
@st.cache_data(ttl=3600, show_spinner="Amazon広告費読込中...")
def _load_amazon_ad_costs(year: int, month: int) -> dict:
    """Amazon広告費キャッシュから指定月のSKU別広告費を取得
    Returns: {SKU: {"ad": 広告費, "ad_sale": 広告経由売上}}
    """
    import json
    from pathlib import Path as _Path
    cache_path = _Path(__file__).resolve().parent.parent.parent / "08_自動実行" / "logs" / "amazon_ad_costs.json"
    if not cache_path.exists():
        return {}
    try:
        d = json.loads(cache_path.read_text(encoding="utf-8"))
        month_key = f"{year}-{month:02d}"
        return d.get("months", {}).get(month_key, {})
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner="楽天広告費取得中...")
def _load_rakuten_ad_costs(year: int, month: int) -> dict:
    """楽天広告費 + 広告経由売上 を取得

    Returns: {SKU: {"ad": 広告費, "ad_sale": 広告経由売上}}

    優先順位:
      1. ローカルキャッシュ (logs/rakuten_ad_costs.json, 朝バッチで更新)
      2. 期間指定2シート直接読込
    """
    import json
    from pathlib import Path as _Path

    # 1) ローカルキャッシュ優先
    cache_path = _Path(__file__).resolve().parent.parent.parent / "08_自動実行" / "logs" / "rakuten_ad_costs.json"
    if cache_path.exists():
        try:
            d = json.loads(cache_path.read_text(encoding="utf-8"))
            if d.get("year") == year and d.get("month") == month:
                # 新形式 sku_data があればそのまま
                if "sku_data" in d:
                    return d["sku_data"]
                # 旧形式 sku_ad しかない場合は ad_sale=0 で変換
                return {k: {"ad": v, "ad_sale": 0} for k, v in d.get("sku_ad", {}).items()}
        except Exception:
            pass

    # 2) フォールバック: スプシ直接読込
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        try:
            sa_info = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(
                sa_info,
                scopes=["https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive"],
            )
        except Exception:
            from lib import config
            creds = Credentials.from_service_account_file(
                str(config.SERVICE_ACCOUNT_JSON),
                scopes=["https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive"],
            )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(RAKUTEN_AD_SS_ID)
        ws = sh.worksheet("期間指定2")
        values = ws.get_all_values()

        sku_data: dict = {}
        target_prefix = f"{year}年{month:02d}月"

        for r in values[7:]:
            if len(r) < 19:
                continue
            period = (r[0] or "").strip()
            if period and not period.startswith(target_prefix):
                continue
            sku = (r[1] or "").strip()
            if not sku:
                continue
            try:
                ad = float(str(r[18]).replace(",", "").replace("¥", "") or 0)
            except (ValueError, TypeError):
                ad = 0
            try:
                ad_sale = float(str(r[6]).replace(",", "").replace("¥", "") or 0)
            except (ValueError, TypeError):
                ad_sale = 0
            if ad > 0 or ad_sale > 0:
                d2 = sku_data.setdefault(sku, {"ad": 0.0, "ad_sale": 0.0})
                d2["ad"] += ad
                d2["ad_sale"] += ad_sale
        return sku_data
    except Exception as e:
        st.warning(f"楽天広告費取得失敗: {e}")
        return {}


@st.cache_data(ttl=1800, show_spinner="売上+マスタ前処理中...")
def _build_enriched_sales(include_archive: bool = True):
    sales = sheets.load_sales(include_archive=include_archive)
    master = sheets.load_master()
    if sales.empty or master.empty:
        return None

    def _col(df, idx):
        return df.columns[idx] if idx < len(df.columns) else None

    DATE_C    = _col(sales, 0)
    CHANNEL_C = _col(sales, 1)
    CODE_C    = _col(sales, 3)
    QTY_C     = _col(sales, 6)
    AMOUNT_C  = _col(sales, 8)
    COST_C    = _col(sales, 9)
    FEE_C     = _col(sales, 10)
    SHIP_C    = _col(sales, 11)
    POINT_C   = _col(sales, 12)  # M列 楽天ポイント費用
    COUPON_C  = _col(sales, 13)  # N列 楽天クーポン費用
    PROFIT_C  = _col(sales, 14)

    M_CODE = master.columns[0]
    M_BIG_CAT = master.columns[3] if len(master.columns) > 3 else None
    M_SUB_CAT = master.columns[4] if len(master.columns) > 4 else None  # E列 小分類

    sales = sales.copy()
    # 日付パース(フォーマット混在対応)
    def _parse_dt(s):
        if pd.isna(s) or str(s).strip() == "":
            return pd.NaT
        s = str(s).strip()
        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return pd.to_datetime(s, format=fmt)
            except (ValueError, TypeError):
                continue
        return pd.to_datetime(s, errors="coerce")
    sales[DATE_C] = sales[DATE_C].apply(_parse_dt)
    sales = sales.dropna(subset=[DATE_C])

    def _to_num(s):
        return pd.to_numeric(s.astype(str).str.replace(",", "").str.replace("¥", ""), errors="coerce").fillna(0)

    for c in [QTY_C, AMOUNT_C, COST_C, FEE_C, SHIP_C, POINT_C, COUPON_C, PROFIT_C]:
        if c and c in sales.columns:
            sales[c] = _to_num(sales[c])

    # マスタから dict 構築
    # A列(商品コード) → 大分類
    # AE列(楽天SKU) / AF列(FBM SKU) / AG列(FBA SKU) も同じ大分類を指すよう登録
    M_AE_X = master.columns[30] if len(master.columns) > 30 else None
    M_AF_X = master.columns[31] if len(master.columns) > 31 else None
    M_AG_X = master.columns[32] if len(master.columns) > 32 else None

    code_to_cat = {}
    code_to_subcat = {}
    if M_BIG_CAT:
        for i, row in master.iterrows():
            code_clean = str(row[M_CODE]).strip()
            cat_clean = str(row[M_BIG_CAT]).strip() if M_BIG_CAT else ""
            cat_val = cat_clean or "(未分類)"
            sub_clean = str(row[M_SUB_CAT]).strip() if M_SUB_CAT else ""
            sub_val = sub_clean or "(未分類)"
            if not code_clean:
                continue
            code_to_cat[code_clean] = cat_val
            code_to_subcat[code_clean] = sub_val
            # AE/AF/AG列の値も同じ大分類/小分類に紐付け(売上管理D列がチャネル別SKUの場合に対応)
            for col_name in (M_AE_X, M_AF_X, M_AG_X):
                if col_name:
                    v = str(row[col_name]).strip()
                    if v and v not in code_to_cat:  # 既に登録済みは上書きしない(A列優先)
                        code_to_cat[v] = cat_val
                        code_to_subcat[v] = sub_val

    sales["_大分類"] = sales[CODE_C].astype(str).str.strip().map(code_to_cat).fillna("(未分類)")
    sales["_小分類"] = sales[CODE_C].astype(str).str.strip().map(code_to_subcat).fillna("(未分類)")

    # チャネル群（vectorized）
    sales["_チャネル群"] = sales[CHANNEL_C].map({
        "楽天": "楽天",
        "Amazon FBA": "Amazon",
        "Amazon FBM": "Amazon",
    }).fillna("その他")

    # 楽天SKU → 商品コード逆引き(マスタAE列)
    rk_sku_to_code = {}
    M_AE = master.columns[30] if len(master.columns) > 30 else None
    if M_AE:
        for code, ae in zip(master[M_CODE].astype(str), master[M_AE].astype(str)):
            ae_clean = ae.strip()
            if ae_clean:
                rk_sku_to_code[ae_clean] = code.strip()

    return {
        "df": sales,
        "DATE_C": DATE_C,
        "CHANNEL_C": CHANNEL_C,
        "CODE_C": CODE_C,
        "QTY_C": QTY_C,
        "AMOUNT_C": AMOUNT_C,
        "COST_C": COST_C,
        "FEE_C": FEE_C,
        "SHIP_C": SHIP_C,
        "POINT_C": POINT_C,
        "COUPON_C": COUPON_C,
        "PROFIT_C": PROFIT_C,
        "code_to_cat": code_to_cat,
        "code_to_subcat": code_to_subcat,
        "rk_sku_to_code": rk_sku_to_code,
    }


# アーカイブを含めるかどうか(過去月を見たい時のみON、軽量化のため初期OFF)
with st.expander("⚙ 詳細設定", expanded=False):
    use_archive = st.checkbox(
        "過去月(アーカイブ)も含めて読込",
        value=False,
        help="OFFだと当月+前2ヶ月のみ。ONだと全期間+アーカイブスプシも読込(遅い)",
    )

_d = _build_enriched_sales(include_archive=use_archive)
if _d is None:
    st.warning("データなし")
    st.stop()

sales    = _d["df"]
DATE_C   = _d["DATE_C"]
QTY_C    = _d["QTY_C"]
AMOUNT_C = _d["AMOUNT_C"]
PROFIT_C = _d["PROFIT_C"]

# ===========================================================
# フィルタ（期間絞りで高速化）
# ===========================================================
with st.expander("🔍 フィルタ", expanded=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        years = sorted(sales[DATE_C].dt.year.unique().tolist(), reverse=True)
        sel_year = st.selectbox("対象年", years, index=0 if years else None)
    with col2:
        # 月の範囲指定で軽量化
        all_months = list(range(1, 13))
        sel_months = st.multiselect(
            "対象月（複数選択可、未選択=全月）",
            all_months,
            default=[],
            help="月を絞ると高速化",
        )
    with col3:
        ch_groups = ["（全て）", "楽天", "Amazon"]
        sel_chg = st.selectbox("チャネル群", ch_groups)

with st.spinner("集計中..."):
    filtered = sales[sales[DATE_C].dt.year == sel_year].copy()
    if sel_months:
        filtered = filtered[filtered[DATE_C].dt.month.isin(sel_months)]
    if sel_chg != "（全て）":
        filtered = filtered[filtered["_チャネル群"] == sel_chg]
    st.caption(f"対象データ: {len(filtered):,}行")

if filtered.empty:
    st.warning("該当データなし")
    st.stop()

# ===========================================================
# 集計
# ===========================================================
filtered["_月"] = filtered[DATE_C].dt.month

# 大分類×月のピボット（売上）
pivot_revenue = filtered.pivot_table(
    index="_大分類",
    columns="_月",
    values=AMOUNT_C,
    aggfunc="sum",
    fill_value=0,
).round(0).astype(int)

pivot_qty = filtered.pivot_table(
    index="_大分類",
    columns="_月",
    values=QTY_C,
    aggfunc="sum",
    fill_value=0,
).astype(int)

pivot_profit = filtered.pivot_table(
    index="_大分類",
    columns="_月",
    values=PROFIT_C,
    aggfunc="sum",
    fill_value=0,
).round(0).astype(int)

# 月名 (1→1月)
pivot_revenue.columns = [f"{c}月" for c in pivot_revenue.columns]
pivot_qty.columns = [f"{c}月" for c in pivot_qty.columns]
pivot_profit.columns = [f"{c}月" for c in pivot_profit.columns]

# 合計列
pivot_revenue["年合計"] = pivot_revenue.sum(axis=1)
pivot_qty["年合計"] = pivot_qty.sum(axis=1)
pivot_profit["年合計"] = pivot_profit.sum(axis=1)

# 並び替え（年合計の降順）
pivot_revenue = pivot_revenue.sort_values("年合計", ascending=False)
pivot_qty = pivot_qty.reindex(pivot_revenue.index)
pivot_profit = pivot_profit.reindex(pivot_revenue.index)

# 合計行
total_rev = pivot_revenue.sum(numeric_only=True)
total_qty = pivot_qty.sum(numeric_only=True)
total_profit = pivot_profit.sum(numeric_only=True)
pivot_revenue.loc["🔵 全カテゴリ合計"] = total_rev
pivot_qty.loc["🔵 全カテゴリ合計"] = total_qty
pivot_profit.loc["🔵 全カテゴリ合計"] = total_profit

# ===========================================================
# 表示（タブ切替）
# ===========================================================
st.markdown(f"### {sel_year}年 大分類別 月推移（{sel_chg}）")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "💰 売上", "📦 数量", "💎 利益", "📈 グラフ", "💼 月次サマリ(広告含む)", "🔬 小分類別利益"
])


def _render_with_pinned_total(df, total_label="🔵 全カテゴリ合計"):
    """合計行をヘッダー直下に固定表示するレイアウト。
    合計を別dataframe(1行)として上に出し、残りデータを下にスクロール表示する。
    """
    if total_label in df.index:
        total_df = df.loc[[total_label]].copy()
        rest_df = df.drop(index=total_label).copy()
    else:
        total_df = None
        rest_df = df.copy()

    if total_df is not None:
        # 合計行: ヘッダ込みで2行ぶんの高さ
        st.dataframe(
            total_df,
            use_container_width=True,
            height=80,  # ヘッダ + 1行
            hide_index=False,
        )
    # 残りデータ: スクロール
    st.dataframe(rest_df, use_container_width=True, height=520, hide_index=False)


with tab1:
    _render_with_pinned_total(pivot_revenue)
with tab2:
    _render_with_pinned_total(pivot_qty)
with tab3:
    _render_with_pinned_total(pivot_profit)
with tab4:
    # 大分類別の年合計売上（Top10）
    top10 = pivot_revenue.drop(index="🔵 全カテゴリ合計").nlargest(10, "年合計")
    st.markdown("#### 売上Top10カテゴリ")
    st.bar_chart(top10["年合計"])

    # 月別合計売上推移
    st.markdown("#### 月別売上推移")
    monthly_total = pivot_revenue.loc["🔵 全カテゴリ合計"].drop("年合計")
    st.line_chart(monthly_total)

# ===========================================================
# 月次サマリタブ
# ===========================================================
with tab5:
    st.caption("月単位の大分類別 売上/原価/利益/広告費/ROAS/ACOS + 在庫数/金額")

    # 月選択(単一月)
    available_months = sorted(filtered["_月"].unique().tolist())
    if not available_months:
        st.warning("対象月なし")
    else:
        summary_month = st.selectbox(
            "対象月",
            available_months,
            index=len(available_months)-1,
            key="summary_month",
        )

        # 楽天広告費取得(管理番号=楽天親SKU別)
        # ※ チャネル群フィルタが「Amazon」だけなら楽天広告費は0扱い
        if sel_chg == "Amazon":
            rk_ad = {}
        else:
            rk_ad = _load_rakuten_ad_costs(sel_year, int(summary_month))
        rk_sku_to_code = _d["rk_sku_to_code"]
        code_to_cat = _d["code_to_cat"]  # 先に取得しておく(以下で使用)

        # 楽天SKU辞書から「manageNumber → 関連する全商品コード」のマップ構築
        # マスタA列(商品コード) と 楽天SKU辞書の完全SKU(fullSKU) が一致するケースが大半
        # (マスタAE列は901/902が空)
        import json as _json
        from pathlib import Path as _P
        parent_to_codes: dict[str, list[str]] = {}
        try:
            rk_dict_path = _P(__file__).resolve().parent.parent.parent / "08_自動実行" / "logs" / "rakuten_sku_dict.json"
            if rk_dict_path.exists():
                d_raw = _json.loads(rk_dict_path.read_text(encoding="utf-8"))
                inner = d_raw.get("dict", d_raw)
                # 各 fullSKU について、それが マスタA列にあるか、AE列にあるかで対応取得
                for full_sku, info in inner.items():
                    parent = info.get("manageNumber", "").strip() if isinstance(info, dict) else ""
                    if not parent:
                        continue
                    # 1) 直接マスタA列に存在?
                    code = None
                    if full_sku in code_to_cat:
                        code = full_sku
                    # 2) AE列(楽天SKU)経由
                    if not code and full_sku in rk_sku_to_code:
                        code = rk_sku_to_code[full_sku]
                    if code:
                        parent_to_codes.setdefault(parent, []).append(code)
        except Exception as _e:
            st.warning(f"⚠ 楽天SKU辞書読込失敗: {_e}")

        # SKU別広告費/広告売上 → 商品コード別 → 大分類別 に集約
        # 親管理番号→子コード複数 の場合、子全員に按分(均等)
        cat_ad: dict[str, float] = {}
        cat_ad_sale: dict[str, float] = {}
        for parent_sku, data in rk_ad.items():
            # 互換: data が float の場合(旧形式)もハンドル
            if isinstance(data, (int, float)):
                ad = float(data)
                ad_sale = 0.0
            else:
                ad = float(data.get("ad", 0))
                ad_sale = float(data.get("ad_sale", 0))

            codes = parent_to_codes.get(parent_sku, [])
            if not codes:
                # 辞書に無い → 親SKU=商品コードと仮定して直接マッチ
                if parent_sku in code_to_cat:
                    c = code_to_cat[parent_sku]
                    cat_ad[c] = cat_ad.get(c, 0) + ad
                    cat_ad_sale[c] = cat_ad_sale.get(c, 0) + ad_sale
                continue
            ad_per = ad / len(codes)
            sale_per = ad_sale / len(codes)
            for code in codes:
                cat = code_to_cat.get(code, "(未分類)")
                cat_ad[cat] = cat_ad.get(cat, 0) + ad_per
                cat_ad_sale[cat] = cat_ad_sale.get(cat, 0) + sale_per

        # Amazon広告費も合算(SKU = FBA SKU、 code_to_cat にマスタAG列経由で登録済)
        # ※ チャネル群フィルタが「楽天」だけならAmazon広告費は0扱い
        if sel_chg == "楽天":
            amz_ad = {}
        else:
            amz_ad = _load_amazon_ad_costs(sel_year, int(summary_month))
        for amz_sku, data in amz_ad.items():
            ad = float(data.get("ad", 0)) if isinstance(data, dict) else float(data)
            ad_sale = float(data.get("ad_sale", 0)) if isinstance(data, dict) else 0
            cat = code_to_cat.get(amz_sku, "(未分類)")
            cat_ad[cat] = cat_ad.get(cat, 0) + ad
            cat_ad_sale[cat] = cat_ad_sale.get(cat, 0) + ad_sale

        # 対象月の売上を大分類別に集計
        m_df = filtered[filtered["_月"] == summary_month]
        agg = m_df.groupby("_大分類").agg(
            売上=(AMOUNT_C, "sum"),
            原価=(_d["COST_C"], "sum"),
            手数料=(_d["FEE_C"], "sum"),
            送料=(_d["SHIP_C"], "sum"),
            ポイント=(_d["POINT_C"], "sum"),
            クーポン=(_d["COUPON_C"], "sum"),
            利益額=(PROFIT_C, "sum"),
            数量=(QTY_C, "sum"),
        ).reset_index()

        # 広告費 / 広告経由売上 を join
        agg["広告費"] = agg["_大分類"].map(cat_ad).fillna(0)
        agg["広告経由売上"] = agg["_大分類"].map(cat_ad_sale).fillna(0)

        # 利益額(O列): 既に売価-原価-手数料-送料-ポイント-クーポン を計算済みなので
        # ここでは追加控除しない(二重控除防止)

        # 広告差し引き利益
        agg["広告後利益"] = agg["利益額"] - agg["広告費"]

        # ROAS = 広告経由売上 ÷ 広告費 × 100 (%表示)
        agg["ROAS"] = agg.apply(
            lambda r: (r["広告経由売上"] / r["広告費"] * 100) if r["広告費"] > 0 else 0,
            axis=1,
        )
        # ACOS = 広告費 ÷ 広告経由売上 × 100 (%表示)
        agg["ACOS"] = agg.apply(
            lambda r: (r["広告費"] / r["広告経由売上"] * 100) if r["広告経由売上"] > 0 else 0,
            axis=1,
        )
        # トータルACOS = 広告費 ÷ 全体売上 × 100
        agg["トータルACOS"] = agg.apply(
            lambda r: (r["広告費"] / r["売上"] * 100) if r["売上"] > 0 else 0,
            axis=1,
        )
        # 利益率 = 利益額 ÷ 売上 × 100
        agg["利益率"] = agg.apply(
            lambda r: (r["利益額"] / r["売上"] * 100) if r["売上"] > 0 else 0,
            axis=1,
        )
        # 広告後利益率 = 広告後利益 ÷ 売上 × 100
        agg["広告後利益率"] = agg.apply(
            lambda r: (r["広告後利益"] / r["売上"] * 100) if r["売上"] > 0 else 0,
            axis=1,
        )

        # 在庫数/在庫金額(マスタ大分類×04のH/K列)
        try:
            inv = sheets.load_inventory()
            master_for_inv = sheets.load_master()
            if not inv.empty and not master_for_inv.empty:
                INV_CODE = inv.columns[0]
                INV_H = inv.columns[7]  # 販売可能合計
                INV_K = inv.columns[10]  # 在庫金額
                M_CODE_I = master_for_inv.columns[0]
                M_BIG_I = master_for_inv.columns[3]

                code_to_cat_for_inv = {}
                for c, x in zip(master_for_inv[M_CODE_I].astype(str), master_for_inv[M_BIG_I].astype(str)):
                    code_to_cat_for_inv[c.strip()] = x.strip() or "(未分類)"

                inv2 = inv.copy()
                inv2["_cat"] = inv2[INV_CODE].astype(str).str.strip().map(code_to_cat_for_inv).fillna("(未分類)")

                def _n(s):
                    return pd.to_numeric(s.astype(str).str.replace(",", "").str.replace("¥", ""), errors="coerce").fillna(0)
                inv2["_qty"] = _n(inv2[INV_H])
                inv2["_amt"] = _n(inv2[INV_K])
                inv_agg = inv2.groupby("_cat").agg(
                    在庫数=("_qty", "sum"),
                    在庫金額=("_amt", "sum"),
                ).reset_index().rename(columns={"_cat": "_大分類"})
                agg = agg.merge(inv_agg, on="_大分類", how="left")
                agg["在庫数"] = agg["在庫数"].fillna(0).astype(int)
                agg["在庫金額"] = agg["在庫金額"].fillna(0).astype(int)
        except Exception as e:
            st.caption(f"⚠ 在庫情報取込失敗: {e}")
            agg["在庫数"] = 0
            agg["在庫金額"] = 0

        # 数値整形
        for c in ["売上","原価","手数料","送料","ポイント","クーポン","利益額","広告費","広告経由売上","広告後利益"]:
            agg[c] = agg[c].round(0).astype(int)
        agg["数量"] = agg["数量"].astype(int)
        agg["ROAS"] = agg["ROAS"].round(2)
        agg["ACOS"] = agg["ACOS"].round(2)
        agg["トータルACOS"] = agg["トータルACOS"].round(2)
        agg["利益率"] = agg["利益率"].round(2)
        agg["広告後利益率"] = agg["広告後利益率"].round(2)

        # 並び替え(売上降順)
        agg = agg.sort_values("売上", ascending=False).reset_index(drop=True)

        # 合計行
        total_row = {
            "_大分類": "🔵 合計",
            "売上": agg["売上"].sum(),
            "原価": agg["原価"].sum(),
            "手数料": agg["手数料"].sum(),
            "送料": agg["送料"].sum(),
            "ポイント": agg["ポイント"].sum(),
            "クーポン": agg["クーポン"].sum(),
            "利益額": agg["利益額"].sum(),
            "広告費": agg["広告費"].sum(),
            "広告経由売上": agg["広告経由売上"].sum(),
            "広告後利益": agg["広告後利益"].sum(),
            "数量": agg["数量"].sum(),
            "在庫数": agg["在庫数"].sum(),
            "在庫金額": agg["在庫金額"].sum(),
        }
        if total_row["広告費"] > 0:
            total_row["ROAS"] = round(total_row["広告経由売上"] / total_row["広告費"] * 100, 2)
        else:
            total_row["ROAS"] = 0
        if total_row["広告経由売上"] > 0:
            total_row["ACOS"] = round(total_row["広告費"] / total_row["広告経由売上"] * 100, 2)
        else:
            total_row["ACOS"] = 0
        if total_row["売上"] > 0:
            total_row["トータルACOS"] = round(total_row["広告費"] / total_row["売上"] * 100, 2)
            total_row["利益率"] = round(total_row["利益額"] / total_row["売上"] * 100, 2)
            total_row["広告後利益率"] = round(total_row["広告後利益"] / total_row["売上"] * 100, 2)
        else:
            total_row["トータルACOS"] = 0
            total_row["利益率"] = 0
            total_row["広告後利益率"] = 0
        agg.loc[len(agg)] = total_row

        # 「合計 / 単価」フォーマット用文字列列を生成
        def _fmt_total_unit(total, qty):
            if qty == 0 or pd.isna(qty):
                return f"¥{int(total):,}"
            unit = int(round(total / qty))
            return f"¥{int(total):,} / ¥{unit:,}"

        for c in ["売上","原価","利益額"]:
            agg[f"{c}_表示"] = agg.apply(lambda r: _fmt_total_unit(r[c], r["数量"]), axis=1)

        # 列順 (表示用文字列に置き換え)
        agg_display = agg.rename(columns={"_大分類": "大分類", "数量": "販売数"}).copy()
        for c in ["売上","原価","利益額"]:
            agg_display[c] = agg_display[f"{c}_表示"]
            agg_display = agg_display.drop(columns=[f"{c}_表示"])

        agg = agg_display[["大分類","販売数","売上","広告経由売上","原価","手数料","送料","ポイント","クーポン",
                   "利益額","利益率","広告費","広告後利益","広告後利益率",
                   "ROAS","ACOS","トータルACOS","在庫数","在庫金額"]]

        # 合計行を切り出して上に固定表示、残りを下にスクロール
        summary_col_config = {
            # 売上/原価/利益額のみ「合計 / 単価」文字列なのでTextColumn
            "売上": st.column_config.TextColumn(width="medium"),
            "原価": st.column_config.TextColumn(width="medium"),
            "利益額": st.column_config.TextColumn(width="medium"),
            # 数値のままの列
            "広告経由売上": st.column_config.NumberColumn(format="¥%d"),
            "広告費": st.column_config.NumberColumn(format="¥%d"),
            "広告後利益": st.column_config.NumberColumn(format="¥%d"),
            "手数料": st.column_config.NumberColumn(format="¥%d"),
            "送料": st.column_config.NumberColumn(format="¥%d"),
            "ポイント": st.column_config.NumberColumn(format="¥%d"),
            "クーポン": st.column_config.NumberColumn(format="¥%d"),
            "在庫金額": st.column_config.NumberColumn(format="¥%d"),
            "ROAS": st.column_config.NumberColumn(format="%.0f%%"),
            "ACOS": st.column_config.NumberColumn(format="%.2f%%"),
            "トータルACOS": st.column_config.NumberColumn(format="%.2f%%"),
            "利益率": st.column_config.NumberColumn(format="%.2f%%"),
            "広告後利益率": st.column_config.NumberColumn(format="%.2f%%"),
        }

        # 🔍 大分類名フィルタ
        _fc1, _fc2 = st.columns([3, 1])
        with _fc1:
            _kw = st.text_input(
                "🔍 大分類名で検索",
                value="",
                placeholder="大分類の名前を入れて絞り込み (空欄で全件)",
                key=f"cat_filter_{summary_month}",
            )
        with _fc2:
            _case_sensitive = st.checkbox("大文字小文字を区別", value=False, key=f"cat_case_{summary_month}")

        if _kw.strip():
            # 合計行は常に残す
            _is_total = agg["大分類"].astype(str).str.contains("合計", na=False)
            if _case_sensitive:
                _hit = agg["大分類"].astype(str).str.contains(_kw, na=False, regex=False)
            else:
                _hit = agg["大分類"].astype(str).str.contains(_kw, case=False, na=False, regex=False)
            agg = agg[_is_total | _hit]
            st.caption(f"🔍 「{_kw}」 ヒット {int((_hit & ~_is_total).sum())}件")

        # 合計行を分離
        total_mask = agg["大分類"].astype(str).str.contains("合計", na=False)
        total_df = agg[total_mask]
        rest_df = agg[~total_mask]

        if not total_df.empty:
            st.dataframe(
                total_df,
                use_container_width=True,
                height=80,  # ヘッダ + 1行ぶん
                hide_index=True,
                column_config=summary_col_config,
            )
        st.dataframe(
            rest_df,
            use_container_width=True,
            height=820,
            hide_index=True,
            column_config=summary_col_config,
        )

        # CSV出力
        csv_sm = agg.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "💾 月次サマリCSV",
            csv_sm,
            file_name=f"category_summary_{sel_year}-{int(summary_month):02d}.csv",
            mime="text/csv",
        )

with tab6:
    st.subheader("🔬 小分類別 販売数〜利益")
    st.caption(
        "選択中の年・月・チャネルでの小分類別集計。"
        "販売数・売上・原価・手数料・送料・ポイント・クーポン・利益額・利益率を表示。"
    )

    if filtered.empty:
        st.info("対象データがありません")
    else:
        sub_agg = filtered.groupby(["_大分類", "_小分類"]).agg(
            販売数=(QTY_C, "sum"),
            売上=(AMOUNT_C, "sum"),
            原価=(_d["COST_C"], "sum"),
            手数料=(_d["FEE_C"], "sum"),
            送料=(_d["SHIP_C"], "sum"),
            ポイント=(_d["POINT_C"], "sum"),
            クーポン=(_d["COUPON_C"], "sum"),
            利益額=(PROFIT_C, "sum"),
        ).reset_index().rename(columns={"_大分類": "大分類", "_小分類": "小分類"})

        # 数値整形
        for c in ["売上", "原価", "手数料", "送料", "ポイント", "クーポン", "利益額"]:
            sub_agg[c] = sub_agg[c].round(0).astype(int)
        sub_agg["販売数"] = sub_agg["販売数"].astype(int)
        sub_agg["利益率"] = sub_agg.apply(
            lambda r: round(r["利益額"] / r["売上"] * 100, 2) if r["売上"] > 0 else 0,
            axis=1,
        )

        sub_agg = sub_agg.sort_values(["売上"], ascending=False).reset_index(drop=True)

        # 合計行
        total_row = {
            "大分類": "🔵 合計",
            "小分類": "",
            "販売数": int(sub_agg["販売数"].sum()),
            "売上": int(sub_agg["売上"].sum()),
            "原価": int(sub_agg["原価"].sum()),
            "手数料": int(sub_agg["手数料"].sum()),
            "送料": int(sub_agg["送料"].sum()),
            "ポイント": int(sub_agg["ポイント"].sum()),
            "クーポン": int(sub_agg["クーポン"].sum()),
            "利益額": int(sub_agg["利益額"].sum()),
        }
        total_row["利益率"] = round(total_row["利益額"] / total_row["売上"] * 100, 2) if total_row["売上"] > 0 else 0
        sub_agg.loc[len(sub_agg)] = total_row

        sub_agg = sub_agg[["大分類", "小分類", "販売数", "売上", "原価", "手数料", "送料",
                           "ポイント", "クーポン", "利益額", "利益率"]]

        sub_col_config = {
            "売上": st.column_config.NumberColumn(format="¥%d"),
            "原価": st.column_config.NumberColumn(format="¥%d"),
            "手数料": st.column_config.NumberColumn(format="¥%d"),
            "送料": st.column_config.NumberColumn(format="¥%d"),
            "ポイント": st.column_config.NumberColumn(format="¥%d"),
            "クーポン": st.column_config.NumberColumn(format="¥%d"),
            "利益額": st.column_config.NumberColumn(format="¥%d"),
            "利益率": st.column_config.NumberColumn(format="%.2f%%"),
        }

        # 🔍 大分類/小分類名フィルタ
        _sc1, _sc2 = st.columns([3, 1])
        with _sc1:
            _skw = st.text_input(
                "🔍 大分類・小分類名で検索",
                value="",
                placeholder="名前を入れて絞り込み (空欄で全件)",
                key="subcat_filter",
            )
        with _sc2:
            _scase = st.checkbox("大文字小文字を区別", value=False, key="subcat_case")

        if _skw.strip():
            _is_total = sub_agg["大分類"].astype(str).str.contains("合計", na=False)
            _hit_big = sub_agg["大分類"].astype(str).str.contains(_skw, case=(not _scase), na=False, regex=False)
            _hit_sub = sub_agg["小分類"].astype(str).str.contains(_skw, case=(not _scase), na=False, regex=False)
            _hit = _hit_big | _hit_sub
            sub_agg = sub_agg[_is_total | _hit]
            st.caption(f"🔍 「{_skw}」 ヒット {int((_hit & ~_is_total).sum())}件")

        # 合計行を分離して上に固定
        _total_mask = sub_agg["大分類"].astype(str).str.contains("合計", na=False)
        _total_df = sub_agg[_total_mask]
        _rest_df = sub_agg[~_total_mask]

        if not _total_df.empty:
            st.dataframe(
                _total_df,
                use_container_width=True,
                height=80,
                hide_index=True,
                column_config=sub_col_config,
            )
        st.dataframe(
            _rest_df,
            use_container_width=True,
            height=620,
            hide_index=True,
            column_config=sub_col_config,
        )

        csv_sub = sub_agg.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "💾 小分類別利益CSV",
            csv_sub,
            file_name=f"subcategory_profit_{sel_year}.csv",
            mime="text/csv",
        )

# CSV
csv = pivot_revenue.to_csv().encode("utf-8-sig")
st.download_button(
    "💾 売上CSV出力",
    csv,
    file_name=f"category_revenue_{sel_year}.csv",
    mime="text/csv",
)
