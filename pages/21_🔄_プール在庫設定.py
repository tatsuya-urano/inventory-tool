"""
🔄 プール在庫設定

マスタAF列(Amazon FBM SKU)に値があり、かつ A列(楽天SKU)と異なる SKU を
「プール在庫」として運用する。
- 楽天SKU行: 自社倉庫在庫を計算（楽天売上 + Amazon FBM売上(両SKU)を引く）
- Amazon FBM SKU行: 楽天SKU行の自社倉庫在庫をミラー表示

これでAmazon FBM SKU側の在庫がマイナスにならず、楽天側で一元管理できる。
"""
import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="プール在庫設定", page_icon="🔄", layout="wide")
st.title("🔄 プール在庫設定")
ui.sidebar_common()

# ===========================================================
# 使い方（最初に必ず読む）
# ===========================================================
with st.expander("📌 プール在庫とは？このページで何ができる？(クリックして読む)", expanded=True):
    st.markdown(
        """
### 📦 プール在庫とは
同じ商品を **楽天と Amazon FBM の両方で販売** していて、
**同じ自社倉庫から発送している** 場合に、在庫を「楽天SKU側に一元管理」する仕組みです。

楽天と Amazon で在庫を別々にカウントすると、実際には倉庫に1個しかないのに
両方のシステムで「1個ずつ」在庫があると見えてしまい、**二重カウント** や
**Amazon側の在庫マイナス** が発生します。プール在庫はこれを防ぎます。

### 🔑 ペアリングの仕組み
- マスタの **A列(商品コード)** = 楽天SKU(在庫マスター)
- マスタの **AF列(Amazon FBM SKU)** に対応するAmazon FBM側のSKUを入力 → ペアになる
- AF列が空、または **A列と同じ値** の場合は対象外
  - A列と同じ = 楽天もAmazonも同じSKU運用 = プール処理不要

### ⚙️ 「⚡ プール在庫式を設定」を押すと
04_在庫管理 の対象行の **F列（自社倉庫在庫）の数式** を以下に書き換えます:

| 行 | F列の数式 | 意味 |
|---|---|---|
| 楽天SKU行 | 月初+入荷-廃棄 -楽天売上 -**Amazon FBM売上(楽天SKU分)** -**Amazon FBM売上(Amazon FBM SKU分)** | 両方の売上を1つの在庫から引く |
| Amazon FBM SKU行 | `=IFERROR(F{楽天SKU行},0)` | 楽天SKU行の在庫をそのまま表示するミラー |

これで:
- ✅ Amazon SKUの在庫がマイナスにならない
- ✅ 楽天もAmazonも同じ実在庫数を見る
- ⚠️ **在庫金額(K列)はこのページでは触らない**
  → K列の二重カウント防止は K7 の ARRAYFORMULA 内のミラーSKUリストで別途管理

### 🔁 何度実行しても安全
新しくAF列を埋めたペアが増えたとき、再実行で追加分も反映されます。
既存のプール対象行は同じ式で上書きされるだけなので副作用なし。

### ⚠️ 注意
- **AF列に間違ったAmazon FBM SKU が入っているとプールが壊れる** → 設定前にマスタ03のAF列を要確認
- 04_在庫管理 の F列は ARRAYFORMULA ではなく **個別行ごとの数式** に置き換わります
- 解除したい場合は、04のF列を元の式に戻す or マスタAF列を空にして再実行
"""
    )

# ===========================================================
# データ取得
# ===========================================================
with st.spinner("読込中..."):
    master = sheets.load_master()
    inv = sheets.load_inventory()

if master.empty or inv.empty:
    st.error("マスタ or 04 が空")
    st.stop()

# AF列(Amazon FBM SKU)の有無
AF_IDX = 31  # AF列 = 0-indexed 31
if len(master.columns) <= AF_IDX:
    st.error("マスタにAF列がありません")
    st.stop()

# ===========================================================
# 1. AF列(Amazon FBM SKU)に値があり、A列と異なるSKUを抽出
# ===========================================================
st.markdown("## 1️⃣ プール対象SKU(マスタAF列にAmazon FBM SKUあり、かつA列と異なる)")

m_code_col = master.columns[0]
m_af_col = master.columns[AF_IDX]

# A列とAF列を取り出して、AF列が空でない＆A列と異なるペアだけ抽出
_pool_src = master[[m_code_col, m_af_col]].copy()
_pool_src.columns = ["楽天SKU(マスター)", "Amazon FBM SKU(ミラー)"]
_pool_src["楽天SKU(マスター)"] = _pool_src["楽天SKU(マスター)"].astype(str).str.strip()
_pool_src["Amazon FBM SKU(ミラー)"] = _pool_src["Amazon FBM SKU(ミラー)"].astype(str).str.strip()

pool_pairs = _pool_src[
    (_pool_src["Amazon FBM SKU(ミラー)"] != "")
    & (_pool_src["楽天SKU(マスター)"] != _pool_src["Amazon FBM SKU(ミラー)"])
].reset_index(drop=True)

