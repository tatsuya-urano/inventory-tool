"""📱 モバイル棚卸 — 小分類順の一覧入力(スマホ最適化)

小分類を降順で並べ、各SKUの「実カウント数」を入力 → 04のG列(月初在庫)を
逆算して 自社倉庫(F) が実カウントと一致するよう反映する。

逆算ロジック(列移設に強い):
  F = G + (I - J - 当月売上 - Z - S)  ← G以外はGに依存しない
  よって G_new = G_old + (実カウント - 現在のF) とすれば F_new = 実カウント。
"""
import streamlit as st
import pandas as pd

from lib import sheets, ui

st.set_page_config(page_title="モバイル棚卸", page_icon="📱", layout="centered")
ui.sidebar_common()

st.markdown("""
<style>
    .stButton>button {
        height: 52px !important;
        font-size: 18px !important;
        font-weight: 700 !important;
    }
    .stTextInput input, .stNumberInput input {
        font-size: 18px !important;
        height: 46px !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📱 モバイル棚卸")
st.caption("小分類順に実在庫を入力 → 自社倉庫に反映")

with st.spinner("読込中..."):
    try:
        inv_df = sheets.load_inventory()
    except Exception as e:
        st.error("📡 在庫データの取得に失敗しました（サーバー混雑かも）。")
        st.caption(f"詳細: {type(e).__name__}")
        if st.button("🔄 もう一度読み込む"):
            sheets._invalidate_one("04_在庫管理")
            st.rerun()
        st.stop()
    # マスタは小分類の取得だけに使う補助データ。失敗しても棚卸は続行
    try:
        master_df = sheets.load_master()
    except Exception:
        master_df = pd.DataFrame()
        st.warning("⚠ 小分類を取得できませんでした（サーバー混雑）。並びは小分類なしになります。")

if inv_df.empty:
    st.error("在庫データ読込失敗")
    st.stop()

code_col = inv_df.columns[0]
title_col = inv_df.columns[1] if len(inv_df.columns) > 1 else code_col


def _f(v):
    try:
        return int(float(str(v).replace(",", "").replace("¥", "").strip() or 0))
    except (ValueError, TypeError):
        return 0


# 商品コード → 小分類 (マスタ E列=index4) / 販売チャネル (マスタ F列=index5)
small_map = {}
channel_map = {}
if not master_df.empty and len(master_df.columns) > 4:
    for c, s in zip(master_df.iloc[:, 0].astype(str).str.strip(),
                    master_df.iloc[:, 4].astype(str)):
        if c:
            small_map[c] = s.strip()
if not master_df.empty and len(master_df.columns) > 5:
    for c, ch in zip(master_df.iloc[:, 0].astype(str).str.strip(),
                     master_df.iloc[:, 5].astype(str)):
        if c:
            channel_map[c] = ch.strip()

# 在庫行 → 作業用テーブル (Amazon専売=AMA専売 は自社倉庫に無いので除外)
rows = []
for _, r in inv_df.iterrows():
    code = str(r[code_col]).strip()
    if not code:
        continue
    if channel_map.get(code) == "AMA専売":
        continue
    rows.append({
        "小分類": small_map.get(code, ""),
        "SKU": code,
        "_G": _f(r.iloc[6]) if len(r) > 6 else 0,    # G 月初在庫
        "現在庫": _f(r.iloc[5]) if len(r) > 5 else 0,  # F 自社倉庫(計算値)
    })
work = pd.DataFrame(rows)

# 絞り込み
smalls = sorted([s for s in work["小分類"].unique() if s], reverse=True)
sel = st.selectbox("小分類で絞り込み", ["（すべて）"] + smalls, key="mob_count_small")
kw = st.text_input("🔍 SKU検索", "", key="mob_count_kw", placeholder="SKUの一部")

view = work.copy()
if sel != "（すべて）":
    view = view[view["小分類"] == sel]
if kw.strip():
    view = view[view["SKU"].str.contains(kw, case=False, na=False)]

# 小分類 降順 → SKU 昇順
view = view.sort_values(["小分類", "SKU"], ascending=[False, True]).reset_index(drop=True)

if view.empty:
    st.warning("該当SKUなし")
    st.stop()

# 入力欄は空欄スタート。数字を入れた行だけ反映(空欄=現在庫のまま)
# ※現在庫を初期値にすると、スマホで「90」と打つと既存桁の後ろに付いて「990」等になる
view["実カウント"] = pd.array([pd.NA] * len(view), dtype="Int64")

st.caption(f"{len(view)}件　実カウント欄に実数を入力した行だけ、その数になるよう月初在庫(G)を逆算反映(空欄はスキップ)")

edited = st.data_editor(
    view[["小分類", "SKU", "現在庫", "実カウント"]],
    use_container_width=True,
    hide_index=True,
    height=520,
    num_rows="fixed",
    # SKU・現在庫は非表示(保存の照合/逆算用に内部データとしては保持)
    # 2列だけ&width小で、横スクロールなしに一画面へ収める
    column_order=("小分類", "実カウント"),
    column_config={
        "小分類": st.column_config.TextColumn(disabled=True, width="small"),
        "SKU": st.column_config.TextColumn(disabled=True),
        "現在庫": st.column_config.NumberColumn("現在庫", disabled=True, format="%d", width="small"),
        "実カウント": st.column_config.NumberColumn("🟢実カウント", min_value=0, step=1, format="%d", width="small"),
    },
    key="mob_count_editor",
)

# 変更行を抽出して逆算
emap = dict(zip(edited["SKU"].astype(str), edited["実カウント"]))
gmap = dict(zip(view["SKU"], view["_G"]))
fmap = dict(zip(view["SKU"], view["現在庫"]))
changes = []
for sku, newc in emap.items():
    if newc is None or pd.isna(newc):
        continue
    newc = int(newc)
    f_old = int(fmap.get(sku, 0))
    if newc == f_old:
        continue
    g_new = int(gmap.get(sku, 0)) + (newc - f_old)
    changes.append((sku, newc, g_new))

st.markdown(f"### ✏️ 変更 {len(changes)} 件")
if changes:
    st.dataframe(
        pd.DataFrame(changes, columns=["SKU", "実カウント", "新・月初(G)"]),
        hide_index=True, use_container_width=True,
    )

if st.button(f"💾 {len(changes)}件を在庫に反映", type="primary",
             use_container_width=True, disabled=not changes):
    try:
        ss = sheets.get_spreadsheet()
        ws = ss.worksheet("04_在庫管理")
        codes = ws.col_values(1)
        row_of = {}
        for i, c in enumerate(codes, start=1):
            if i >= 7 and c.strip():
                row_of.setdefault(c.strip(), i)
        reqs, miss = [], []
        for sku, newc, g_new in changes:
            row = row_of.get(sku)
            if not row:
                miss.append(sku)
                continue
            reqs.append({"range": f"G{row}", "values": [[g_new]]})
        if reqs:
            sheets.safe_batch_update(ws, reqs, value_input_option="USER_ENTERED")
            sheets._invalidate_one("04_在庫管理")
        st.success(
            f"✅ {len(reqs)}件反映。自社倉庫(F)が実カウントに一致します"
            + (f" / ⚠未マッチ {len(miss)}件" if miss else "")
        )
        st.balloons()
    except Exception as e:
        st.error(f"反映失敗: {e}")

st.markdown("---")
st.caption("📌 実カウント=倉庫の実物数。変えた行だけが反映対象です(現在庫と同じ行はスキップ)。Amazon専売(AMA専売)は自社倉庫に無いので非表示")
