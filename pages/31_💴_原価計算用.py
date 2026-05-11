"""
02_原価計算用 編集ページ

シート構造:
- E2/E3/E4: パラメータ(為替レート/EMS元/KG/船便元/KG)
- row 7: ヘッダ(商品テーブル)
- row 8〜: 商品ごとの計算行(B〜J列)
- row 8〜: 並行して L〜P列 に容積重量参考データ(航空便系/船便系)
"""
import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="原価計算用", page_icon="💴", layout="wide")
st.title("💴 02_原価計算用")
ui.sidebar_common(this_sheet="02_原価計算用")

with st.expander("📌 このページでできること", expanded=False):
    st.markdown(
        """
- **計算パラメータ**(為替レート / EMS / 船便) を編集
- **容積重量参考テーブル** で航空便/船便の寸法から重量を計算(P列が自動)
- **商品テーブル** で 商品名/商品代/入荷数/重さ/国内送料 を編集
- 数式列 (F, H, I, J, P) は保護されます
"""
    )

sh = sheets.get_spreadsheet()
ws = sh.worksheet("02_原価計算用")
all_values = ws.get_all_values()

if not all_values or len(all_values) < 7:
    st.warning("シートが空、または想定構造ではありません")
    st.stop()


def _to_num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("¥", "").strip())
    except (ValueError, TypeError):
        return None


# ===========================================================
# 1️⃣ パラメータ編集 (E2, E3, E4)
# ===========================================================
st.markdown("### ⚙️ 計算パラメータ")
e2 = all_values[1][4] if len(all_values) > 1 and len(all_values[1]) > 4 else ""
e3 = all_values[2][4] if len(all_values) > 2 and len(all_values[2]) > 4 else ""
e4 = all_values[3][4] if len(all_values) > 3 and len(all_values[3]) > 4 else ""

pc1, pc2, pc3 = st.columns(3)
new_e2 = pc1.number_input("為替レート",   value=_to_num(e2) or 0.0, step=0.01, format="%.4f", key="param_e2")
new_e3 = pc2.number_input("EMS元/KG",     value=_to_num(e3) or 0.0, step=0.1,  format="%.2f", key="param_e3")
new_e4 = pc3.number_input("船便元/KG",    value=_to_num(e4) or 0.0, step=0.1,  format="%.2f", key="param_e4")

orig_params = (_to_num(e2), _to_num(e3), _to_num(e4))
if (new_e2, new_e3, new_e4) != orig_params:
    try:
        ws.batch_update([
            {"range": "E2", "values": [[new_e2]]},
            {"range": "E3", "values": [[new_e3]]},
            {"range": "E4", "values": [[new_e4]]},
        ], value_input_option="USER_ENTERED")
        sheets._invalidate_one("02_原価計算用")
        st.toast("💾 パラメータ 自動保存", icon="✅")
        st.rerun()
    except Exception as e:
        st.error(f"❌ パラメータ 自動保存失敗: {e}")

st.markdown("---")


# ===========================================================
# 2️⃣ 容積重量参考テーブル (L〜P列)
# ===========================================================
st.markdown("### 📦 容積重量参考テーブル")
st.caption("航空便/船便の寸法から容積重量を算出 (P列 = 縦×横×高さ÷6000×1000)")

vol_cols = ["区分メモ", "縦cm", "横cm", "高さcm", "容積重量g"]
vol_rows = []
vol_sheet_rows = []
for i, r in enumerate(all_values[7:], start=8):
    # L〜P 列 (index 11〜15)
    lp = (r[11:16] if len(r) >= 16 else r[11:] + [""] * (16 - len(r) - 1))
    lp = lp + [""] * (5 - len(lp))
    if any(str(c).strip() for c in lp):
        vol_rows.append(lp)
        vol_sheet_rows.append(i)

