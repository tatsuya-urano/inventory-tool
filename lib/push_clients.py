"""
楽天RMS / Amazon SP-API 在庫PUSHクライアント

GAS版の pushRakutenInventory / pushAmazonFBMInventory を Python移植
"""
import base64
import json
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st


# ============================================================
# 楽天RMS 在庫更新
# ============================================================
class RakutenRMSClient:
    """楽天RMS Web Service API クライアント

    GAS版 getRakutenSkuDictV2 と同様、items/search で
    manageNumber + variantId の対応辞書を自動構築する。
    """

    def __init__(self):
        try:
            self.service_secret = st.secrets["rakuten"]["service_secret"]
            self.license_key    = st.secrets["rakuten"]["license_key"]
        except (KeyError, FileNotFoundError):
            raise RuntimeError("楽天RMS認証情報が未設定です。🔐 認証設定ページで登録してください")
        if not self.service_secret or not self.license_key:
            raise RuntimeError("楽天RMS認証情報が空です")

        auth = base64.b64encode(
            f"{self.service_secret}:{self.license_key}".encode()
        ).decode()
        self.headers = {"Authorization": f"ESA {auth}"}

    @staticmethod
    @st.cache_data(ttl=900, show_spinner="🏪 楽天SKU辞書を取得中（初回のみ・数秒〜30秒）...")
    def build_sku_dict(_dummy=None) -> dict:
        """楽天 items/search で全商品の {結合SKU(manageNumber+variantId): {manageNumber, variantId}} 辞書を構築

        例: pradisecasecatpink → {manageNumber: "pradisecase", variantId: "catpink"}
            またはバリエーション無し → {manageNumber: "xxx", variantId: ""}
        """
        try:
            client = RakutenRMSClient()
        except RuntimeError:
            return {}

        url = "https://api.rms.rakuten.co.jp/es/2.0/items/search"
        dict_ = {}
        offset = 0
        LIMIT = 100
        max_pages = 50  # 最大5000商品まで

        for page in range(max_pages):
            params = {"hits": LIMIT, "offset": offset}
            try:
                r = requests.get(url, headers=client.headers, params=params, timeout=20)
                if r.status_code != 200:
                    break
                data = r.json()
                results = data.get("items") or data.get("results") or []
                if not results:
                    break

                for r_item in results:
                    src = r_item.get("item") or r_item
                    mn = src.get("manageNumber") or src.get("itemNumber")
                    if not mn:
                        continue
                    variants = src.get("variants") or src.get("skus") or src.get("sku")
                    variant_ids = []
                    if variants:
                        if isinstance(variants, list):
                            variant_ids = [v.get("variantId") or v.get("id") or v.get("sku") for v in variants]
                            variant_ids = [v for v in variant_ids if v]
                        elif isinstance(variants, dict):
                            variant_ids = list(variants.keys())

                    if not variant_ids:
                        # バリエーション無し → 結合SKU = manageNumber、variantId は manageNumber と同値
                        dict_[mn] = {"manageNumber": mn, "variantId": mn}
                    else:
                        for vid in variant_ids:
                            combined = mn + vid
                            dict_[combined] = {"manageNumber": mn, "variantId": vid}

                if len(results) < LIMIT:
                    break
                offset += LIMIT
            except Exception:
                break

        return dict_

    def get_inventory(self, manage_number: str) -> dict:
        """商品の在庫情報を取得（複数フィールド名・エンドポイント試行）"""
        attempts = []

        # 試行リスト: (URL, JSON body)
        candidates = [
            # inventories/bulk-get の候補
            ("https://api.rms.rakuten.co.jp/es/2.0/inventories/bulk-get",
             {"manageNumberList": [manage_number]}),
            ("https://api.rms.rakuten.co.jp/es/2.0/inventories/bulk-get",
             {"items": [{"manageNumber": manage_number}]}),
            ("https://api.rms.rakuten.co.jp/es/2.0/inventories/bulk-get",
             {"inventories": [{"manageNumber": manage_number}]}),
            ("https://api.rms.rakuten.co.jp/es/2.0/inventories/bulk-get",
             {"requests": [{"manageNumber": manage_number}]}),
            # items API
            ("https://api.rms.rakuten.co.jp/es/2.0/items/bulk-get",
             {"manageNumbers": [manage_number]}),
            ("https://api.rms.rakuten.co.jp/es/2.0/items/bulk-get",
             {"manageNumberList": [manage_number]}),
        ]

        for url, body in candidates:
            try:
                r = requests.post(
                    url,
                    headers={**self.headers, "Content-Type": "application/json; charset=utf-8"},
                    data=json.dumps(body),
                    timeout=15,
                )
                if r.status_code == 200:
                    return {"source": url, "request": body, "data": r.json()}
                attempts.append({
                    "url": url,
                    "body": body,
                    "status": r.status_code,
                    "error": r.text[:200],
                })
            except Exception as e:
                attempts.append({"url": url, "body": body, "exception": str(e)})

        return {"_error": "全エンドポイント失敗", "attempts": attempts}

    def update_inventory_debug(self, item_url: str, inventory: int, variant_id: str = None) -> dict:
        """デバッグ用: variantId 空 / manageNumber同値 / 指定値 の3パターンを試行"""
        results = []
        candidates_vid = [
            ("空文字（バリエーション無し商品の正解）", ""),
            ("manageNumberと同値", item_url),
        ]
        if variant_id:
            candidates_vid.append((f"指定値 {variant_id}", variant_id))

        url = "https://api.rms.rakuten.co.jp/es/2.0/inventories/bulk-upsert"
        for name, vid in candidates_vid:
            payload = {
                "inventories": [
                    {
                        "manageNumber": item_url,
                        "variantId": vid,
                        "quantity": int(inventory),
                        "mode": "ABSOLUTE",
                    }
                ]
            }
            try:
                r = requests.post(
                    url,
                    headers={**self.headers, "Content-Type": "application/json; charset=utf-8"},
                    data=json.dumps(payload),
                    timeout=15,
                )
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                results.append({
                    "variantId試行": name,
                    "送信payload": payload,
                    "ステータス": r.status_code,
                    "レスポンス": body,
                })
            except Exception as e:
                results.append({"variantId試行": name, "例外": str(e)})

        return {"全試行結果": results}

    def update_inventory(self, item_url: str, inventory: int, variant_id: str = None) -> Tuple[bool, str]:
        """1SKU の在庫数を更新（楽天RMS Inventory API v2.0 bulk-upsert）

        Args:
            item_url: 結合SKU（マスタA列の値、例: "pradisecasecatpink"）
            inventory: 新在庫数
            variant_id: バリエーションID（指定されていればそれを使う、None なら自動辞書から検索）
        """
        # variant_id 未指定なら、SKU辞書から自動検索
        if variant_id is None:
            sku_dict = self.build_sku_dict()
            entry = sku_dict.get(item_url)
            if entry:
                manage_number = entry["manageNumber"]
                variant_id = entry["variantId"]
            else:
                # 辞書にない → 楽天未登録の可能性
                return False, f"楽天SKU辞書に未登録: {item_url}"
        else:
            # variant_id 指定時は item_url を manageNumber としてそのまま使う
            manage_number = item_url

        url = "https://api.rms.rakuten.co.jp/es/2.0/inventories/bulk-upsert"
        payload = {
            "inventories": [
                {
                    "manageNumber": manage_number,
                    "variantId": variant_id,
                    "quantity": int(inventory),
                    "mode": "ABSOLUTE",
                }
            ]
        }
        try:
            r = requests.post(
                url,
                headers={**self.headers, "Content-Type": "application/json; charset=utf-8"},
                data=json.dumps(payload),
                timeout=15,
            )
            code = r.status_code
            text = r.text or ""
            if code not in (200, 204, 207):
                return False, f"HTTP {code}: {text[:300]}"
            # 200/204/207: レスポンス中身を確認
            if not text.strip():
                return True, "OK (empty response)"
            try:
                data = r.json()
            except Exception:
                return True, f"OK (non-JSON): {text[:100]}"

            # results 配列を探す（楽天は results / inventories / items のどれか）
            results = data.get("results") or data.get("inventories") or data.get("items") or []
            if not results:
                # 配列がない=単一結果。data自体がerrorなら失敗
                if data.get("errors"):
                    return False, f"楽天エラー: {json.dumps(data.get('errors'), ensure_ascii=False)[:300]}"
                return True, "OK"

            # 個別判定
            for res in results:
                code_v = res.get("code") or res.get("statusCode")
                is_ok = res.get("isSuccess")
                if code_v in ("OK", "N00-000", 200, "200") or is_ok is True or not code_v:
                    continue
                # NG
                return False, f"{res.get('manageNumber', '?')}: {res.get('message') or code_v}"
            return True, "OK"
        except Exception as e:
            return False, f"例外: {e}"

    def bulk_update_inventory_batch(self, updates: List[Dict], batch_size: int = 100) -> Dict:
        """複数SKUの在庫を bulk-upsert で一括送信（GAS版と同じ仕様）

        Args:
            updates: [{"item_url": "xxx", "inventory": 10, "variant_id": "yyy"}, ...]
            batch_size: 1リクエストあたりの件数（楽天は最大100件）
        """
        url = "https://api.rms.rakuten.co.jp/es/2.0/inventories/bulk-upsert"
        success = 0
        failed = 0
        errors = []
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            inventories = []
            for u in batch:
                inventories.append({
                    "manageNumber": u["item_url"],
                    "variantId": u.get("variant_id") or u["item_url"],
                    "quantity": int(u["inventory"]),
                    "mode": "ABSOLUTE",
                })
            payload = {"inventories": inventories}
            try:
                r = requests.post(
                    url,
                    headers={**self.headers, "Content-Type": "application/json; charset=utf-8"},
                    data=json.dumps(payload),
                    timeout=30,
                )
                if r.status_code in (200, 204):
                    success += len(batch)
                else:
                    failed += len(batch)
                    errors.append({"batch_start": i, "error": f"HTTP {r.status_code}: {r.text[:200]}"})
            except Exception as e:
                failed += len(batch)
                errors.append({"batch_start": i, "error": str(e)})
        return {"success": success, "failed": failed, "errors": errors}

    def bulk_update_inventory(self, updates: List[Dict]) -> Dict:
        """複数SKUの在庫を順次PUSH

        Args:
            updates: [{"item_url": "xxx", "inventory": 10}, ...]

        Returns: {success: int, failed: int, errors: list}
        """
        success = 0
        failed = 0
        errors = []
        for u in updates:
            ok, msg = self.update_inventory(u["item_url"], u["inventory"])
            if ok:
                success += 1
            else:
                failed += 1
                errors.append({"item_url": u["item_url"], "error": msg})
        return {"success": success, "failed": failed, "errors": errors}


