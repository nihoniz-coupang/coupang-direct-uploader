from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse


GTIN_RE = re.compile(r"^\d{8,14}$")


def _items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = payload.get("items", [])
    return items if isinstance(items, list) else []


def _attrs(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    attrs = item.get("attributes", [])
    return attrs if isinstance(attrs, list) else []


def _attr_map(item: Dict[str, Any]) -> Dict[str, str]:
    out = {}
    for attr in _attrs(item):
        name = str(attr.get("attributeTypeName", "")).strip()
        value = str(attr.get("attributeValueName", "")).strip()
        if name:
            out[name] = value
    return out


def get_mandatory_exposed_attribute_names(metadata: Dict[str, Any]) -> List[str]:
    """
    Coupang metadata shape can change/contain wrappers.
    Traverse the response and collect:
      required == MANDATORY
      exposed == EXPOSED
    Attribute groups are returned as multiple records; the uploader flags them for review
    rather than deciding group OR/AND logic on behalf of the seller.
    """
    names = []

    def walk(node: Any):
        if isinstance(node, dict):
            if (
                str(node.get("required", "")).upper() == "MANDATORY"
                and str(node.get("exposed", "")).upper() == "EXPOSED"
                and node.get("attributeTypeName")
            ):
                names.append(str(node["attributeTypeName"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(metadata)
    # preserve order
    seen = set()
    result = []
    for name in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def validate_product_payload(
    payload: Dict[str, Any],
    metadata: Dict[str, Any] | None = None,
) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    required_top = [
        "sellerProductName",
        "vendorId",
        "saleStartedAt",
        "saleEndedAt",
        "deliveryMethod",
        "deliveryCompanyCode",
        "deliveryChargeType",
        "returnCenterCode",
        "returnChargeName",
        "companyContactNumber",
        "returnZipCode",
        "returnAddress",
        "returnAddressDetail",
        "returnCharge",
        "outboundShippingPlaceCode",
        "vendorUserId",
        "items",
    ]
    for key in required_top:
        if key not in payload or payload.get(key) in ("", None, []):
            errors.append(f"필수 상위 필드 누락: {key}")

    if not payload.get("brand") and not payload.get("brandId"):
        errors.append("브랜드 정보가 없습니다. brand 또는 brandId가 필요합니다.")

    items = _items(payload)
    if not items:
        errors.append("items가 비어 있습니다.")
        return errors, warnings

    external_skus = []
    for idx, item in enumerate(items, start=1):
        prefix = f"옵션 {idx}({item.get('itemName', '이름없음')})"
        for key in ["itemName", "salePrice", "outboundShippingTimeDay", "unitCount"]:
            if item.get(key) in ("", None):
                errors.append(f"{prefix}: {key} 누락")

        attrs = _attr_map(item)
        gtin = attrs.get("Global Trade Item Number", "")
        mpn = attrs.get("Manufacturer Part Number", "")
        if not gtin and not mpn:
            errors.append(
                f"{prefix}: Global Trade Item Number 또는 Manufacturer Part Number 중 하나가 필요합니다."
            )
        if gtin and not GTIN_RE.match(gtin):
            warnings.append(f"{prefix}: GTIN '{gtin}' 형식을 다시 확인하세요(8~14자리 숫자 권장).")

        if payload.get("deliveryMethod") == "AGENT_BUY" and item.get("pccNeeded") is not True:
            errors.append(f"{prefix}: 구매대행(AGENT_BUY)은 pccNeeded=true가 필요합니다.")

        sku = str(item.get("externalVendorSku", "")).strip()
        if sku:
            external_skus.append(sku)

        images = item.get("images") or []
        rep = 0
        for image in images:
            if image.get("imageType") == "REPRESENTATION":
                rep += 1
            path = image.get("vendorPath") or image.get("cdnPath") or ""
            if path:
                parsed = urlparse(path)
                if parsed.scheme not in ("http", "https"):
                    errors.append(f"{prefix}: 이미지 URL은 http/https여야 합니다: {path}")
        if rep != 1:
            errors.append(f"{prefix}: REPRESENTATION 대표이미지는 정확히 1개가 필요합니다.")

        if not item.get("contents"):
            warnings.append(f"{prefix}: 상세설명(contents)이 비어 있습니다.")

    if len(external_skus) != len(set(external_skus)):
        warnings.append("externalVendorSku가 옵션 간 중복됩니다. 고유값 사용을 권장합니다.")

    if metadata:
        mandatory = get_mandatory_exposed_attribute_names(metadata)
        if mandatory:
            for idx, item in enumerate(items, start=1):
                attrs = _attr_map(item)
                # Group attributes can be OR conditions, so we only flag them.
                missing = [name for name in mandatory if not attrs.get(name)]
                if missing:
                    warnings.append(
                        f"옵션 {idx}: 카테고리 메타 기준 필수/그룹 구매옵션 확인 필요: "
                        + ", ".join(missing)
                    )

    if payload.get("deliveryMethod") == "AGENT_BUY":
        warnings.append(
            "구매대행(AGENT_BUY)은 쿠팡에 등록된 '해외 출고지'를 사용해야 합니다. "
            "프로그램은 주소의 국내/해외 여부를 로컬에서 확정할 수 없으므로 API/WING에서 확인하세요."
        )

    return errors, warnings
