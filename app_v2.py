from __future__ import annotations

import hmac
import json
import streamlit as st

from coupang_api import CoupangAPIError, CoupangClient
from validators import validate_product_payload, get_mandatory_exposed_attribute_names


st.set_page_config(
    page_title="쿠팡 Direct Uploader",
    page_icon="📦",
    layout="wide",
)


def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
        return str(value) if value is not None else default
    except Exception:
        return default


def require_login() -> None:
    expected = get_secret("APP_PASSWORD")

    if not expected:
        st.error("APP_PASSWORD가 설정되지 않았습니다.")
        st.info(
            "Streamlit 앱 Settings → Secrets에 APP_PASSWORD를 먼저 등록해 주세요. "
            "비밀번호를 GitHub 코드에 직접 적으면 안 됩니다."
        )
        st.stop()

    if st.session_state.get("authenticated") is True:
        return

    st.title("🔐 쿠팡 Direct Uploader")
    st.caption("관리자 로그인")

    password = st.text_input(
        "비밀번호",
        type="password",
        placeholder="관리자 비밀번호 입력",
    )

    if st.button("로그인", type="primary", use_container_width=True):
        if hmac.compare_digest(password, expected):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")

    st.stop()


require_login()

ACCESS_KEY = get_secret("COUPANG_ACCESS_KEY")
SECRET_KEY = get_secret("COUPANG_SECRET_KEY")
VENDOR_ID = get_secret("COUPANG_VENDOR_ID")
VENDOR_USER_ID = get_secret("COUPANG_VENDOR_USER_ID")


