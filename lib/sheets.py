"""
Google Sheets 接続・読み取り共通モジュール

設計方針:
- 各シートを個別に @st.cache_data でキャッシュ
- 書き込み時は対象シートのキャッシュだけ無効化（他シートは触らない）
- preload_all_sheets はオプション（手動で全シート読み込み）
- ディスクキャッシュ層: Streamlit再起動後の初回読込を高速化
"""
import json
import re
import time
from pathlib import Path

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from . import config

# ディスクキャッシュ保存先
_DISK_CACHE_DIR = Path(__file__).resolve().parent.parent / ".streamlit" / "sheet_cache"
# ディスクキャッシュTTL: 6時間。これを超えたら古い扱い、API再取得を試みる
_DISK_CACHE_TTL_SEC = 6 * 3600


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-_]", "_", name) + ".json"


def _disk_cache_load(sheet_name: str) -> tuple[list[list[str]] | None, float]:
    """戻り値: (values, age_sec)。なければ (None, inf)"""
    p = _DISK_CACHE_DIR / _safe_filename(sheet_name)
    if not p.exists():
        return None, float("inf")
    try:
        age = time.time() - p.stat().st_mtime
        with p.open("r", encoding="utf-8") as f:
            return json.load(f), age
    except Exception:
        return None, float("inf")


def _disk_cache_save(sheet_name: str, values: list[list[str]]) -> None:
    try:
        _DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _DISK_CACHE_DIR / _safe_filename(sheet_name)
        with p.open("w", encoding="utf-8") as f:
            json.dump(values, f, ensure_ascii=False)
    except Exception:
        pass  # キャッシュ保存失敗は致命的ではない


def _disk_cache_delete(sheet_name: str) -> None:
    try:
        p = _DISK_CACHE_DIR / _safe_filename(sheet_name)
        if p.exists():
            p.unlink()
    except Exception:
        pass


@st.cache_resource
def get_client() -> gspread.Client:
    """サービスアカウント認証で gspread クライアント取得。
    ローカル: .streamlit/service_account.json があればそれを使用
    Streamlit Cloud: st.secrets["gcp_service_account"] から読む
    """
    # ローカルJSONファイル優先
    if config.SERVICE_ACCOUNT_JSON.exists():
        creds = Credentials.from_service_account_file(
            str(config.SERVICE_ACCOUNT_JSON), scopes=config.SCOPES
        )
        return gspread.authorize(creds)

    # Streamlit Cloud: secrets から読む
    try:
        sa_info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(sa_info, scopes=config.SCOPES)
        return gspread.authorize(creds)
    except (KeyError, FileNotFoundError):
        pass

    st.error(
        "認証情報が見つかりません。\n\n"
        "ローカル: .streamlit/service_account.json を配置してください\n"
        "クラウド: Settings → Secrets で [gcp_service_account] を設定してください"
    )
    st.stop()


@st.cache_resource
def get_spreadsheet():
    """対象スプレッドシートをopen"""
    gc = get_client()
    try:
        return gc.open_by_key(config.SPREADSHEET_ID)
    except gspread.exceptions.APIError as e:
        st.error(f"スプレッドシート取得失敗: {e}")
        st.stop()


# ============================================================
# 内部ヘルパ
# ============================================================
def _detect_header_row(all_values, expected_keywords, scan_rows=15):
    """ヘッダ行を自動検出"""
    for i in range(min(scan_rows, len(all_values))):
        row = all_values[i]
        joined = "|".join(str(c) for c in row)
        for kw in expected_keywords:
            if kw in joined:
                return i + 1
    return None


def _dedupe_columns(columns):
    """重複列名を一意化"""
    seen = {}
    out = []
    for i, c in enumerate(columns):
        name = str(c).strip() if c else f"col_{i}"
        if not name:
            name = f"col_{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def _values_to_df(all_values, header_row, data_start_row, auto_detect_keywords=None):
    """値リスト → DataFrame"""
    if not all_values:
        return pd.DataFrame()

    if header_row is None and auto_detect_keywords:
        detected = _detect_header_row(all_values, auto_detect_keywords)
        if detected is None:
            return pd.DataFrame()
        header_row = detected
        data_start_row = detected + 1

    if len(all_values) < data_start_row:
        return pd.DataFrame()

    header = _dedupe_columns(all_values[header_row - 1])
    data = all_values[data_start_row - 1:]
    df = pd.DataFrame(data, columns=header)
    if len(df.columns) > 0:
        df = df[df.iloc[:, 0].astype(str).str.strip() != ""]
    return df.reset_index(drop=True)


