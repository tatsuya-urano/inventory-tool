"""
🔐 認証情報設定

楽天RMS / Amazon SP-API / LINE Notify の認証情報を画面から登録
→ .streamlit/secrets.toml に自動保存
"""
from pathlib import Path

import streamlit as st
import toml

from lib import ui

st.set_page_config(page_title="認証設定", page_icon="🔐", layout="wide")
st.title("🔐 認証情報設定")
st.caption("楽天RMS / Amazon SP-API / LINE Notify")
ui.sidebar_common()

SECRETS_PATH = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"

# ===========================================================
# 既存値の読み込み
# ===========================================================
def load_existing():
    if SECRETS_PATH.exists():
        try:
            return toml.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

existing = load_existing()
rakuten_e = existing.get("rakuten", {})
amazon_e  = existing.get("amazon", {})
line_e    = existing.get("line", {})

# ===========================================================
# 状態確認
# ===========================================================
def _mask(v):
    if not v:
        return "（未設定）"
    s = str(v)
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "*" * (len(s) - 8) + s[-4:]

st.markdown("### 現在の設定状態")
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**🏪 楽天RMS**")
    st.caption(f"service_secret: {_mask(rakuten_e.get('service_secret'))}")
    st.caption(f"license_key: {_mask(rakuten_e.get('license_key'))}")
    st.caption(f"shop_url: {rakuten_e.get('shop_url') or '（未設定）'}")
with col2:
    st.markdown("**📦 Amazon SP-API**")
    st.caption(f"lwa_client_id: {_mask(amazon_e.get('lwa_client_id'))}")
    st.caption(f"lwa_client_secret: {_mask(amazon_e.get('lwa_client_secret'))}")
    st.caption(f"refresh_token: {_mask(amazon_e.get('refresh_token'))}")
    st.caption(f"seller_id: {_mask(amazon_e.get('seller_id'))}")
    st.caption(f"marketplace_id: {amazon_e.get('marketplace_id') or '（未設定）'}")
with col3:
    st.markdown("**📱 LINE Messaging API**")
    st.caption(f"channel_token: {_mask(line_e.get('channel_access_token'))}")
    st.caption(f"user_id: {_mask(line_e.get('user_id'))}")

st.markdown("---")

# ===========================================================
# 入力フォーム
# ===========================================================
with st.form("secrets_form"):
    st.markdown("### 🏪 楽天RMS Web Service API")
    st.caption("楽天RMS管理画面 → 拡張サービス → API設定 から取得")
    rakuten_secret = st.text_input(
        "Service Secret (SP000000_xxxxxxxx)",
        value=rakuten_e.get("service_secret", ""),
        type="password",
        key="ra_secret",
    )
    rakuten_license = st.text_input(
        "License Key (SL000000_xxxxxxxx)",
        value=rakuten_e.get("license_key", ""),
        type="password",
        key="ra_license",
    )
    rakuten_shop = st.text_input(
        "Shop URL（店舗識別子）",
        value=rakuten_e.get("shop_url", ""),
        help="例: yourshop.rakuten.co.jp なら 'yourshop'",
        key="ra_shop",
    )

    st.markdown("---")
    st.markdown("### 📦 Amazon SP-API")
    st.caption("Seller Central → Develop Apps → 既存アプリの認証情報")
    amazon_client_id = st.text_input(
        "LWA Client ID (amzn1.application-oa2-client.xxx)",
        value=amazon_e.get("lwa_client_id", ""),
        type="password",
        key="am_id",
    )
    amazon_client_secret = st.text_input(
        "LWA Client Secret (amzn1.oa2-cs.v1.xxx)",
        value=amazon_e.get("lwa_client_secret", ""),
        type="password",
        key="am_secret",
    )
    amazon_refresh = st.text_input(
        "Refresh Token (Atzr|xxx)",
        value=amazon_e.get("refresh_token", ""),
        type="password",
        key="am_refresh",
    )
    amazon_seller = st.text_input(
        "Seller ID (Aで始まる ID)",
        value=amazon_e.get("seller_id", ""),
        key="am_seller",
    )
    amazon_marketplace = st.text_input(
        "Marketplace ID",
        value=amazon_e.get("marketplace_id", "A1VC38T7YXB528"),
        help="日本: A1VC38T7YXB528",
        key="am_market",
    )

    st.markdown("---")
    st.markdown("### 📱 LINE Messaging API（公式チャットボット・任意）")
    st.caption("⚠ LINE Notify は2025年3月末で終了しました。Messaging APIを使用")
    line_channel_token = st.text_input(
        "Channel Access Token",
        value=line_e.get("channel_access_token", ""),
        type="password",
        help="LINE Developers Console で取得",
        key="ln_channel",
    )
    line_user_id = st.text_input(
        "User ID（送信先）",
        value=line_e.get("user_id", ""),
        type="password",
        help="LINE Official Account の User ID（U で始まる）",
        key="ln_user",
    )

    submitted = st.form_submit_button("💾 保存", type="primary", use_container_width=True)

