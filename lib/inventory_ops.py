"""
在庫変動 業務ロジック（Python版）

GAS の以下を移植:
- A1: applyReviewPresentToInventory  → apply_review_present()
- A2: applyArrivalToInventory        → apply_arrival()  (TODO)
- A3: applyOrderToInventory          → apply_order()    (TODO)
- A4: rolloverOpeningStock           → rollover_opening_stock()  (TODO)
- A5: applyStocktakingToInventory    → apply_stocktaking()  (TODO)
- A6: executeFBAShipment             → execute_fba_shipment()  (TODO)
"""
from typing import List, Tuple

import gspread
import pandas as pd

from . import sheets

# 04_在庫管理 の列番号（GAS の INV_COL と揃える、1-indexed）
INV_COL = {
    "PRODUCT_CODE":     1,   # A: 商品コード
    "TITLE":            2,   # B: タイトル
    "ROUTE":            3,   # C: 物流ルート
    "FBA_STOCK":        4,   # D: FBA在庫
    "FBA_INBOUND":      5,   # E: FBA入庫処理中
    "WAREHOUSE_STOCK":  6,   # F: 自社倉庫在庫
    "OPENING_STOCK":    7,   # G: 月初在庫
    "TOTAL_AVAILABLE":  8,   # H: 販売可能在庫合計
    "MONTH_ARRIVAL":    9,   # I: 当月入荷
    "MONTH_DISPOSAL":  10,   # J: 当月廃棄
    "STOCK_AMOUNT":    11,   # K: 在庫金額
    "ORDERED":         12,   # L: 発注済み
    "RECOMMEND_ORDER": 13,   # M: 推奨発注数
    "MONTH_SALES":     14,   # N: 当月販売数
    "KOBARI_USE":      15,   # O: コバリ消費
    "SALES_90D":       16,   # P: 過去90日販売数
    "CORRECTION":      17,   # Q: 補正倍率
    "CALC_VELOCITY":   18,   # R: 計算用販売速度
    "INVENTORY_DAYS":  19,   # S: 在庫日数
    "STATUS":          20,   # T: ステータス
}

# 04_在庫管理 のヘッダ行/データ開始行
INV_HEADER_ROW = 6
INV_DATA_START = 7

SHEET_INVENTORY = "04_在庫管理"


# ============================================================
# 共通ヘルパ
# ============================================================
def _get_inventory_worksheet():
    """04_在庫管理 の Worksheet オブジェクトを返す"""
    sh = sheets.get_spreadsheet()
    return sh.worksheet(SHEET_INVENTORY)


def _build_code_index(ws) -> Tuple[dict, int, int]:
    """04のA列(商品コード) → 行番号(1-indexed) のマップを構築

    Returns: (code_to_row_dict, last_row, num_data_rows)
    """
    last_row = ws.row_count
    actual_last = ws.col_values(INV_COL["PRODUCT_CODE"])  # A列全部
    actual_last_row = len(actual_last)

    code_idx = {}
    for i, code in enumerate(actual_last):
        if i + 1 < INV_DATA_START:
            continue  # ヘッダ・タイトル行スキップ
        c = str(code or "").strip()
        if c:
            code_idx[c] = i + 1  # 1-indexed row number

    num_data = max(0, actual_last_row - INV_DATA_START + 1)
    return code_idx, actual_last_row, num_data