# ============================================================
# シート別ロード関数（各々個別にキャッシュ）
# ============================================================
@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def _fetch_raw(sheet_name: str):
    """シート1枚を取得(メモリキャッシュのみ。ディスクキャッシュは使わない)

    ディスクキャッシュは古いARRAYFORMULA計算結果を保持してしまう副作用があるため無効化。
    APIエラー時の保険として、ディスクキャッシュは「フォールバック用」だけ残す。

    503等の一時エラーは指数バックオフでリトライ。
    """
    import time as _time
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        return None

    last_exc = None
    for attempt in range(4):
        try:
            values = ws.get_all_values()
            _disk_cache_save(sheet_name, values)
            return values
        except gspread.exceptions.APIError as e:
            last_exc = e
            status = getattr(e, "response", None) and getattr(e.response, "status_code", None)
            if status in (429, 500, 502, 503, 504):
                _time.sleep(min(2 ** attempt * 2, 8))  # 2, 4, 8, 8秒(最大22秒)
                continue
            break
        except Exception as e:
            last_exc = e
            break

    # 全リトライ失敗 → 古いディスクキャッシュをフォールバック
    disk_values, _ = _disk_cache_load(sheet_name)
    if disk_values is not None:
        return disk_values
    raise last_exc


@st.cache_data(ttl=config.CACHE_TTL_SECONDS)
def load_inventory() -> pd.DataFrame:
    """04_在庫管理"""
    values = _fetch_raw(config.SHEET_INVENTORY)
    return _values_to_df(values, config.INV_HEADER_ROW, config.INV_DATA_START)


@st.cache_data(ttl=config.CACHE_TTL_SECONDS)
def load_inventory_snapshot() -> pd.DataFrame:
    """04_在庫スナップ(家PCバッチが焼く数式ゼロの軽量スナップ)を読む。

    04_在庫管理はTODAY()依存の重い数式で読込に8分半かかるため、表示用はこの
    スナップ(0.4秒)を使う。列: 商品コード/タイトル/自社倉庫/月初在庫/ステータス/
    在庫日数/推奨発注数/小分類/販売チャネル。ヘッダ行1・データ2行目〜。
    スナップ未生成(バッチ未実行)なら空DataFrameを返す→呼び出し側でフォールバック。
    """
    values = _fetch_raw(config.SHEET_INV_SNAPSHOT)
    if not values:
        return pd.DataFrame()
    return _values_to_df(values, 1, 2)