# ============================================================
# Amazon SP-API 在庫更新（Listings Items API patch）
# ============================================================
class AmazonSPClient:
    """Amazon SP-API クライアント"""

    SPAPI_HOST = "https://sellingpartnerapi-fe.amazon.com"  # Far East (JP)
    LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"

    def __init__(self):
        try:
            s = st.secrets["amazon"]
            self.lwa_client_id     = s["lwa_client_id"]
            self.lwa_client_secret = s["lwa_client_secret"]
            self.refresh_token     = s["refresh_token"]
            self.seller_id         = s["seller_id"]
            self.marketplace_id    = s["marketplace_id"]
        except (KeyError, FileNotFoundError):
            raise RuntimeError("Amazon SP-API認証情報が未設定です")
        if not self.refresh_token or not self.seller_id:
            raise RuntimeError("Amazon SP-API認証情報が空です")

        self._access_token = None
        self._product_type_cache = {}

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        r = requests.post(
            self.LWA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.lwa_client_id,
                "client_secret": self.lwa_client_secret,
            },
            timeout=15,
        )
        r.raise_for_status()
        self._access_token = r.json()["access_token"]
        return self._access_token

    def _headers(self) -> Dict[str, str]:
        return {
            "x-amz-access-token": self._get_access_token(),
            "Content-Type": "application/json",
        }

    def _get_product_type(self, sku: str) -> Optional[str]:
        """SKUから productType を取得（PATCH時に必要）"""
        if sku in self._product_type_cache:
            return self._product_type_cache[sku]
        url = f"{self.SPAPI_HOST}/listings/2021-08-01/items/{self.seller_id}/{sku}"
        params = {"marketplaceIds": self.marketplace_id, "includedData": "summaries"}
        try:
            r = requests.get(url, headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                summaries = r.json().get("summaries", [])
                if summaries:
                    pt = summaries[0].get("productType")
                    if pt:
                        self._product_type_cache[sku] = pt
                        return pt
            return None
        except Exception:
            return None

    def update_inventory(self, sku: str, quantity: int) -> Tuple[bool, str]:
        """1SKUの在庫数を更新（fulfillment_availability経由）"""
        product_type = self._get_product_type(sku)
        if not product_type:
            return False, f"productType取得失敗: {sku}"

        url = f"{self.SPAPI_HOST}/listings/2021-08-01/items/{self.seller_id}/{sku}"
        params = {"marketplaceIds": self.marketplace_id}
        payload = {
            "productType": product_type,
            "patches": [
                {
                    "op": "replace",
                    "path": "/attributes/fulfillment_availability",
                    "value": [
                        {
                            "fulfillment_channel_code": "DEFAULT",
                            "quantity": int(quantity),
                        }
                    ],
                }
            ],
        }
        try:
            r = requests.patch(url, headers=self._headers(), params=params,
                               data=json.dumps(payload), timeout=20)
            if r.status_code in (200, 204):
                return True, "OK"
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"例外: {e}"

    def bulk_update_inventory(self, updates: List[Dict]) -> Dict:
        """複数SKUの在庫PUSH

        Args:
            updates: [{"sku": "xxx", "quantity": 10}, ...]
        """
        success = 0
        failed = 0
        errors = []
        for u in updates:
            ok, msg = self.update_inventory(u["sku"], u["quantity"])
            if ok:
                success += 1
            else:
                failed += 1
                errors.append({"sku": u["sku"], "error": msg})
        return {"success": success, "failed": failed, "errors": errors}