# 既存のコード参照名と互換性を保つため列名を旧形式にも揃える（amz_in_inv 等の検出処理用）
pool_pairs = pool_pairs.rename(columns={"Amazon FBM SKU(ミラー)": "Amazon SKU(ミラー)"})

st.metric("プール対象ペア数", len(pool_pairs))

if pool_pairs.empty:
    st.warning("マスタAE列に値があるSKUがありません。プール在庫設定の対象なし")
    st.stop()

st.dataframe(pool_pairs, use_container_width=True, hide_index=True, height=300)

# ===========================================================
# 2. 04 に Amazon SKU 行が存在するか診断
# ===========================================================
st.markdown("---")
st.markdown("## 2️⃣ 04_在庫管理 にAmazon SKU行があるか診断")

inv_codes = set(inv.iloc[:, 0].astype(str).str.strip())

amz_in_inv = pool_pairs[pool_pairs["Amazon SKU(ミラー)"].astype(str).str.strip().isin(inv_codes)]
amz_not_in_inv = pool_pairs[~pool_pairs["Amazon SKU(ミラー)"].astype(str).str.strip().isin(inv_codes)]
rakuten_in_inv = pool_pairs[pool_pairs["楽天SKU(マスター)"].astype(str).str.strip().isin(inv_codes)]
rakuten_not_in_inv = pool_pairs[~pool_pairs["楽天SKU(マスター)"].astype(str).str.strip().isin(inv_codes)]

c1, c2, c3, c4 = st.columns(4)
c1.metric("✅ 楽天SKU 04にあり", len(rakuten_in_inv))
c2.metric("⚠ 楽天SKU 04になし", len(rakuten_not_in_inv))
c3.metric("✅ Amazon SKU 04にあり", len(amz_in_inv))
c4.metric("⚠ Amazon SKU 04になし", len(amz_not_in_inv))

if len(rakuten_not_in_inv) > 0:
    with st.expander(f"⚠ 楽天SKU 04になし {len(rakuten_not_in_inv)}件"):
        st.dataframe(rakuten_not_in_inv, use_container_width=True, hide_index=True)

if len(amz_in_inv) > 0:
    with st.expander(f"✅ Amazon SKU 04にあり {len(amz_in_inv)}件（プール化対象）"):
        st.dataframe(amz_in_inv, use_container_width=True, hide_index=True)

# ===========================================================
# 3. プール化実行
# ===========================================================
st.markdown("---")
st.markdown("## 3️⃣ プール在庫式を設定")

st.info(
    """
**実行内容:**
1. **楽天SKU行**（プール対象の楽天SKU）の F列(自社倉庫在庫) 数式を更新:
   - 既存: 楽天売上 + Amazon FBM売上(自分のSKU)を引く
   - 新規: 楽天売上 + Amazon FBM売上(自分のSKU **+ 対応するAmazon SKU**)を引く

2. **Amazon SKU行** の F列を **VLOOKUP** に変更:
   - `=IFERROR(VLOOKUP("楽天SKU", A:F, 6, FALSE), 0)`
   - つまり楽天SKU行の自社倉庫在庫を表示するだけ
   - マイナスにならない

3. **Amazon SKU行** の K列(在庫金額) を **0** に固定:
   - 在庫金額は楽天SKU側で計上、Amazon側は0
   - 在庫金額の二重カウント防止

⚠ ARRAYFORMULA ではなく、**該当行のみ個別数式**で書き換えます
"""
)

if st.button("⚡ プール在庫式を設定", type="primary"):
    with st.spinner("数式書込中..."):
        try:
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
            for _, pair in pool_pairs.iterrows():
                rakuten_sku = str(pair["楽天SKU(マスター)"]).strip()
                amazon_sku = str(pair["Amazon SKU(ミラー)"]).strip()

                # 楽天SKU行のF列を「楽天売上 + Amazon FBM売上(楽天SKU + Amazon SKU両方) を引く」に
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

                # Amazon SKU行のF列を「楽天SKU行のF列を直接参照」に
                # (VLOOKUP A:F だと循環参照になるため、INDEX+MATCHで限定参照)
                if amazon_sku in code_to_row:
                    r = code_to_row[amazon_sku]
                    if rakuten_sku in code_to_row:
                        rakuten_row = code_to_row[rakuten_sku]
                        # 楽天SKU行のF列を直接参照（循環なし）
                        formula_mirror = f'=IFERROR(F{rakuten_row},0)'
                    else:
                        formula_mirror = '0'
                    updates.append({"range": f"F{r}", "values": [[formula_mirror]]})
                    # K列(在庫金額)は ARRAYFORMULA との衝突を避けるため触らない

            # batch_update で一括書込
            if updates:
                ws.batch_update(updates, value_input_option="USER_ENTERED")
                sheets._invalidate_one("04_在庫管理")
                st.success(
                    f"✅ プール在庫設定完了\n\n"
                    f"- 楽天SKU行 F列更新: {len(pool_pairs[pool_pairs['楽天SKU(マスター)'].astype(str).str.strip().isin(inv_codes)])}件\n"
                    f"- Amazon SKU行 F列更新: {len(amz_in_inv)}件\n"
                    f"- 合計書込: {len(updates)}件"
                )
                st.balloons()
            else:
                st.warning("更新対象がありません")
        except Exception as e:
            st.error(f"失敗: {e}")
            import traceback
            st.code(traceback.format_exc())