@st.cache_data(ttl=config.CACHE_TTL_SECONDS)
def load_sales(include_archive: bool = False) -> pd.DataFrame:
    """05_売上管理 を読込

    シート構造:
      行1: タイトル
      行2: ↓ 7行目から実データ の説明
      行3-6: サマリブロック
      行7以降: データ
    ヘッダー列名はコード内で固定定義(スプシ2行目を参照しない)

    include_archive=True の場合、月別アーカイブシート (05_売上_YYYY-MM) も
    自動で結合して返す。月次サマリや過去履歴を見るページで使う。
    """
    SALES_COLUMNS = [
        "日付", "モール", "注文番号", "商品コード", "商品名", "SKU",
        "数量", "単価", "売上", "原価", "手数料", "送料",
        "楽天ポイント費用", "楽天クーポン費用", "利益額", "利益率", "備考",
    ]
    values = _fetch_raw(config.SHEET_SALES)
    if not values or len(values) < 8:
        df = pd.DataFrame(columns=SALES_COLUMNS)
    else:
        # 8行目以降(0-indexedで7以降)を読み込み (7行目はデータヘッダー)
        data = values[7:]
        # 列数を揃える
        max_cols = max(len(SALES_COLUMNS), max((len(r) for r in data), default=0))
        cols = SALES_COLUMNS + [f"col_{i}" for i in range(len(SALES_COLUMNS), max_cols)]
        normalized = [r + [""] * (max_cols - len(r)) for r in data]
        df = pd.DataFrame(normalized, columns=cols[:max_cols])
        # 日付列が空の行を除外
        if "日付" in df.columns:
            df = df[df["日付"].astype(str).str.strip() != ""]
        df = df.reset_index(drop=True)
    if not include_archive:
        return df

    # メインスプシ内のアーカイブシート列挙
    try:
        sh = get_spreadsheet()
        archive_names = sorted([
            ws.title for ws in sh.worksheets()
            if ws.title.startswith("05_売上_") and ws.title != config.SHEET_SALES
        ])
    except Exception:
        archive_names = []

    dfs = [df] if not df.empty else []
    for name in archive_names:
        try:
            arc_values = _fetch_raw(name)
            if not arc_values or len(arc_values) < 2:
                continue
            arc_data = arc_values[1:]
            max_cols = max(len(SALES_COLUMNS), max((len(r) for r in arc_data), default=0))
            cols = SALES_COLUMNS + [f"col_{i}" for i in range(len(SALES_COLUMNS), max_cols)]
            arc_norm = [r + [""] * (max_cols - len(r)) for r in arc_data]
            arc_df = pd.DataFrame(arc_norm, columns=cols[:max_cols])
            if "日付" in arc_df.columns:
                arc_df = arc_df[arc_df["日付"].astype(str).str.strip() != ""]
            if not arc_df.empty:
                dfs.append(arc_df.reset_index(drop=True))
        except Exception:
            continue

    # 別スプシのアーカイブも読込
    try:
        archive_ss_id = st.secrets.get("archive", {}).get("sales_spreadsheet_id", "")
    except Exception:
        archive_ss_id = ""
    if archive_ss_id:
        try:
            gc = get_client()
            arc_sh = gc.open_by_key(archive_ss_id)
            for ws in arc_sh.worksheets():
                if not ws.title.startswith("05_売上_"):
                    continue
                try:
                    arc_values = ws.get_all_values()
                except Exception:
                    continue
                if not arc_values or len(arc_values) < 2:
                    continue
                arc_data = arc_values[1:]
                max_cols = max(len(SALES_COLUMNS), max((len(r) for r in arc_data), default=0))
                cols = SALES_COLUMNS + [f"col_{i}" for i in range(len(SALES_COLUMNS), max_cols)]
                arc_norm = [r + [""] * (max_cols - len(r)) for r in arc_data]
                arc_df = pd.DataFrame(arc_norm, columns=cols[:max_cols])
                if "日付" in arc_df.columns:
                    arc_df = arc_df[arc_df["日付"].astype(str).str.strip() != ""]
                if not arc_df.empty:
                    dfs.append(arc_df.reset_index(drop=True))
        except Exception:
            pass

    if not dfs:
        return df
    if len(dfs) == 1:
        return dfs[0]
    # 列を揃えてconcat
    merged = pd.concat(dfs, ignore_index=True, sort=False)
    return merged


@st.cache_data(ttl=config.CACHE_TTL_SECONDS)
def load_master() -> pd.DataFrame:
    """03_商品マスタ参照"""
    values = _fetch_raw(config.SHEET_PRODUCT_MASTER)
    return _values_to_df(values, 6, 7)


@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def load_any_sheet(
    sheet_name: str,
    header_row: int = 1,
    data_start_row: int = 2,
    auto_detect: bool = False,
) -> pd.DataFrame:
    """任意シートを DataFrame として読み込み（引数別キャッシュ）"""
    values = _fetch_raw(sheet_name)
    if not values:
        return pd.DataFrame()
    if auto_detect:
        return _values_to_df(values, None, None,
                             auto_detect_keywords=["日付", "商品コード", "SKU", "ステータス"])
    return _values_to_df(values, header_row, data_start_row)


@st.cache_data(ttl=config.CACHE_TTL_SECONDS)
def list_all_sheets() -> list:
    """シート名一覧"""
    sh = get_spreadsheet()
    return [ws.title for ws in sh.worksheets()]


