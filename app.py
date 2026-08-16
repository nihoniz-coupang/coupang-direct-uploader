from __future__ import annotations

import json
import os
from copy import deepcopy

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from coupang_api import CoupangAPIError, CoupangClient
from validators import validate_product_payload, get_mandatory_exposed_attribute_names


load_dotenv()

st.set_page_config(page_title="쿠팡 Direct Uploader", page_icon="📦", layout="wide")
st.title("📦 쿠팡 Direct Uploader v1")
st.caption("투플렉스 없이 쿠팡 Open API로 직접 상품을 등록하는 도구")

if "metadata" not in st.session_state:
    st.session_state.metadata = None
if "product_json" not in st.session_state:
    with open("sample_product.json", "r", encoding="utf-8") as f:
        st.session_state.product_json = f.read()


def api_error(exc: Exception):
    if isinstance(exc, CoupangAPIError):
        st.error(str(exc))
        if exc.payload is not None:
            st.json(exc.payload)
    else:
        st.exception(exc)


with st.sidebar:
    st.header("🔐 쿠팡 API 인증")
    access_key = st.text_input(
        "Access Key",
        value=os.getenv("COUPANG_ACCESS_KEY", ""),
        type="password",
    )
    secret_key = st.text_input(
        "Secret Key",
        value=os.getenv("COUPANG_SECRET_KEY", ""),
        type="password",
    )
    vendor_id = st.text_input(
        "Vendor ID",
        value=os.getenv("COUPANG_VENDOR_ID", ""),
        help="예: A00123456",
    )
    vendor_user_id = st.text_input(
        "WING 로그인 ID",
        value=os.getenv("COUPANG_VENDOR_USER_ID", ""),
    )
    st.info("키는 브라우저 세션에서만 사용합니다. 소스코드/로그에는 출력하지 않습니다.")

    def get_client():
        return CoupangClient(access_key, secret_key, vendor_id, vendor_user_id)


tab_conn, tab_meta, tab_product, tab_manage = st.tabs(
    ["1. 연결·물류", "2. 카테고리·브랜드", "3. 상품 등록", "4. 조회·승인"]
)


with tab_conn:
    st.subheader("API 연결 테스트")
    if st.button("연결 확인", type="primary"):
        try:
            data = get_client().get_inflow_status()
            st.success("쿠팡 API 인증 성공")
            st.json(data)
        except Exception as exc:
            api_error(exc)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("출고지 조회")
        st.caption("구매대행(AGENT_BUY)은 해외 출고지만 사용할 수 있습니다.")
        if st.button("출고지 불러오기"):
            try:
                data = get_client().list_outbound_shipping_places()
                st.json(data)
            except Exception as exc:
                api_error(exc)

    with c2:
        st.subheader("반품지 조회")
        st.caption("구매대행 상품도 국내 반품지 설정을 정확히 확인하세요.")
        if st.button("반품지 불러오기"):
            try:
                data = get_client().list_return_centers()
                st.json(data)
            except Exception as exc:
                api_error(exc)


with tab_meta:
    st.subheader("카테고리 추천")
    p1, p2 = st.columns(2)
    with p1:
        rec_name = st.text_input("상품명", placeholder="예: 조지루시 SU-AA36 360ml 보온보냉 텀블러")
        rec_brand = st.text_input("브랜드", placeholder="예: ZOJIRUSHI")
        rec_desc = st.text_area("간단 설명", height=100)
        if st.button("카테고리 추천받기"):
            try:
                data = get_client().recommend_category(
                    rec_name,
                    product_description=rec_desc,
                    brand=rec_brand,
                )
                st.json(data)
                predicted = (
                    data.get("data", {}).get("predictedCategoryId")
                    if isinstance(data, dict) else None
                )
                if predicted:
                    st.session_state["last_category_code"] = str(predicted)
            except Exception as exc:
                api_error(exc)

    with p2:
        st.subheader("브랜드 ID 검색")
        brand_query = st.text_input("브랜드 검색어", placeholder="예: ZOJIRUSHI")
        if st.button("브랜드 검색"):
            try:
                data = get_client().search_brand(brand_query)
                st.json(data)
            except Exception as exc:
                api_error(exc)

    st.divider()
    st.subheader("카테고리 메타정보")
    category_code = st.text_input(
        "displayCategoryCode",
        value=st.session_state.get("last_category_code", ""),
    )
    if st.button("메타정보 조회"):
        try:
            data = get_client().get_category_metadata(category_code)
            st.session_state.metadata = data
            st.success("메타정보를 저장했습니다. 상품 등록 탭의 검증에 사용됩니다.")
            mandatory = get_mandatory_exposed_attribute_names(data)
            if mandatory:
                st.write("**필수/그룹 구매옵션 후보:**", ", ".join(mandatory))
            st.json(data)
        except Exception as exc:
            api_error(exc)


