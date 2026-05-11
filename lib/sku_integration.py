"""
SKU統合 ロジック（Python版）

GAS版の 20_SKUIntegration.gs を pandas で爆速化
"""
import re
import unicodedata
from collections import defaultdict
from typing import List, Tuple

import pandas as pd

# プレフィックス除去ルール（先頭マッチで除去）
PREFIX_RULES = [
    (re.compile(r"^R\d+"),    "R+数字（楽天）"),
    (re.compile(r"^自"),       "自（Amazon FBM）"),
    (re.compile(r"^AMA"),     "AMA（Amazon）"),
    (re.compile(r"^ama"),     "ama（Amazon FBM）"),
    (re.compile(r"^Ama"),     "Ama（Amazon）"),
    (re.compile(r"^FBA"),     "FBA"),
    (re.compile(r"^Fba"),     "Fba"),
    (re.compile(r"^fba"),     "fba"),
]

CH_RAKUTEN = "楽天"
CH_FBM     = "FBM"
CH_FBA     = "FBA"
CH_UNKNOWN = "不明"


def normalize_text(s: str) -> str:
    """全角→半角、スペース統一、両端trim"""
    if s is None or s == "":
        return ""
    t = str(s)
    # 全角→半角（NFKC で英数記号変換）
    t = unicodedata.normalize("NFKC", t)
    # 連続スペース→1個、両端trim
    t = re.sub(r"\s+", " ", t).strip()
    return t


def remove_prefix(s: str) -> str:
    """先頭プレフィックスを除去（最初にマッチしたルールを適用）"""
    s = normalize_text(s)
    if not s:
        return ""
    for pattern, _ in PREFIX_RULES:
        if pattern.match(s):
            s = pattern.sub("", s)
            break
    return s.strip()


def detect_channel(raw_small_cat: str) -> str:
    """小分類の生値からチャネル推定"""
    if not raw_small_cat:
        return CH_UNKNOWN
    s = str(raw_small_cat)
    if re.match(r"^FBA|^Fba|^fba", s):
        return CH_FBA
    if re.match(r"^自|^AMA|^ama|^Ama", s):
        return CH_FBM
    if re.match(r"^R\d+", s):
        return CH_RAKUTEN
    return CH_UNKNOWN


def make_unified_sku(seq: int) -> str:
    """U000001 形式の統合SKU生成"""
    return f"U{seq:06d}"


def analyze_prefixes(master_df: pd.DataFrame, small_cat_col: str) -> pd.DataFrame:
    """Phase 1: プレフィックス頻度分析

    Returns: DataFrame [プレフィックス, 件数, サンプル(最大3件)]
    """
    counter = defaultdict(lambda: {"count": 0, "samples": []})
    for v in master_df[small_cat_col].dropna():
        s = str(v).strip()
        if not s:
            continue
        matched = None
        for pattern, label in PREFIX_RULES:
            if pattern.match(s):
                matched = label
                break
        key = matched if matched else "(なし)"
        counter[key]["count"] += 1
        if len(counter[key]["samples"]) < 3:
            counter[key]["samples"].append(s)

    rows = [
        {
            "プレフィックス": k,
            "件数": v["count"],
            "サンプル": " | ".join(v["samples"]),
        }
        for k, v in counter.items()
    ]
    return pd.DataFrame(rows).sort_values("件数", ascending=False).reset_index(drop=True)


def build_grouping(
    master_df: pd.DataFrame,
    code_col: str,
    small_cat_col: str,
    supplier_col: str = None,
    title_col: str = None,
) -> pd.DataFrame:
    """Phase 2: 全SKUをグルーピング → レビュー用 DataFrame 生成

    Returns: DataFrame with cols
        [グループID, 統合SKU, 旧SKU, 小分類(生), 正規化キー, チャネル, 仕入先, タイトル, マスタ行, 確定?, 修正後グループID]
    """
    # 各行の正規化情報を生成
    rows = []
    for idx, row in master_df.iterrows():
        old_sku = str(row[code_col]).strip() if pd.notna(row[code_col]) else ""
        if not old_sku:
            continue
        small = str(row[small_cat_col]).strip() if pd.notna(row[small_cat_col]) else ""
        norm = remove_prefix(small)
        ch = detect_channel(small)
        sup = str(row[supplier_col]).strip() if supplier_col and pd.notna(row[supplier_col]) else ""
        title = str(row[title_col]).strip() if title_col and pd.notna(row[title_col]) else ""
        rows.append({
            "old_sku": old_sku,
            "small_raw": small,
            "norm_key": norm,
            "channel": ch,
            "supplier": sup,
            "title": title,
            "master_row": idx + 7,  # 1-indexed master row (header at row 6)
        })

    # 正規化キーでグルーピング
    groups = defaultdict(list)
    singles = []
    for r in rows:
        if r["norm_key"]:
            groups[r["norm_key"]].append(r)
        else:
            singles.append(r)

    # グループID発番（複数メンバーグループ → 単独グループ の順）
    grouped = []
    seq = 0

    # 複数メンバー優先で番号付け
    multi = [(k, members) for k, members in groups.items() if len(members) >= 2]
    single = [(k, members) for k, members in groups.items() if len(members) == 1]

    for key, members in multi + single:
        seq += 1
        gid = f"G{seq:04d}"
        # チャネル順ソート（楽天→FBM→FBA→不明）
        ch_order = {CH_RAKUTEN: 0, CH_FBM: 1, CH_FBA: 2, CH_UNKNOWN: 3}
        members.sort(key=lambda m: ch_order.get(m["channel"], 9))
        for m in members:
            m["group_id"] = gid
        grouped.extend(members)

    for r in singles:
        seq += 1
        r["group_id"] = f"G{seq:04d}"
        grouped.append(r)

    # 統合SKU仮発番（グループ単位、先頭行のみ表示）
    df = pd.DataFrame(grouped)
    if df.empty:
        return df

    df = df.reset_index(drop=True)
    seen_groups = set()
    unified_seq = 0
    unified_skus = []
    for gid in df["group_id"]:
        if gid not in seen_groups:
            seen_groups.add(gid)
            unified_seq += 1
            unified_skus.append(make_unified_sku(unified_seq))
        else:
            unified_skus.append("")  # 重複行は空表示
    df["unified_sku"] = unified_skus

    # 出力DataFrame
    out = pd.DataFrame({
        "グループID":         df["group_id"],
        "統合SKU(予定)":      df["unified_sku"],
        "旧SKU":              df["old_sku"],
        "小分類(生)":         df["small_raw"],
        "正規化キー":         df["norm_key"],
        "チャネル":           df["channel"],
        "仕入先":             df["supplier"],
        "タイトル":           df["title"],
        "マスタ行":           df["master_row"],
        "確定?":              False,
        "修正後グループID":   "",
    })
    return out