def preload_all_sheets():
    """全シート一括取得 → 各 _fetch_raw キャッシュに格納（高速化用、オプション）"""
    sh = get_spreadsheet()
    worksheets = sh.worksheets()
    sheet_names = [ws.title for ws in worksheets]
    ranges = [f"'{name}'!A1:ZZ" for name in sheet_names]
    try:
        results = sh.values_batch_get(ranges)
        value_ranges = results.get("valueRanges", [])
    except Exception:
        value_ranges = [{"values": ws.get_all_values()} for ws in worksheets]

    loaded = {}
    for name, vr in zip(sheet_names, value_ranges):
        loaded[name] = vr.get("values", [])
    return loaded


# ============================================================
# キャッシュ管理
# ============================================================
def clear_all_caches():
    """全キャッシュクリア（重い、緊急時のみ）

    ディスクキャッシュも全削除
    """
    st.cache_data.clear()
    # ディスクキャッシュ全削除
    try:
        if _DISK_CACHE_DIR.exists():
            for f in _DISK_CACHE_DIR.glob("*.json"):
                try:
                    f.unlink()
                except Exception:
                    pass
    except Exception:
        pass


def refresh_sheet(sheet_name: str):
    """指定シート1枚だけ強制再取得（他のシートは保持）

    重要: ディスクキャッシュも削除して、確実にAPIから最新取得させる
    """
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        return False

    # ディスクキャッシュ削除(これが無いと古いデータが残る)
    _disk_cache_delete(sheet_name)

    # メモリキャッシュもクリア
    _fetch_raw.clear()
    if sheet_name == config.SHEET_INVENTORY:
        load_inventory.clear()
    elif sheet_name == config.SHEET_SALES:
        load_sales.clear()
    elif sheet_name == config.SHEET_PRODUCT_MASTER:
        load_master.clear()
    load_any_sheet.clear()
    return True


# ============================================================
# 書き込み系
# ============================================================
def _invalidate_one(sheet_name: str):
    """書き込み後: 対象シート関連のキャッシュだけクリア（ディスクキャッシュも削除）"""
    # _fetch_raw はclear()で全エントリ消えてしまうが、これは仕方ない（次回各 load で個別再取得）
    # ただし、書き込みされてないシートのload結果は変わらないので、load関数を個別clear
    if sheet_name == config.SHEET_INVENTORY:
        load_inventory.clear()
    elif sheet_name == config.SHEET_SALES:
        load_sales.clear()
    elif sheet_name == config.SHEET_PRODUCT_MASTER:
        load_master.clear()
    # _fetch_raw の特定キーだけクリアするAPIがないので諦める
    # → 書込後の最初の各シート読込のみ若干遅くなる（許容）
    _fetch_raw.clear()
    load_any_sheet.clear()
    # ディスクキャッシュも削除して次回はAPI再取得を強制
    _disk_cache_delete(sheet_name)


# ============================================================
# 数式列ガード: ARRAYFORMULA保護
# ============================================================
# 各シートで「絶対に書込してはいけない数式列」(1-indexed列番号)
# これらの列に書き込もうとするとARRAYFORMULAが破壊されるため、自動で除外する
PROTECTED_COLS: dict[str, set[int]] = {
    "04_在庫管理": {6, 8, 11, 13, 18, 19, 20, 21},  # F, H, K, M, R, S, T, U
    "03_商品マスタ参照": {8, 12, 13, 30},            # H, L, M, AD
}


def _is_protected(sheet_name: str, range_a1: str) -> bool:
    """A1記法のレンジが保護列に該当するか判定"""
    protected = PROTECTED_COLS.get(sheet_name)
    if not protected:
        return False
    import re
    # "A7" or "A7:B10" → 列番号抽出
    m = re.match(r"([A-Z]+)\d", range_a1)
    if not m:
        return False
    col_letters = m.group(1)
    # 列文字列→1-indexed数値
    col_num = 0
    for c in col_letters:
        col_num = col_num * 26 + (ord(c) - ord('A') + 1)
    return col_num in protected


def filter_protected_requests(sheet_name: str, requests: list[dict]) -> tuple[list[dict], list[str]]:
    """batch_update用 requests から保護列を除外。
    Returns: (filtered_requests, removed_ranges)
    """
    filtered = []
    removed = []
    for req in requests:
        rng = req.get("range", "")
        if _is_protected(sheet_name, rng):
            removed.append(rng)
        else:
            filtered.append(req)
    return filtered, removed