# ===========================================================
# 4. K列(在庫金額)二重カウント防止
# ===========================================================
st.markdown("---")
st.markdown("## 4️⃣ K列(在庫金額) 二重カウント防止")
st.caption(
    "Amazon SKU行のK列を ARRAYFORMULA で「ミラー行ならゼロ」に変更。\n"
    "VLOOKUP で楽天側のF列を参照してるため、楽天側のK列で在庫金額が計上される"
)

if st.button("🔧 K列ARRAYFORMULAを「ミラー除外」に書き換え", key="fix_k_formula"):
    with st.spinner("K列の数式書込中..."):
        try:
            ss = sheets.get_spreadsheet()
            ws = ss.worksheet("04_在庫管理")

            # ミラー側(Amazon FBM SKU)のリストをREGEXMATCHパターン化
            amazon_skus = [s for s in pool_pairs["Amazon SKU(ミラー)"].astype(str).str.strip().tolist() if s]
            # 正規表現メタ文字をエスケープ
            import re as _re
            pattern = "^(" + "|".join(_re.escape(s) for s in amazon_skus) + ")$"

            # 新しいK列ARRAYFORMULA: ミラー行は0、それ以外は H × XLOOKUP(A, master.A, master.H)
            # COUNTIFは配列critで動かない既知バグのため REGEXMATCH を使う
            # IFERROR(VLOOKUP) もARRAYFORMULA内で配列が崩れる既知バグのため XLOOKUP+IFNA
            new_k_formula = (
                f'=ARRAYFORMULA(IF(A7:A="","",'
                f'IF(REGEXMATCH(A7:A&"","{pattern}"),'
                f'0,'
                f'N(H7:H)*IFNA(XLOOKUP(A7:A,\'03_商品マスタ参照\'!A:A,\'03_商品マスタ参照\'!H:H),0))))'
            )

            # K7を完全に書き換え（既存は1個セルなので衝突なし）
            ws.update(range_name="K7", values=[[new_k_formula]],
                      value_input_option="USER_ENTERED")
            sheets._invalidate_one("04_在庫管理")
            st.success(f"✅ K列の数式を更新（ミラー{len(amazon_skus)}件は0、楽天行で計上）")
            st.balloons()
        except Exception as e:
            st.error(f"失敗: {e}")
            import traceback
            st.code(traceback.format_exc())

# ===========================================================
# 5. ロールバック（プール化解除）
# ===========================================================
with st.expander("🔙 ロールバック: プール化を解除して元のF列数式に戻す"):
    st.caption(
        "Amazon SKU行のF列をデフォルト数式（自社で売上計算）に戻します"
    )
    if st.button("元の数式に戻す", key="rollback"):
        with st.spinner("元に戻し中..."):
            try:
                ss = sheets.get_spreadsheet()
                ws = ss.worksheet("04_在庫管理")
                inv_a_col = ws.col_values(1)
                code_to_row = {str(c or "").strip(): i+1 for i, c in enumerate(inv_a_col) if i+1 >= 7 and str(c or "").strip()}

                updates = []
                for _, pair in pool_pairs.iterrows():
                    for sku in [pair["楽天SKU(マスター)"], pair["Amazon SKU(ミラー)"]]:
                        sku = str(sku).strip()
                        if sku in code_to_row:
                            r = code_to_row[sku]
                            formula = (
                                f'=IF(A{r}="","",'
                                f'IFERROR(G{r},0)+IFERROR(I{r},0)-IFERROR(J{r},0)'
                                f'-IFERROR(SUMIFS(\'05_売上管理\'!G:G,\'05_売上管理\'!D:D,A{r},'
                                f'\'05_売上管理\'!A:A,">="&EOMONTH(TODAY(),-1)+1,'
                                f'\'05_売上管理\'!B:B,"楽天"),0)'
                                f'-IFERROR(SUMIFS(\'05_売上管理\'!G:G,\'05_売上管理\'!D:D,A{r},'
                                f'\'05_売上管理\'!A:A,">="&EOMONTH(TODAY(),-1)+1,'
                                f'\'05_売上管理\'!B:B,"Amazon FBM"),0)'
                                f'-IFERROR(O{r},0))'
                            )
                            updates.append({"range": f"F{r}", "values": [[formula]]})

                if updates:
                    ws.batch_update(updates, value_input_option="USER_ENTERED")
                    sheets._invalidate_one("04_在庫管理")
                    st.success(f"✅ {len(updates)}件 ロールバック完了")
            except Exception as e:
                st.error(f"失敗: {e}")