# 06_入荷時 シートの列番号（GAS の ARR_COL と揃える）
ARR_COL = {
    "ARRIVAL_DATE":   1,   # A: 入荷日
    "ORDER_NO":       2,   # B: 注文番号
    "PRODUCT_CODE":   3,   # C: 商品コード
    "PRODUCT_NAME":   4,   # D: 商品名
    "RATIO":          5,   # E: 係数
    "ACTUAL_ARRIVAL": 6,   # F: 実際入荷数
    "SKU":            7,   # G: SKU
    "AFTER_STOCK":    8,   # H: 反映後在庫
    "WEIGHT":         9,   # I: 重量
    "BEFORE_AMOUNT": 10,   # J: 前在庫
    "CURRENT_COST":  11,   # K: 現原価
    "AFTER_COST":    12,   # L: 反映後原価
    "EMS_COST":      13,   # M: EMS送料
    "SHIP_COST":     14,   # N: 国内送料
    "JUDGE_FLAG":    15,   # O: 判定フラグ
    "TRANSFER":      16,   # P: 振替
    "MEMO":          17,   # Q: 備考
    "ADJUSTMENT":    18,   # R: 調整数
}
ARR_HEADER_ROW = 6
ARR_DATA_START = 7
SHEET_ARRIVAL = "06_入荷時"


# ============================================================
# A1: レビュープレゼント反映
# ============================================================
def apply_review_present() -> dict:
    """レビュープレゼントシート → 04のJ列(当月廃棄)に加算 → 反映成功行を削除

    GAS版 applyReviewPresentToInventory と等価動作:
    - レビューシート: A=商品コード, B=数量, C=発送日 (3列)
    - マスタにある商品 → 04のJ列に加算 → レビューシートから削除
    - マスタにない商品 → レビューシートに残す

    Returns: {processed: int, not_found: list, total: int}
    """
    sh = sheets.get_spreadsheet()
    rev_ws = sh.worksheet("レビュープレゼント")
    inv_ws = _get_inventory_worksheet()

    # レビューシート全データ取得
    rev_values = rev_ws.get_all_values()
    if len(rev_values) < 2:
        return {"processed": 0, "not_found": [], "total": 0, "remaining": 0}

    rev_header = rev_values[0]
    rev_data = rev_values[1:]

    # 04の商品コード→行番号マップ
    code_idx, last_row, num_data = _build_code_index(inv_ws)
    if num_data == 0:
        return {"processed": 0, "not_found": [], "total": 0, "remaining": 0,
                "error": "04_在庫管理にデータなし"}

    # 04のJ列(当月廃棄)を一括取得
    j_col_range = inv_ws.range(INV_DATA_START, INV_COL["MONTH_DISPOSAL"],
                                last_row, INV_COL["MONTH_DISPOSAL"])
    j_values = {(c.row): float(c.value or 0) for c in j_col_range}

    processed = 0
    not_found = []
    remain_rows = []

    for row in rev_data:
        if len(row) < 2:
            continue
        code = str(row[0] or "").strip()
        try:
            qty = float(row[1] or 0)
        except ValueError:
            qty = 0
        if not code or qty <= 0:
            continue

        if code not in code_idx:
            not_found.append(code)
            remain_rows.append(row)
            continue

        target_row = code_idx[code]
        j_values[target_row] = j_values.get(target_row, 0) + qty
        processed += 1

    # J列を一括書込
    if processed > 0:
        # range cells を更新
        cells_to_update = []
        for cell in j_col_range:
            new_val = j_values.get(cell.row, 0)
            cell.value = new_val
            cells_to_update.append(cell)
        inv_ws.update_cells(cells_to_update, value_input_option="USER_ENTERED")

    # レビューシート: 全行クリア → 残す行だけ書戻し
    rev_ws.batch_clear([f"A2:Z{len(rev_values)}"])
    if remain_rows:
        # 3列に整形（短い行は空文字埋め）
        normalized = [[str(r[i]) if i < len(r) else "" for i in range(3)]
                      for r in remain_rows]
        rev_ws.update(range_name=f"A2", values=normalized,
                      value_input_option="USER_ENTERED")

    # キャッシュクリア（in-memory + disk cache 両方）
    sheets._invalidate_one("04_在庫管理")
    sheets._invalidate_one("レビュープレゼント")

    return {
        "processed": processed,
        "not_found": not_found,
        "total": len(rev_data),
        "remaining": len(remain_rows),
    }