if submitted:
    new_secrets = {
        "rakuten": {
            "service_secret": rakuten_secret.strip(),
            "license_key": rakuten_license.strip(),
            "shop_url": rakuten_shop.strip(),
        },
        "amazon": {
            "lwa_client_id": amazon_client_id.strip(),
            "lwa_client_secret": amazon_client_secret.strip(),
            "refresh_token": amazon_refresh.strip(),
            "seller_id": amazon_seller.strip(),
            "marketplace_id": amazon_marketplace.strip(),
        },
        "line": {
            "channel_access_token": line_channel_token.strip(),
            "user_id": line_user_id.strip(),
        },
    }
    try:
        SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SECRETS_PATH.write_text(toml.dumps(new_secrets), encoding="utf-8")
        st.success(f"✅ 保存完了: {SECRETS_PATH}")
        st.balloons()
        st.info("⚠ 反映するには Streamlit を再起動してください（Ctrl+C → streamlit run app.py）")
    except Exception as e:
        st.error(f"保存失敗: {e}")

# ===========================================================
# 接続テスト
# ===========================================================
st.markdown("---")
st.markdown("### 🔬 接続テスト")
st.caption("各APIに認証情報で実際に接続できるかチェック")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🏪 楽天RMS テスト"):
        if not rakuten_e.get("service_secret"):
            st.error("先に保存してください")
        else:
            with st.spinner("接続中..."):
                try:
                    import requests, base64
                    auth = base64.b64encode(
                        f"{rakuten_e['service_secret']}:{rakuten_e['license_key']}".encode()
                    ).decode()
                    # 楽天RMS: 商品検索API（在庫API系の代表）
                    # ItemAPI v1.0 検索エンドポイント
                    r = requests.get(
                        "https://api.rms.rakuten.co.jp/es/2.0/items/search?hits=1",
                        headers={"Authorization": f"ESA {auth}"},
                        timeout=10,
                    )
                    if r.status_code == 200:
                        st.success(f"✅ 楽天RMS 接続OK（商品検索API）")
                        st.code(r.text[:500])
                    elif r.status_code == 401:
                        st.error("❌ 401 認証失敗 — Service Secret / License Key を確認")
                    elif r.status_code == 404:
                        # 別のエンドポイントを試す
                        r2 = requests.get(
                            "https://api.rms.rakuten.co.jp/es/1.0/inventory/get",
                            headers={"Authorization": f"ESA {auth}"},
                            params={"itemUrl": "test"},
                            timeout=10,
                        )
                        if r2.status_code in (200, 400):
                            st.success(f"✅ 楽天RMS 接続OK（在庫API、{r2.status_code}）")
                            st.caption("400は『そのSKUなし』で正常応答 = 認証は通っている")
                        else:
                            st.error(f"❌ {r2.status_code}: {r2.text[:300]}")
                    else:
                        st.error(f"❌ {r.status_code}: {r.text[:300]}")
                except Exception as e:
                    st.error(f"失敗: {e}")

with col2:
    if st.button("📦 Amazon SP-API テスト"):
        if not amazon_e.get("refresh_token"):
            st.error("先に保存してください")
        else:
            with st.spinner("接続中..."):
                try:
                    import requests
                    # LWA トークン取得
                    r = requests.post(
                        "https://api.amazon.com/auth/o2/token",
                        data={
                            "grant_type": "refresh_token",
                            "refresh_token": amazon_e["refresh_token"],
                            "client_id": amazon_e["lwa_client_id"],
                            "client_secret": amazon_e["lwa_client_secret"],
                        },
                        timeout=10,
                    )
                    if r.status_code == 200:
                        access_token = r.json().get("access_token")
                        # marketplaceParticipations を取得
                        r2 = requests.get(
                            "https://sellingpartnerapi-fe.amazon.com/sellers/v1/marketplaceParticipations",
                            headers={"x-amz-access-token": access_token},
                            timeout=10,
                        )
                        if r2.status_code == 200:
                            st.success(f"✅ Amazon SP-API 接続OK")
                            st.code(r2.text[:500])
                        else:
                            st.error(f"❌ SP-API {r2.status_code}: {r2.text[:300]}")
                    else:
                        st.error(f"❌ LWA {r.status_code}: {r.text[:300]}")
                except Exception as e:
                    st.error(f"失敗: {e}")

with col3:
    if st.button("📱 LINE Messaging テスト"):
        if not line_e.get("channel_access_token") or not line_e.get("user_id"):
            st.error("先に保存してください（Channel Token + User ID 両方必要）")
        else:
            with st.spinner("送信中..."):
                try:
                    import requests
                    r = requests.post(
                        "https://api.line.me/v2/bot/message/push",
                        headers={
                            "Authorization": f"Bearer {line_e['channel_access_token']}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "to": line_e["user_id"],
                            "messages": [{"type": "text", "text": "Streamlit 接続テスト"}],
                        },
                        timeout=10,
                    )
                    if r.status_code == 200:
                        st.success("✅ LINE Messaging API テスト送信OK")
                    else:
                        st.error(f"❌ {r.status_code}: {r.text[:300]}")
                except Exception as e:
                    st.error(f"失敗: {e}")
