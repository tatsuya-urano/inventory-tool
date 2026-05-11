"""
📤 在庫PUSH

04_在庫管理 のH列(販売可能在庫合計) を 楽天 + Amazon FBM に同期PUSH
- マスタAE列に値があるSKU = Amazon SKUで送信
- マスタAE列が空 = 楽天SKUと同名でAmazonに送信
- コバリ子は親在庫 ÷ 係数 で計算してPUSH
- バッファ（マスタZ列）を引いた数量をPUSH
"""
import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="在庫PUSH", page_icon="📤", layout="wide")
st.title("📤 在庫PUSH（楽天 / Amazon FBM）")
st.caption("04_在庫管理 のF列(自社倉庫在庫) を楽天 / Amazon に逆掲載")
ui.sidebar_common()


# ===========================================================
# キャッシュ化された PUSH対象計算（5分キャッシュ）
# ===========================================================
@st.cache_data(ttl=300, show_spinner="🚀 PUSH対象を計算中（初回のみ）...")
def _compute_push_targets():
    inv = sheets.load_inventory()
    master = sheets.load_master()
    if inv.empty or master.empty:
        return None, None

    M_CODE = master.columns[0]
    M_SMALL_CAT = master.columns[4] if len(master.columns) > 4 else None  # E列 小分類
    M_CHANNEL = master.columns[5] if len(master.columns) > 5 else None
    M_PARENT = master.columns[20] if len(master.columns) > 20 else None
    M_RATIO = master.columns[21] if len(master.columns) > 21 else None
    M_BUFFER = master.columns[25] if len(master.columns) > 25 else None
    M_AE = master.columns[30] if len(master.columns) > 30 else None
    INV_CODE = inv.columns[0]
    INV_F = inv.columns[5] if len(inv.columns) > 5 else None
    if not INV_F:
        return None, None

    def _n(v):
        try:
            return float(str(v).replace(",", "").replace("¥", "").strip())
        except (ValueError, TypeError):
            return 0.0

    # 04のSKU→F列マップ（高速 zip）
    inv_map = {}
    for code, f in zip(inv[INV_CODE].astype(str).str.strip(), inv[INV_F]):
        if code:
            inv_map[code] = _n(f)

    rakuten_targets = []
    amazon_targets = []
    for _, r in master.iterrows():
        code = str(r[M_CODE]).strip()
        if not code:
            continue
        ch = str(r[M_CHANNEL]).strip() if M_CHANNEL else ""
        small = str(r[M_SMALL_CAT]).strip() if M_SMALL_CAT else ""
        parent = str(r[M_PARENT]).strip() if M_PARENT else ""
        ratio = _n(r[M_RATIO]) if M_RATIO else 0
        buf = _n(r[M_BUFFER]) if M_BUFFER else 0
        amz_sku = str(r[M_AE]).strip() if M_AE else ""

        if parent and ratio > 0:
            parent_stock = inv_map.get(parent, 0)
            available = int(parent_stock // ratio)
            breakdown = f"親{parent}/{ratio}={available}"
        else:
            available = int(inv_map.get(code, 0))
            breakdown = f"自身F={available}"
        new_stock = max(0, available - int(buf))

        if ch in ("楽天専売", "両方"):
            rakuten_targets.append({
                "sku": code, "小分類": small, "key": code, "quantity": new_stock,
                "buffer": int(buf), "breakdown": breakdown,
            })
        if ch in ("AMA専売", "両方"):
            amazon_targets.append({
                "sku": code, "小分類": small, "key": amz_sku or code, "quantity": new_stock,
                "buffer": int(buf), "breakdown": breakdown,
            })
    return rakuten_targets, amazon_targets


rakuten_t, amazon_t = _compute_push_targets()
if rakuten_t is None:
    st.error("データ取得失敗。04 or マスタが空")
    st.stop()

# ===========================================================
# 表示
# ===========================================================
c1, c2 = st.columns(2)
c1.metric("🏪 楽天 PUSH対象", f"{len(rakuten_t):,}件")
c2.metric("📦 Amazon FBM PUSH対象", f"{len(amazon_t):,}件")

st.markdown("---")

tab1, tab2, tab3 = st.tabs(["🏪 楽天", "📦 Amazon FBM", "🚀 一括PUSH"])

# -----------------------------------------------------------
# Tab 1: 楽天
# -----------------------------------------------------------
with tab1:
    st.markdown("### 楽天PUSH対象一覧")
    st.caption("⚙️ チェックを入れたSKUのみPUSH（チェック0件なら全件PUSH）/ quantity列も編集可")
    keyword = st.text_input("商品コード・小分類検索", "", key="ra_kw")
    df_ra = pd.DataFrame(rakuten_t)
    if keyword and not df_ra.empty:
        mask = df_ra["sku"].astype(str).str.contains(keyword, case=False, na=False)
        if "小分類" in df_ra.columns:
            mask |= df_ra["小分類"].astype(str).str.contains(keyword, case=False, na=False)
        df_ra = df_ra[mask]
    df_ra = df_ra.copy()
    df_ra.insert(0, "送信", False)
    st.caption(f"{len(df_ra):,}件")

    df_ra_edited = st.data_editor(
        df_ra,
        use_container_width=True,
        height=400,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "送信":      st.column_config.CheckboxColumn(label="☑ 送信", help="チェック入れた行だけPUSH。0件なら全件"),
            "sku":       st.column_config.TextColumn(disabled=True, label="🔒 商品コード"),
            "小分類":    st.column_config.TextColumn(disabled=True, label="🔒 小分類"),
            "key":       st.column_config.TextColumn(disabled=True, label="🔒 楽天SKU(送信先)"),
            "quantity":  st.column_config.NumberColumn(label="🟢 PUSH数量", min_value=0, step=1),
            "buffer":    st.column_config.NumberColumn(disabled=True, label="🔒 バッファ"),
            "breakdown": st.column_config.TextColumn(disabled=True, label="🔒 内訳"),
        },
        key="ra_editor",
    )

    # 送信対象の絞込
    checked_ra = df_ra_edited[df_ra_edited["送信"] == True]
    if len(checked_ra) > 0:
        st.info(f"☑ {len(checked_ra)}件を選択中（これだけPUSH）")
        df_ra_send = checked_ra
    else:
        st.caption(f"☐ チェック0件 → 全{len(df_ra_edited)}件をPUSH")
        df_ra_send = df_ra_edited

    # デバッグ: 1件の在庫情報を取得 + デバッグPUSH
    with st.expander("🐛 楽天デバッグ"):
        debug_sku = st.text_input("商品管理番号", "", key="ra_debug_sku")
        debug_qty = st.number_input("PUSHしたい数量", min_value=0, value=10, key="ra_debug_qty")
        debug_vid = st.text_input("variantId（空ならmanageNumberと同値）", "", key="ra_debug_vid")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            if st.button("📡 在庫情報取得"):
                from lib.push_clients import RakutenRMSClient
                client = RakutenRMSClient()
                info = client.get_inventory(debug_sku)
                st.json(info)
        with col_d2:
            if st.button("🐛 デバッグPUSH（送信内容+応答全文を表示）"):
                from lib.push_clients import RakutenRMSClient
                client = RakutenRMSClient()
                result = client.update_inventory_debug(debug_sku, debug_qty, debug_vid or None)
                st.json(result)

    if st.button("🚀 楽天にPUSH実行", type="primary", key="push_ra"):
        from lib.push_clients import RakutenRMSClient
        try:
            client = RakutenRMSClient()
        except RuntimeError as e:
            st.error(str(e))
            st.stop()

        if df_ra_send.empty:
            st.warning("対象なし")
        else:
            updates = [{"item_url": r["key"], "inventory": int(r["quantity"])} for _, r in df_ra_send.iterrows()]
            progress = st.progress(0, text="送信中...")
            result = {"success": 0, "failed": 0, "errors": []}
            for i, u in enumerate(updates):
                ok, msg = client.update_inventory(u["item_url"], u["inventory"])
                if ok:
                    result["success"] += 1
                else:
                    result["failed"] += 1
                    result["errors"].append({"item_url": u["item_url"], "qty": u["inventory"], "error": msg})
                progress.progress((i + 1) / len(updates), text=f"{i+1}/{len(updates)}")
            progress.empty()

            st.success(f"✅ 成功: {result['success']}件 / 失敗: {result['failed']}件")
            if result["errors"]:
                with st.expander(f"⚠ エラー詳細 ({len(result['errors'])}件)"):
                    st.dataframe(pd.DataFrame(result["errors"]), hide_index=True)
            # チェックボックスをリセット（data_editorのkeyを変える）
            if "ra_editor" in st.session_state:
                del st.session_state["ra_editor"]
            st.rerun()