def execute_merge(
    review_df: pd.DataFrame,
    master_df: pd.DataFrame,
    code_col: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Phase 4: マージ実行 → 新マスタ + 対応表

    Args:
        review_df: build_grouping の結果（人間レビュー後）
        master_df: 元マスタ DataFrame
        code_col:  マスタの商品コード列名

    Returns:
        (new_master_df, mapping_df, stats)
    """
    # 確定グループID決定（修正後があればそれ、なければ元のグループID）
    review_df = review_df.copy()
    review_df["確定グループID"] = review_df.apply(
        lambda r: r["修正後グループID"] if str(r["修正後グループID"]).strip() else r["グループID"],
        axis=1,
    )

    # マスタを商品コード → 行 のマップにする
    master_indexed = master_df.set_index(code_col, drop=False)

    # 確定グループでマージ
    new_rows = []
    mapping_rows = []
    seq = 0
    pick_order = {CH_RAKUTEN: 0, CH_FBA: 1, CH_FBM: 2, CH_UNKNOWN: 3}

    for gid, members in review_df.groupby("確定グループID", sort=True):
        seq += 1
        unified = make_unified_sku(seq)

        # 各チャネルのSKU
        rakuten_sku = ""
        fbm_sku = ""
        fba_sku = ""
        for _, m in members.iterrows():
            ch = m["チャネル"]
            sku = m["旧SKU"]
            if ch == CH_RAKUTEN and not rakuten_sku:
                rakuten_sku = sku
            elif ch == CH_FBM and not fbm_sku:
                fbm_sku = sku
            elif ch == CH_FBA and not fba_sku:
                fba_sku = sku

        # 「楽天」しか選ばれてないが両方販売の可能性 → AE列(FBM SKU)に楽天SKUをコピー
        # （楽天SKUを Amazon FBM SKU としても使ってる前提）
        if rakuten_sku and not fbm_sku:
            fbm_sku = rakuten_sku

        # 代表行の決定（楽天→FBA→FBM→不明）
        members_sorted = members.copy()
        members_sorted["_pick"] = members_sorted["チャネル"].map(lambda c: pick_order.get(c, 9))
        primary = members_sorted.sort_values("_pick").iloc[0]
        primary_sku = primary["旧SKU"]

        # マスタから代表行を取得
        try:
            base_row = master_indexed.loc[primary_sku].copy()
            if isinstance(base_row, pd.DataFrame):
                base_row = base_row.iloc[0]
        except KeyError:
            base_row = pd.Series(dtype=object)

        # 新行構築
        new_row = base_row.to_dict() if not base_row.empty else {}
        new_row[code_col] = unified  # A列を統合SKU化
        new_row["楽天SKU"]         = rakuten_sku
        new_row["Amazon FBM SKU"]  = fbm_sku
        new_row["Amazon FBA SKU"]  = fba_sku
        new_rows.append(new_row)

        # 対応表
        for _, m in members.iterrows():
            mapping_rows.append({
                "旧SKU":     m["旧SKU"],
                "旧チャネル": m["チャネル"],
                "新統合SKU": unified,
                "旧マスタ行": m["マスタ行"],
            })

    new_master_df = pd.DataFrame(new_rows)
    mapping_df = pd.DataFrame(mapping_rows)

    stats = {
        "新マスタ行数": len(new_master_df),
        "対応表行数": len(mapping_df),
        "統合SKU範囲": f"{make_unified_sku(1)} 〜 {make_unified_sku(seq)}" if seq > 0 else "なし",
        "グループ数": seq,
    }
    return new_master_df, mapping_df, stats