with tab_product:
    st.subheader("상품 JSON")
    st.caption(
        "v1은 안정성을 위해 쿠팡 공식 Product Creation JSON을 그대로 검증·전송합니다. "
        "앞으로 라쿠텐 링크 분석 결과를 이 JSON으로 자동 생성하도록 확장할 수 있습니다."
    )

    uploaded = st.file_uploader("상품 JSON 불러오기", type=["json"])
    if uploaded is not None:
        try:
            st.session_state.product_json = uploaded.read().decode("utf-8")
        except Exception as exc:
            st.error(f"파일 읽기 실패: {exc}")

    editor = st.text_area(
        "등록 전문",
        value=st.session_state.product_json,
        height=620,
        key="product_editor",
    )

    b1, b2, b3 = st.columns([1, 1, 2])

    parsed = None
    with b1:
        if st.button("JSON 검증", type="primary"):
            try:
                parsed = json.loads(editor)
                # Always force the current credentials into the payload.
                if vendor_id:
                    parsed["vendorId"] = vendor_id
                if vendor_user_id:
                    parsed["vendorUserId"] = vendor_user_id

                errors, warnings = validate_product_payload(
                    parsed,
                    metadata=st.session_state.metadata,
                )
                if errors:
                    st.error("등록 전 수정이 필요한 항목이 있습니다.")
                    for msg in errors:
                        st.write("❌", msg)
                else:
                    st.success("로컬 필수 검증 통과")
                for msg in warnings:
                    st.write("⚠️", msg)

                st.session_state.product_json = json.dumps(
                    parsed, ensure_ascii=False, indent=2
                )
            except Exception as exc:
                api_error(exc)

    with b2:
        dry_request = st.checkbox(
            "자동 승인 요청",
            value=False,
            help="OFF 권장: 우선 임시저장 후 내용을 확인하고 별도 승인 요청하세요.",
        )

    st.warning(
        "실제 등록 버튼은 쿠팡에 쓰기 작업을 수행합니다. 처음에는 '자동 승인 요청'을 끄고 "
        "임시저장으로 테스트하는 것을 권장합니다."
    )

    confirm = st.checkbox("실제 쿠팡 계정에 상품을 생성하는 것에 동의합니다.")
    if st.button("🚀 쿠팡에 상품 생성", disabled=not confirm):
        try:
            parsed = json.loads(editor)
            parsed["vendorId"] = vendor_id
            if vendor_user_id:
                parsed["vendorUserId"] = vendor_user_id
            parsed["requested"] = bool(dry_request)

            errors, warnings = validate_product_payload(
                parsed,
                metadata=st.session_state.metadata,
            )
            if errors:
                st.error("로컬 검증 오류가 있어 API 호출을 중단했습니다.")
                for msg in errors:
                    st.write("❌", msg)
            else:
                for msg in warnings:
                    st.write("⚠️", msg)
                result = get_client().create_product(parsed)
                st.success("쿠팡 Product Creation API 호출 완료")
                st.json(result)
                if isinstance(result, dict) and result.get("data"):
                    st.session_state["last_seller_product_id"] = str(result["data"])
        except Exception as exc:
            api_error(exc)


with tab_manage:
    st.subheader("상품 조회 / 승인 요청")
    seller_product_id = st.text_input(
        "sellerProductId",
        value=st.session_state.get("last_seller_product_id", ""),
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("상품 조회"):
            try:
                data = get_client().get_product(seller_product_id)
                st.json(data)
            except Exception as exc:
                api_error(exc)

    with c2:
        approve_confirm = st.checkbox("해당 상품의 판매 승인 요청을 진행합니다.")
        if st.button("승인 요청", disabled=not approve_confirm):
            try:
                data = get_client().approve_product(seller_product_id)
                st.success("승인 요청 API 호출 완료")
                st.json(data)
            except Exception as exc:
                api_error(exc)

st.divider()
st.caption(
    "주의: 카테고리별 필수 구매옵션·고시·인증은 쿠팡 메타정보가 최종 기준입니다. "
    "본 도구의 로컬 검증은 쿠팡 서버 검증을 대체하지 않습니다."
)