def safe_batch_update(ws, requests: list[dict], **kwargs) -> int:
    """ARRAYFORMULA保護付きの batch_update。
    保護列への書込はスキップしてログ出力。
    Returns: 実際に書き込んだ件数
    """
    sheet_name = ws.title
    filtered, removed = filter_protected_requests(sheet_name, requests)
    if removed:
        import streamlit as st
        st.warning(
            f"⚠ 数式列保護: {sheet_name} の {len(removed)}件を書込スキップ "
            f"(例: {removed[:3]}). ARRAYFORMULA保護のため。"
        )
    if filtered:
        ws.batch_update(filtered, **kwargs)
    return len(filtered)


def write_cell(sheet_name: str, row: int, col: int, value):
    """単一セル書込

    USER_ENTERED で書込 → 数値文字列はちゃんと数値として保存される
    """
    sh = get_spreadsheet()
    ws = sh.worksheet(sheet_name)
    cell_addr = f"{_col_index_to_letter(col)}{row}"
    ws.update(range_name=cell_addr, values=[[value]], value_input_option="USER_ENTERED")
    _invalidate_one(sheet_name)


def write_range(sheet_name: str, start_row: int, start_col: int, values_2d):
    sh = get_spreadsheet()
    ws = sh.worksheet(sheet_name)
    rows = len(values_2d)
    cols = len(values_2d[0]) if rows > 0 else 0
    if rows == 0 or cols == 0:
        return
    end_row = start_row + rows - 1
    end_col_letter = _col_index_to_letter(start_col + cols - 1)
    start_col_letter = _col_index_to_letter(start_col)
    range_str = f"{start_col_letter}{start_row}:{end_col_letter}{end_row}"
    ws.update(range_name=range_str, values=values_2d, value_input_option="USER_ENTERED")
    _invalidate_one(sheet_name)


def append_rows(sheet_name: str, values_2d):
    sh = get_spreadsheet()
    ws = sh.worksheet(sheet_name)
    ws.append_rows(values_2d, value_input_option="USER_ENTERED")
    _invalidate_one(sheet_name)


def replace_sheet_data(sheet_name: str, df: pd.DataFrame, header_row: int = 1, data_start_row: int = 2):
    sh = get_spreadsheet()
    ws = sh.worksheet(sheet_name)
    last_row = ws.row_count
    last_col = ws.col_count
    if last_row >= data_start_row:
        clear_range = f"A{data_start_row}:{_col_index_to_letter(last_col)}{last_row}"
        ws.batch_clear([clear_range])
    if df.empty:
        _invalidate_one(sheet_name)
        return
    values = [df.columns.tolist()] if header_row else []
    values.extend(df.fillna("").astype(str).values.tolist())
    if header_row:
        ws.update(range_name=f"A{header_row}", values=values, value_input_option="USER_ENTERED")
    else:
        ws.update(range_name=f"A{data_start_row}",
                  values=df.fillna("").astype(str).values.tolist(),
                  value_input_option="USER_ENTERED")
    _invalidate_one(sheet_name)


def create_or_replace_sheet(sheet_name: str, df: pd.DataFrame, include_header: bool = True):
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(sheet_name)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(
            title=sheet_name,
            rows=max(len(df) + 10, 100),
            cols=max(len(df.columns) + 5, 26),
        )
    if df.empty:
        return ws
    values = []
    if include_header:
        values.append(df.columns.tolist())
    values.extend(df.fillna("").astype(str).values.tolist())
    ws.update(range_name="A1", values=values, value_input_option="USER_ENTERED")
    _invalidate_one(sheet_name)
    return ws


# ============================================================
# ヘルパ
# ============================================================
def _col_index_to_letter(idx: int) -> str:
    """1-indexed の列番号を A1記法に"""
    result = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        result = chr(65 + rem) + result
    return result


def find_col(df, candidates):
    """候補列名から最初に一致するものを返す（部分一致）"""
    for cand in candidates:
        for col in df.columns:
            if cand in str(col):
                return col
    return None


def build_row_by_header(df_columns, value_map):
    """実ヘッダ順に値を組み立てる"""
    return [value_map.get(col, "") for col in df_columns]
