from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests


API_HOST = "https://api-gateway.coupang.com"


class CoupangAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class CoupangClient:
    """
    Coupang Open API client.

    HMAC rule:
      message = signed_date + HTTP_METHOD + path + query_string
      signature = HMAC-SHA256(secret_key, message)
    The request body is not part of the signature.
    """

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        vendor_id: str,
        vendor_user_id: str = "",
        timeout: int = 45,
    ):
        self.access_key = access_key.strip()
        self.secret_key = secret_key.strip()
        self.vendor_id = vendor_id.strip()
        self.vendor_user_id = vendor_user_id.strip()
        self.timeout = timeout

        missing = [
            name for name, value in {
                "access_key": self.access_key,
                "secret_key": self.secret_key,
                "vendor_id": self.vendor_id,
            }.items() if not value
        ]
        if missing:
            raise ValueError(f"Missing required credentials: {', '.join(missing)}")

    @staticmethod
    def _signed_date() -> str:
        # Coupang examples use UTC/GMT in yyMMdd'T'HHmmss'Z'
        return datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")

    def _authorization(self, method: str, path: str, query: str = "") -> str:
        signed_date = self._signed_date()
        message = f"{signed_date}{method.upper()}{path}{query}"
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return (
            "CEA algorithm=HmacSHA256, "
            f"access-key={self.access_key}, "
            f"signed-date={signed_date}, "
            f"signature={signature}"
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        method = method.upper()
        params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        query = urlencode(params, doseq=True)
        url = f"{API_HOST}{path}" + (f"?{query}" if query else "")

        headers = {
            "Authorization": self._authorization(method, path, query),
            "Content-Type": "application/json;charset=UTF-8",
            "X-Requested-By": self.vendor_id,
            "X-MARKET": "KR",
        }

        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CoupangAPIError(f"Network error: {exc}") from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text}

        if not response.ok:
            raise CoupangAPIError(
                f"Coupang API HTTP {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )
        return payload

    # ---------- Account / logistics ----------

    def get_inflow_status(self) -> Dict[str, Any]:
        return self.request(
            "GET",
            "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/inflow-status",
        )

    def list_outbound_shipping_places(self, page_num: int = 1, page_size: int = 50) -> Dict[str, Any]:
        return self.request(
            "GET",
            "/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound",
            params={"pageNum": page_num, "pageSize": page_size},
        )

    def list_return_centers(self, page_num: int = 1, page_size: int = 50) -> Dict[str, Any]:
        return self.request(
            "GET",
            f"/v2/providers/openapi/apis/api/v5/vendors/{self.vendor_id}/returnShippingCenters",
            params={"pageNum": page_num, "pageSize": page_size},
        )

    # ---------- Category / brand ----------

    def recommend_category(
        self,
        product_name: str,
        *,
        product_description: str = "",
        brand: str = "",
        attributes: Optional[list] = None,
        seller_sku_code: str = "",
    ) -> Dict[str, Any]:
        body = {
            "productName": product_name,
            "productDescription": product_description,
            "brand": brand,
            "attributes": attributes or [],
            "sellerSkuCode": seller_sku_code,
        }
        return self.request(
            "POST",
            "/v2/providers/openapi/apis/api/v1/categorization/predict",
            json_body=body,
        )

    def get_category_metadata(self, display_category_code: int | str) -> Dict[str, Any]:
        return self.request(
            "GET",
            (
                "/v2/providers/seller_api/apis/api/v1/marketplace/meta/"
                f"category-related-metas/display-category-codes/{display_category_code}"
            ),
        )

    def search_brand(self, brand_name: str, page: int = 1, count_per_page: int = 10) -> Dict[str, Any]:
        return self.request(
            "POST",
            "/v2/providers/seller_api/apis/api/v1/marketplace/brands/search",
            json_body={
                "brandName": brand_name,
                "countPerPage": min(max(count_per_page, 1), 10),
                "page": max(page, 1),
            },
        )

    # ---------- Product ----------

    def create_product(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(
            "POST",
            "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
            json_body=payload,
        )

    def approve_product(self, seller_product_id: int | str) -> Dict[str, Any]:
        return self.request(
            "PUT",
            (
                "/v2/providers/seller_api/apis/api/v1/marketplace/"
                f"seller-products/{seller_product_id}/approvals"
            ),
        )

    def get_product(self, seller_product_id: int | str) -> Dict[str, Any]:
        return self.request(
            "GET",
            (
                "/v2/providers/seller_api/apis/api/v1/marketplace/"
                f"seller-products/{seller_product_id}"
            ),
        )