# -----------------------------------------------------------
# Tab 2: Amazon FBM
# -----------------------------------------------------------
with tab2:
    st.markdown("### Amazon FBM PUSH対象一覧")
    st.caption("⚙️ チェックを入れたSKUのみPUSH（チェック0件なら全件PUSH）/ quantity列も編集可")
    keyword2 = st.text_input("商品コード・小分類検索", "", key="am_kw")
    df_am = pd.DataFrame(amazon_t)
    if keyword2 and not df_am.empty:
        mask2 = df_am["sku"].astype(str).str.contains(keyword2, case=False, na=False)
        if "小分類" in df_am.columns:
            mask2 |= df_am["小分類"].astype(str).str.contains(keyword2, case=False, na=False)
        df_am = df_am[mask2]
    df_am = df_am.copy()
    df_am.insert(0, "送信", False)
    st.caption(f"{len(df_am):,}件")

    df_am_edited = st.data_editor(
        df_am,
        use_container_width=True,
        height=400,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "送信":      st.column_config.CheckboxColumn(label="☑ 送信", help="チェック入れた行だけPUSH。0件なら全件"),
            "sku":       st.column_config.TextColumn(disabled=True, label="🔒 商品コード"),
            "小分類":    st.column_config.TextColumn(disabled=True, label="🔒 小分類"),
            "key":       st.column_config.TextColumn(disabled=True, label="🔒 Amazon SKU(送信先)"),
            "quantity":  st.column_config.NumberColumn(label="🟢 PUSH数量", min_value=0, step=1),
            "buffer":    st.column_config.NumberColumn(disabled=True, label="🔒 バッファ"),
            "breakdown": st.column_config.TextColumn(disabled=True, label="🔒 内訳"),
        },
        key="am_editor",
    )

    # 送信対象の絞込
    checked_am = df_am_edited[df_am_edited["送信"] == True]
    if len(checked_am) > 0:
        st.info(f"☑ {len(checked_am)}件を選択中（これだけPUSH）")
        df_am_send = checked_am
    else:
        st.caption(f"☐ チェック0件 → 全{len(df_am_edited)}件をPUSH")
        df_am_send = df_am_edited

    if st.button("🚀 AmazonにPUSH実行", type="primary", key="push_am"):
        from lib.push_clients import AmazonSPClient
        try:
            client = AmazonSPClient()
        except RuntimeError as e:
            st.error(str(e))
            st.stop()

        if df_am_send.empty:
            st.warning("対象なし")
        else:
            updates = [{"sku": r["key"], "quantity": int(r["quantity"])} for _, r in df_am_send.iterrows()]
            progress = st.progress(0, text="送信中...")
            result = {"success": 0, "failed": 0, "errors": []}
            for i, u in enumerate(updates):
                ok, msg = client.update_inventory(u["sku"], u["quantity"])
                if ok:
                    result["success"] += 1
                else:
                    result["failed"] += 1
                    result["errors"].append({"sku": u["sku"], "error": msg})
                progress.progress((i + 1) / len(updates), text=f"{i+1}/{len(updates)}")
            progress.empty()

            st.success(f"✅ 成功: {result['success']}件 / 失敗: {result['failed']}件")
            if result["errors"]:
                with st.expander(f"⚠ エラー詳細 ({len(result['errors'])}件)"):
                    st.dataframe(pd.DataFrame(result["errors"]), hide_index=True)
            # チェックボックスをリセット
            if "am_editor" in st.session_state:
                del st.session_state["am_editor"]
            st.rerun()

