"""
プール在庫設定ロジック（共通モジュール）

マスタAE列(Amazon SKU) ↔ 楽天SKU のペアを検出し、
04_在庫管理 のF列を「楽天=計算 / Amazon=ミラー参照」に設定する
"""
import pandas as pd

from . import sheets


AE_IDX = 30  # マスタAE列 = 0-indexed 30


def get_pool_pairs(master_df=None):
    """マスタAE列に値が入ってるペアを取得

    Returns: list of (rakuten_sku, amazon_sku)
    """
    if master_df is None:
        master_df = sheets.load_master()
    if master_df.empty or len(master_df.columns) <= AE_IDX:
        return []

    code_col = master_df.columns[0]
    ae_col = master_df.columns[AE_IDX]

    pairs = []
    for _, r in master_df.iterrows():
        rakuten = str(r[code_col]).strip()
        amazon = str(r[ae_col]).strip()
        if rakuten and amazon:
            pairs.append((rakuten, amazon))
    return pairs


def apply_pool_setup(master_df=None, target_pairs=None) -> dict:
    """プール在庫式を一括設定

    Args:
        master_df: マスタDataFrame (Noneなら自動取得)
        target_pairs: [(rakuten, amazon), ...] 指定があればその組のみ更新

    Returns: {master_updated, mirror_updated, k_updated, total}
    """
    if master_df is None:
        master_df = sheets.load_master()

    if target_pairs is None:
        target_pairs = get_pool_pairs(master_df)

    if not target_pairs:
        return {"master_updated": 0, "mirror_updated": 0, "total": 0, "skipped": 0}

    ss = sheets.get_spreadsheet()
    ws = ss.worksheet("04_在庫管理")

    # 04のA列マップ
    inv_a_col = ws.col_values(1)
    code_to_row = {}
    for i, c in enumerate(inv_a_col):
        if i + 1 < 7:
            continue
        cs = str(c or "").strip()
        if cs:
            code_to_row[cs] = i + 1

    updates = []
    master_updated = 0
    mirror_updated = 0
    skipped = 0

    for rakuten_sku, amazon_sku in target_pairs:
        # 楽天SKU行のF列マスター数式
        if rakuten_sku in code_to_row:
            r = code_to_row[rakuten_sku]
            formula_master = (
                f'=IF(A{r}="","",'
                f'IFERROR(G{r},0)+IFERROR(I{r},0)-IFERROR(J{r},0)'
                f'-IFERROR(SUMIFS(\'05_売上管理\'!G:G,'
                f'\'05_売上管理\'!D:D,A{r},'
                f'\'05_売上管理\'!A:A,">="&EOMONTH(TODAY(),-1)+1,'
                f'\'05_売上管理\'!B:B,"楽天"),0)'
                f'-IFERROR(SUMIFS(\'05_売上管理\'!G:G,'
                f'\'05_売上管理\'!D:D,A{r},'
                f'\'05_売上管理\'!A:A,">="&EOMONTH(TODAY(),-1)+1,'
                f'\'05_売上管理\'!B:B,"Amazon FBM"),0)'
                f'-IFERROR(SUMIFS(\'05_売上管理\'!G:G,'
                f'\'05_売上管理\'!D:D,"{amazon_sku}",'
                f'\'05_売上管理\'!A:A,">="&EOMONTH(TODAY(),-1)+1,'
                f'\'05_売上管理\'!B:B,"Amazon FBM"),0)'
                f'-IFERROR(O{r},0))'
            )
            updates.append({"range": f"F{r}", "values": [[formula_master]]})
            master_updated += 1

        # Amazon SKU行のF列ミラー（楽天行のF列を直接参照）
        if amazon_sku in code_to_row:
            r = code_to_row[amazon_sku]
            if rakuten_sku in code_to_row:
                rakuten_row = code_to_row[rakuten_sku]
                formula_mirror = f'=IFERROR(F{rakuten_row},0)'
            else:
                formula_mirror = '0'
            updates.append({"range": f"F{r}", "values": [[formula_mirror]]})
            mirror_updated += 1
        else:
            skipped += 1

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        sheets._invalidate_one("04_在庫管理")

    return {
        "master_updated": master_updated,
        "mirror_updated": mirror_updated,
        "total": len(updates),
        "skipped": skipped,
    }


def update_k_arrayformula(amazon_skus: list) -> bool:
    """K列のARRAYFORMULAを「Amazon SKU(ミラー)行はゼロ」に書き換え

    Args:
        amazon_skus: ミラー対象のAmazon SKUリスト

    Returns: True/False
    """
    ss = sheets.get_spreadsheet()
    ws = ss.worksheet("04_在庫管理")

    sku_list = [s for s in amazon_skus if s and str(s).strip()]
    if not sku_list:
        return False

    sku_list_str = "{" + ",".join(f'"{s}"' for s in sku_list) + "}"
    new_k_formula = (
        f'=ARRAYFORMULA(IF(A7:A="","",'
        f'IF(COUNTIF({sku_list_str},A7:A)>0,0,'
        f'H7:H*IFERROR(VLOOKUP(A7:A,\'03_商品マスタ参照\'!A:H,8,FALSE),0))))'
    )
    ws.update(range_name="K7", values=[[new_k_formula]],
              value_input_option="USER_ENTERED")
    sheets._invalidate_one("04_在庫管理")
    return True