# ============================================================
# A2: 入荷を在庫に反映
# ============================================================
def apply_arrival() -> dict:
    """06_入荷時 → 04のI列(当月入荷)に加算 + L列(発注済み)から減算

    GAS版 applyArrivalToInventory と等価:
    - C列: 商品コード
    - F列: 実際入荷数
    - R列: 調整数（空ならF列を使う）
    - 04のI列(MONTH_ARRIVAL)に F列加算
    - 04のL列(ORDERED)から R列(または F列) 減算（マイナス防止）
    - 反映後、入荷時シートのデータ部分をクリア

    Returns: {processed, not_found, total}
    """
    sh = sheets.get_spreadsheet()
    arr_ws = sh.worksheet(SHEET_ARRIVAL)
    inv_ws = _get_inventory_worksheet()

    # 入荷時データ取得（R列まで18列）
    arr_last_row = arr_ws.row_count
    arr_values = arr_ws.get(f"A{ARR_DATA_START}:R{arr_last_row}")
    if not arr_values:
        return {"processed": 0, "not_found": [], "total": 0}

    # 04のA列マップ
    code_idx, inv_last_row, num_data = _build_code_index(inv_ws)

    # 04のI列(当月入荷)とL列(発注済み)を一括取得
    i_col_range = inv_ws.range(INV_DATA_START, INV_COL["MONTH_ARRIVAL"],
                                inv_last_row, INV_COL["MONTH_ARRIVAL"])
    l_col_range = inv_ws.range(INV_DATA_START, INV_COL["ORDERED"],
                                inv_last_row, INV_COL["ORDERED"])
    i_values = {c.row: float(c.value or 0) for c in i_col_range}
    l_values = {c.row: float(c.value or 0) for c in l_col_range}

    processed = 0
    not_found = []

    for row in arr_values:
        if len(row) < ARR_COL["ACTUAL_ARRIVAL"]:
            continue
        code = str(row[ARR_COL["PRODUCT_CODE"] - 1] or "").strip()
        if not code or code in ("商品管理番号", "商品コード"):
            continue
        try:
            actual = float(row[ARR_COL["ACTUAL_ARRIVAL"] - 1] or 0)
        except ValueError:
            actual = 0
        # R列(調整数) - 範囲外なら空
        adj_raw = row[ARR_COL["ADJUSTMENT"] - 1] if len(row) >= ARR_COL["ADJUSTMENT"] else ""
        if adj_raw == "" or adj_raw is None:
            subtract = actual
        else:
            try:
                subtract = float(adj_raw)
            except ValueError:
                subtract = actual

        if code not in code_idx:
            not_found.append(code)
            continue

        target_row = code_idx[code]
        i_values[target_row] = i_values.get(target_row, 0) + actual
        l_values[target_row] = max(0, l_values.get(target_row, 0) - subtract)
        processed += 1

    # 04のI列・L列を一括書込
    if processed > 0:
        for cell in i_col_range:
            cell.value = i_values.get(cell.row, 0)
        inv_ws.update_cells(i_col_range, value_input_option="USER_ENTERED")
        for cell in l_col_range:
            cell.value = l_values.get(cell.row, 0)
        inv_ws.update_cells(l_col_range, value_input_option="USER_ENTERED")

    # 入荷時シートのデータをクリア（A〜R列、データ行）
    if processed > 0 and arr_last_row >= ARR_DATA_START:
        clear_range = f"A{ARR_DATA_START}:R{arr_last_row}"
        arr_ws.batch_clear([clear_range])

    sheets.clear_all_caches()

    return {
        "processed": processed,
        "not_found": not_found,
        "total": len(arr_values),
    }


