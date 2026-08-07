"""5.3 금융 정보 수집 서비스
- 금융상품 / 정책 / 시장 정보 수집 (MVP: 스텁 + 금감원 API 연동 지점)

TODO:
- 금융감독원 금융상품통합비교공시 API 연동 (예금/적금 상품)
- 한국은행 ECOS API 연동 (기준금리)
- 정책 정보 크롤링 or 공공데이터 API
"""
import httpx

from app.config import get_settings

settings = get_settings()

# 금감원 금융상품 API (예시)
FSS_BASE_URL = "http://finlife.fss.or.kr/finlifeapi"


async def fetch_deposit_products(top_fin_grp_no: str = "020000") -> list[dict]:
    """예금 상품 목록 조회 (금감원 API)
    top_fin_grp_no: 020000=은행, 030300=저축은행
    """
    if not settings.fss_api_key:
        # API 키 미설정 시 더미 데이터 반환 (개발용)
        return _dummy_deposit_products()

    url = f"{FSS_BASE_URL}/depositProductsSearch.json"
    params = {"auth": settings.fss_api_key, "topFinGrpNo": top_fin_grp_no, "pageNo": 1}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    return data.get("result", {}).get("baseList", [])


async def fetch_savings_products(top_fin_grp_no: str = "020000") -> list[dict]:
    """적금 상품 목록 조회 (금감원 API)"""
    if not settings.fss_api_key:
        return _dummy_savings_products()

    url = f"{FSS_BASE_URL}/savingProductsSearch.json"
    params = {"auth": settings.fss_api_key, "topFinGrpNo": top_fin_grp_no, "pageNo": 1}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    return data.get("result", {}).get("baseList", [])


async def get_base_rate() -> float:
    """기준금리 조회 (TODO: 한국은행 ECOS API 연동)"""
    return 2.50  # 더미 값


def _dummy_deposit_products() -> list[dict]:
    return [
        {"kor_co_nm": "A은행", "fin_prdt_nm": "A정기예금", "intr_rate": 3.2, "intr_rate2": 3.5},
        {"kor_co_nm": "B은행", "fin_prdt_nm": "B정기예금", "intr_rate": 3.0, "intr_rate2": 3.4},
    ]


def _dummy_savings_products() -> list[dict]:
    return [
        {"kor_co_nm": "A은행", "fin_prdt_nm": "A청년적금", "intr_rate": 4.0, "intr_rate2": 5.0},
        {"kor_co_nm": "C은행", "fin_prdt_nm": "C자유적금", "intr_rate": 3.5, "intr_rate2": 4.2},
    ]
