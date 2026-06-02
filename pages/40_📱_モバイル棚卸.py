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
    /* 反映(送信)ボタンを画面右下に常駐させる。入力後すぐ押せるように */
    div[data-testid="stFormSubmitButton"] {
        position: fixed;
        bottom: 16px;
        right: 16px;
        z-index: 9999;
        width: auto !important;
    }
    div[data-testid="stFormSubmitButton"] button {
        height: 52px !important;
        font-size: 17px !important;
        font-weight: 700 !important;
        border-radius: 28px !important;
        padding: 0 22px !important;
        box-shadow: 0 4px 14px rgba(0,0,0,0.35);
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

# 在庫行 → 作業用テーブル
#  - Amazon専売(AMA専売) は自社倉庫に無いので除外
#  - 小分類なし(マスタ未登録)は終売とみなし除外。ただしマスタ取得失敗時(small_map空)は
#    全行が小分類なし扱いになり全滅するため、その時は除外しない
have_small = bool(small_map)
rows = []
for _, r in inv_df.iterrows():
    code = str(r[code_col]).strip()
    if not code:
        continue
    if channel_map.get(code) == "AMA専売":
        continue
    small = small_map.get(code, "")
    if have_small and not small:
        continue  # 小分類なし=終売とみなし非表示
    rows.append({
        "小分類": small,
        "SKU": code,
        "_G": _f(r.iloc[6]) if len(r) > 6 else 0,    # G 月初在庫
        "現在庫": _f(r.iloc[5]) if len(r) > 5 else 0,  # F 自社倉庫(計算値)
    })
work = pd.DataFrame(rows)

# 絞り込み
smalls = sorted([s for s in work["小分類"].unique() if s])
sel = st.selectbox("小分類で絞り込み", ["（すべて）"] + smalls, key="mob_count_small")
kw = st.text_input("🔍 SKU検索", "", key="mob_count_kw", placeholder="SKUの一部")

view = work.copy()
if sel != "（すべて）":
    view = view[view["小分類"] == sel]
if kw.strip():
    view = view[view["SKU"].str.contains(kw, case=False, na=False)]

# 小分類 昇順 → SKU 昇順(上る順)
view = view.sort_values(["小分類", "SKU"], ascending=[True, True]).reset_index(drop=True)

if view.empty:
    st.warning("該当SKUなし")
    st.stop()

# data_editorはスマホで数値が累積・消せない不具合があるため、st.formの
# 行ごとnumber_inputに変更。formは送信ボタンを押すまで再実行しないので、
# 入力途中で数字が勝手に足される/消せない問題が起きない。
# 件数が多いと重いので200件ずつページ送り。ページ内で入力→反映を繰り返す。
PAGE_SIZE = 200
total = len(view)
n_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
if n_pages > 1:
    page = st.selectbox(
        "ページ (200件ずつ)",
        list(range(1, n_pages + 1)),
        format_func=lambda p: f"{p}/{n_pages}ページ "
                              f"({(p-1)*PAGE_SIZE+1}〜{min(p*PAGE_SIZE, total)}件)",
        key="mob_count_page",
    )
else:
    page = 1
start = (page - 1) * PAGE_SIZE
view_page = view.iloc[start:start + PAGE_SIZE].reset_index(drop=True)

st.caption(f"全{total}件中 {start+1}〜{min(start+PAGE_SIZE, total)}件目を表示　"
           "各SKUに実数を入力 → 「反映」を押した時だけ保存。"
           "空欄の行はスキップ(現在庫のまま)。ページを変える前に反映を押してください")

gmap = dict(zip(view_page["SKU"], view_page["_G"]))
fmap = dict(zip(view_page["SKU"], view_page["現在庫"]))

with st.form("mob_count_form", clear_on_submit=False):
    for _, row in view_page.iterrows():
        sku = row["SKU"]
        f_old = int(row["現在庫"])
        small = row["小分類"] or "（小分類なし）"
        st.number_input(
            f"{small}　|　{sku}　(現在 {f_old})",
            min_value=0, step=1, value=None,
            key=f"mob_cnt_{sku}",
        )
    submitted = st.form_submit_button(
        "💾 反映", type="primary", use_container_width=False)

if submitted:
    # 入力値を集計して逆算 (空欄=None はスキップ、現在庫と同じ値もスキップ)
    changes = []
    for sku in view_page["SKU"]:
        newc = st.session_state.get(f"mob_cnt_{sku}")
        if newc is None:
            continue
        newc = int(newc)
        f_old = int(fmap.get(sku, 0))
        if newc == f_old:
            continue
        g_new = int(gmap.get(sku, 0)) + (newc - f_old)
        changes.append((sku, newc, g_new))

    if not changes:
        st.info("入力された変更がありません(空欄か現在庫と同じ値のみ)")
    else:
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
                r_idx = row_of.get(sku)
                if not r_idx:
                    miss.append(sku)
                    continue
                reqs.append({"range": f"G{r_idx}", "values": [[g_new]]})
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

# 下部のページ遷移(スクロールし切った場所からでも移動できるように)
if n_pages > 1:
    st.markdown("---")
    st.caption(f"ページ {page}/{n_pages}　※移動前に「反映」を押してください(未反映の入力は消えます)")
    pcol1, pcol2, pcol3 = st.columns([1, 1, 1])
    if pcol1.button("◀ 前へ", use_container_width=True,
                    disabled=page <= 1, key="mob_count_prev"):
        st.session_state["mob_count_page"] = page - 1
        st.rerun()
    pcol2.markdown(
        f"<div style='text-align:center;line-height:52px;font-weight:700;'>"
        f"{page} / {n_pages}</div>", unsafe_allow_html=True)
    if pcol3.button("次へ ▶", use_container_width=True,
                    disabled=page >= n_pages, key="mob_count_next"):
        st.session_state["mob_count_page"] = page + 1
        st.rerun()

st.markdown("---")
st.caption("📌 実カウント=倉庫の実物数。入力した行だけが反映対象(空欄・現在庫と同じ値はスキップ)。Amazon専売(AMA専売)は自社倉庫に無いので非表示")