# ============================================================
# A3: 発注を在庫に反映
# ============================================================
def apply_order() -> dict:
    """10_エクセル発注用 → 04のL列(発注済み)に加算 + マスタT列(最終発注日)更新

    GAS版 applyOrderToInventory と等価:
    - エクセル発注用 4行目以降がデータ
    - A列: 商品コード, F列: 発注数, X列: 係数
    - 04のL列(ORDERED) += F / X (単品換算)
    - マスタT列(LAST_ORDER) = 今日の日付
    - エクセル発注用シートはA〜X列をクリア

    Returns: {processed, not_found, total}
    """
    from datetime import datetime
    sh = sheets.get_spreadsheet()
    order_ws = sh.worksheet("10_エクセル発注用")
    inv_ws = _get_inventory_worksheet()
    master_ws = sh.worksheet("03_商品マスタ参照")

    ORDER_DATA_START = 4
    order_last_row = order_ws.row_count
    order_values = order_ws.get(f"A{ORDER_DATA_START}:X{order_last_row}")
    if not order_values:
        return {"processed": 0, "not_found": [], "total": 0}

    # 04のA列マップ
    code_idx, inv_last_row, _ = _build_code_index(inv_ws)

    # 04のL列(発注済み)の現在値を一括取得 (col_values 1回・全行)
    l_col_letter = sheets._col_index_to_letter(INV_COL["ORDERED"])
    l_existing = inv_ws.col_values(INV_COL["ORDERED"])  # 1次元list
    # row番号(1-indexed) → float
    l_values: dict[int, float] = {}
    for i, v in enumerate(l_existing, start=1):
        if i < INV_DATA_START:
            continue
        try:
            l_values[i] = float(str(v or 0).replace(",", "").replace("¥", "") or 0)
        except (ValueError, TypeError):
            l_values[i] = 0

    # マスタA列マップ
    master_codes = master_ws.col_values(1)
    master_idx = {}
    for i, c in enumerate(master_codes):
        if i + 1 < 7:
            continue
        cs = str(c or "").strip()
        if cs:
            master_idx[cs] = i + 1

    LAST_ORDER_COL = 20  # マスタT列
    today = datetime.now().strftime("%Y-%m-%d")

    processed = 0
    not_found = []
    master_updates = []  # [(row_num, today)]
    l_target_rows: set[int] = set()  # 加算した対象04行のみ

    for row in order_values:
        if not row:
            continue
        code = str(row[0] or "").strip() if len(row) > 0 else ""
        try:
            qty = float(row[5] or 0) if len(row) > 5 else 0
        except ValueError:
            qty = 0
        try:
            ratio = float(row[23] or 0) if len(row) > 23 else 0
        except ValueError:
            ratio = 0

        if not code or qty <= 0 or ratio <= 0:
            continue

        if code not in code_idx:
            not_found.append(code)
            continue

        target_row = code_idx[code]
        add_qty = qty / ratio
        l_values[target_row] = l_values.get(target_row, 0) + add_qty
        l_target_rows.add(target_row)
        processed += 1

        # マスタの最終発注日
        if code in master_idx:
            master_updates.append((master_idx[code], today))

    # 04のL列: 加算した対象行だけ batch_update
    requests = []
    for r in l_target_rows:
        v = l_values[r]
        # 整数なら int 表記
        v_out = int(v) if v == int(v) else v
        requests.append({"range": f"{l_col_letter}{r}", "values": [[v_out]]})

    # マスタT列(最終発注日)も同じ requests に乗せて1回の batch_update でいけるが
    # シートが違うので別々のbatch_update
    if requests:
        inv_ws.batch_update(requests, value_input_option="USER_ENTERED")

    # マスタT列を batch_update (旧: update_cell ループ)
    if master_updates:
        master_t_letter = sheets._col_index_to_letter(LAST_ORDER_COL)
        master_reqs = [
            {"range": f"{master_t_letter}{rn}", "values": [[ds]]}
            for rn, ds in master_updates
        ]
        master_ws.batch_update(master_reqs, value_input_option="USER_ENTERED")

    # エクセル発注用シートクリア
    if processed > 0 and order_last_row >= ORDER_DATA_START:
        clear_range = f"A{ORDER_DATA_START}:X{order_last_row}"
        order_ws.batch_clear([clear_range])

    sheets.clear_all_caches()

    return {
        "processed": processed,
        "not_found": not_found,
        "total": len(order_values),
        "master_updated": len(master_updates),
    }