def get_client() -> CoupangClient:
    missing = [
        name
        for name, value in {
            "COUPANG_ACCESS_KEY": ACCESS_KEY,
            "COUPANG_SECRET_KEY": SECRET_KEY,
            "COUPANG_VENDOR_ID": VENDOR_ID,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Streamlit Secrets에 다음 값이 필요합니다: " + ", ".join(missing)
        )

    return CoupangClient(
        ACCESS_KEY,
        SECRET_KEY,
        VENDOR_ID,
        VENDOR_USER_ID,
    )


def api_error(exc: Exception) -> None:
    if isinstance(exc, CoupangAPIError):
        st.error(str(exc))
        if exc.payload is not None:
            st.json(exc.payload)
    else:
        st.error(str(exc))


if "metadata" not in st.session_state:
    st.session_state["metadata"] = None

if "product_json" not in st.session_state:
    try:
        with open("sample_product.json", "r", encoding="utf-8") as f:
            st.session_state["product_json"] = f.read()
    except FileNotFoundError:
        st.session_state["product_json"] = "{}"


header_left, header_right = st.columns([5, 1])

with header_left:
    st.title("📦 쿠팡 Direct Uploader v2")
    st.caption("투플렉스 없이 쿠팡 Open API로 직접 상품 등록")

with header_right:
    if st.button("로그아웃", use_container_width=True):
        st.session_state.clear()
        st.rerun()


with st.expander("🔐 서버 설정 상태", expanded=False):
    checks = {
        "관리자 비밀번호": bool(get_secret("APP_PASSWORD")),
        "Coupang Access Key": bool(ACCESS_KEY),
        "Coupang Secret Key": bool(SECRET_KEY),
        "Coupang Vendor ID": bool(VENDOR_ID),
        "WING 로그인 ID": bool(VENDOR_USER_ID),
    }
    for label, ok in checks.items():
        st.write(("✅ " if ok else "❌ ") + label)

    if not all(checks.values()):
        st.warning(
            "미설정 항목은 Streamlit Community Cloud의 앱 Settings → Secrets에서 등록하세요."
        )


tab_conn, tab_meta, tab_product, tab_manage = st.tabs(
    ["1. 연결·물류", "2. 카테고리·브랜드", "3. 상품 등록", "4. 조회·승인"]
)


with tab_conn:
    st.subheader("쿠팡 API 연결")

    if st.button("API 연결 확인", type="primary"):
        try:
            data = get_client().get_inflow_status()
            st.success("쿠팡 Open API 인증 성공")
            st.json(data)
        except Exception as exc:
            api_error(exc)

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("출고지 조회")
        st.caption("구매대행 AGENT_BUY 사용 시 실제 해외 출고지 여부를 반드시 확인하세요.")
        if st.button("출고지 불러오기"):
            try:
                st.json(get_client().list_outbound_shipping_places())
            except Exception as exc:
                api_error(exc)

    with c2:
        st.subheader("반품지 조회")
        if st.button("반품지 불러오기"):
            try:
                st.json(get_client().list_return_centers())
            except Exception as exc:
                api_error(exc)


with tab_meta:
    st.subheader("카테고리 추천")

    c1, c2 = st.columns(2)

    with c1:
        rec_name = st.text_input(
            "상품명",
            placeholder="예: 조지루시 SU-AA36 360ml 보온보냉 텀블러",
        )
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

                predicted = None
                if isinstance(data, dict):
                    predicted = (
                        data.get("data", {}).get("predictedCategoryId")
                        if isinstance(data.get("data"), dict)
                        else None
                    )
                if predicted:
                    st.session_state["last_category_code"] = str(predicted)
            except Exception as exc:
                api_error(exc)

    with c2:
        st.subheader("브랜드 ID 검색")
        brand_query = st.text_input(
            "브랜드 검색어",
            placeholder="예: ZOJIRUSHI",
        )
        if st.button("브랜드 검색"):
            try:
                st.json(get_client().search_brand(brand_query))
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
            st.session_state["metadata"] = data
            st.success("카테고리 메타정보 저장 완료")

            mandatory = get_mandatory_exposed_attribute_names(data)
            if mandatory:
                st.write("필수/그룹 구매옵션 후보:", ", ".join(mandatory))

            st.json(data)
        except Exception as exc:
            api_error(exc)


with tab_product:
    st.subheader("상품 등록 전문")
    st.caption(
        "현재 v2는 API 연결 안정성 검증 단계입니다. "
        "다음 단계에서 라쿠텐 URL → 자동완성 폼으로 교체합니다."
    )

    uploaded = st.file_uploader("상품 JSON 불러오기", type=["json"])
    if uploaded is not None:
        try:
            st.session_state["product_json"] = uploaded.read().decode("utf-8")
        except Exception as exc:
            st.error(f"파일 읽기 실패: {exc}")

    editor = st.text_area(
        "JSON",
        value=st.session_state["product_json"],
        height=560,
        key="product_editor",
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("JSON 검증", type="primary", use_container_width=True):
            try:
                parsed = json.loads(editor)

                if VENDOR_ID:
                    parsed["vendorId"] = VENDOR_ID
                if VENDOR_USER_ID:
                    parsed["vendorUserId"] = VENDOR_USER_ID

                errors, warnings = validate_product_payload(
                    parsed,
                    metadata=st.session_state.get("metadata"),
                )

                if errors:
                    st.error("수정이 필요한 항목이 있습니다.")
                    for msg in errors:
                        st.write("❌", msg)
                else:
                    st.success("로컬 필수 검증 통과")

                for msg in warnings:
                    st.write("⚠️", msg)

                st.session_state["product_json"] = json.dumps(
                    parsed,
                    ensure_ascii=False,
                    indent=2,
                )

            except Exception as exc:
                api_error(exc)

    with col2:
        auto_approve = st.checkbox(
            "생성 직후 승인 요청",
            value=False,
            help="초기 테스트에서는 OFF를 권장합니다.",
        )

    st.warning(
        "아래 버튼은 실제 쿠팡 계정에 쓰기 작업을 수행합니다. "
        "첫 테스트에서는 승인 요청을 끄고 임시 등록 후 조회하는 것을 권장합니다."
    )

    confirm = st.checkbox(
        "실제 쿠팡 계정에 상품을 생성하는 것을 확인했습니다."
    )

    if st.button(
        "🚀 쿠팡에 상품 생성",
        disabled=not confirm,
        type="primary",
        use_container_width=True,
    ):
        try:
            parsed = json.loads(editor)

            parsed["vendorId"] = VENDOR_ID
            if VENDOR_USER_ID:
                parsed["vendorUserId"] = VENDOR_USER_ID

            parsed["requested"] = bool(auto_approve)

            errors, warnings = validate_product_payload(
                parsed,
                metadata=st.session_state.get("metadata"),
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
        if st.button("상품 조회", use_container_width=True):
            try:
                st.json(get_client().get_product(seller_product_id))
            except Exception as exc:
                api_error(exc)

    with c2:
        approve_confirm = st.checkbox("해당 상품의 판매 승인 요청을 진행합니다.")

        if st.button(
            "승인 요청",
            disabled=not approve_confirm,
            use_container_width=True,
        ):
            try:
                data = get_client().approve_product(seller_product_id)
                st.success("승인 요청 API 호출 완료")
                st.json(data)
            except Exception as exc:
                api_error(exc)


st.divider()
st.caption(
    "API 키와 관리자 비밀번호는 GitHub에 저장하지 않습니다. "
    "Streamlit Community Cloud Secrets에서만 관리합니다."
)