# -----------------------------------------------------------
# Tab 3: 一括PUSH
# -----------------------------------------------------------
with tab3:
    st.markdown("### 楽天 + Amazon 一括PUSH")
    st.warning(
        "⚠ 全SKUに対して 楽天と Amazon FBM の両方に PUSH します。\n"
        "API呼び出し回数が多くなるため、時間がかかります"
    )
    st.caption(f"楽天: {len(rakuten_t):,}件 / Amazon: {len(amazon_t):,}件")

    if st.button("🚀 全件 一括PUSH実行", type="primary", key="push_all"):
        from lib.push_clients import RakutenRMSClient, AmazonSPClient
        try:
            rc = RakutenRMSClient()
            ac = AmazonSPClient()
        except RuntimeError as e:
            st.error(str(e))
            st.stop()

        # 楽天
        st.markdown("#### 🏪 楽天")
        ra_progress = st.progress(0, text="送信中...")
        ra_result = {"success": 0, "failed": 0}
        for i, t in enumerate(rakuten_t):
            ok, _ = rc.update_inventory(t["key"], t["quantity"])
            if ok: ra_result["success"] += 1
            else:  ra_result["failed"] += 1
            ra_progress.progress((i + 1) / max(len(rakuten_t), 1), text=f"{i+1}/{len(rakuten_t)}")
        ra_progress.empty()
        st.success(f"✅ 楽天 成功:{ra_result['success']} 失敗:{ra_result['failed']}")

        # Amazon
        st.markdown("#### 📦 Amazon FBM")
        am_progress = st.progress(0, text="送信中...")
        am_result = {"success": 0, "failed": 0}
        for i, t in enumerate(amazon_t):
            ok, _ = ac.update_inventory(t["key"], t["quantity"])
            if ok: am_result["success"] += 1
            else:  am_result["failed"] += 1
            am_progress.progress((i + 1) / max(len(amazon_t), 1), text=f"{i+1}/{len(amazon_t)}")
        am_progress.empty()
        st.success(f"✅ Amazon 成功:{am_result['success']} 失敗:{am_result['failed']}")
        st.balloons()