if vol_rows:
    df_vol = pd.DataFrame(vol_rows, columns=vol_cols)
    for col in ["縦cm", "横cm", "高さcm"]:
        df_vol[col] = df_vol[col].apply(lambda v: _to_num(v) if v not in (None, "") else None)

    edited_vol = st.data_editor(
        df_vol,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "区分メモ":   st.column_config.TextColumn(label="🟢 区分メモ"),
            "縦cm":       st.column_config.NumberColumn(label="🟢 縦cm", min_value=0, step=1),
            "横cm":       st.column_config.NumberColumn(label="🟢 横cm", min_value=0, step=1),
            "高さcm":     st.column_config.NumberColumn(label="🟢 高さcm", min_value=0, step=0.1, format="%.1f"),
            "容積重量g":  st.column_config.TextColumn(label="🔒 容積重量g (数式)", disabled=True),
        },
        key="vol_editor",
    )

    # 差分検出 (L/M/N/O列のみ書き戻し、Pは数式)
    def _norm(v):
        if v is None or pd.isna(v):
            return ""
        s = str(v).strip()
        try:
            return float(s.replace(",", "").replace("¥", ""))
        except (ValueError, TypeError):
            return s

    vol_diffs = []
    VOL_LETTER = {"区分メモ": "L", "縦cm": "M", "横cm": "N", "高さcm": "O"}
    for i, sheet_row in enumerate(vol_sheet_rows):
        for col, letter in VOL_LETTER.items():
            old_v = df_vol.at[i, col]
            new_v = edited_vol.at[i, col]
            if _norm(old_v) == _norm(new_v):
                continue
            write_v = "" if pd.isna(new_v) or new_v is None else new_v
            vol_diffs.append({"row": sheet_row, "col": letter, "value": write_v,
                              "label": f"{col} (row{sheet_row})", "old": old_v, "new": new_v})

    if vol_diffs:
        try:
            ws.batch_update(
                [{"range": f"{d['col']}{d['row']}", "values": [[d["value"]]]} for d in vol_diffs],
                value_input_option="USER_ENTERED",
            )
            sheets._invalidate_one("02_原価計算用")
            st.toast(f"💾 容積重量 自動保存 {len(vol_diffs)}件", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"❌ 容積重量 自動保存失敗: {e}")
    else:
        st.caption("✅ 変更なし(編集→Enterで自動保存)")
else:
    st.info("容積重量データなし")

st.markdown("---")


# ===========================================================
# 3️⃣ 商品テーブル (B〜J列)
# ===========================================================
st.markdown("### 📊 商品ごとの原価計算")
st.caption("⚠ 数式列(F単体重さ / H EMS原価 / I 船便原価 / J 総料金) は編集不可")

prod_cols = ["商品名", "商品代(元)", "入荷数", "商品重さ(g)", "商品重さ(単体)",
             "国内送料(元)", "EMS原価(円)", "船便原価(円)", "商品総料金"]

prod_rows = []
prod_sheet_rows = []
for i, r in enumerate(all_values[7:], start=8):
    bj = (r[1:10] if len(r) >= 10 else r[1:] + [""] * (10 - len(r) - 1))
    bj = bj + [""] * (9 - len(bj))
    prod_rows.append(bj)
    prod_sheet_rows.append(i)

if not prod_rows:
    st.info("商品データなし")
    st.stop()

df_prod = pd.DataFrame(prod_rows, columns=prod_cols)
for col in ["商品代(元)", "入荷数", "商品重さ(g)", "国内送料(元)"]:
    df_prod[col] = df_prod[col].apply(lambda v: _to_num(v) if v not in (None, "") else None)

prod_editable_text = {"商品名"}
prod_editable_num = {"商品代(元)", "入荷数", "商品重さ(g)", "国内送料(元)"}
prod_config = {}
for col in prod_cols:
    if col in prod_editable_text:
        prod_config[col] = st.column_config.TextColumn(label=f"🟢 {col}")
    elif col in prod_editable_num:
        prod_config[col] = st.column_config.NumberColumn(label=f"🟢 {col}", min_value=0, step=1)
    else:
        prod_config[col] = st.column_config.TextColumn(label=f"🔒 {col} (数式)", disabled=True)

edited_prod = st.data_editor(
    df_prod,
    use_container_width=True,
    height=500,
    hide_index=True,
    num_rows="fixed",
    column_config=prod_config,
    key="prod_editor",
)

# 差分検出
def _norm2(v):
    if v is None or pd.isna(v):
        return ""
    s = str(v).strip()
    try:
        return float(s.replace(",", "").replace("¥", ""))
    except (ValueError, TypeError):
        return s

prod_diffs = []
PROD_LETTER = {"商品名": "B", "商品代(元)": "C", "入荷数": "D", "商品重さ(g)": "E", "国内送料(元)": "G"}
for i, sheet_row in enumerate(prod_sheet_rows):
    for col, letter in PROD_LETTER.items():
        old_v = df_prod.at[i, col]
        new_v = edited_prod.at[i, col]
        if _norm2(old_v) == _norm2(new_v):
            continue
        write_v = "" if pd.isna(new_v) or new_v is None else new_v
        prod_diffs.append({"row": sheet_row, "col": letter, "value": write_v,
                           "label": f"{col} (row{sheet_row})", "old": old_v, "new": new_v})

if prod_diffs:
    try:
        ws.batch_update(
            [{"range": f"{d['col']}{d['row']}", "values": [[d["value"]]]} for d in prod_diffs],
            value_input_option="USER_ENTERED",
        )
        sheets._invalidate_one("02_原価計算用")
        st.toast(f"💾 商品テーブル 自動保存 {len(prod_diffs)}件", icon="✅")
        st.rerun()
    except Exception as e:
        st.error(f"❌ 商品テーブル 自動保存失敗: {e}")
else:
    st.caption("✅ 変更なし(編集→Enterで自動保存)")
