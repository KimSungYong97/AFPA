"""3단계 LLM 분류기 (불명확 상호명 한정)

개인정보 정책: 가맹점명만 전달한다(금액·일시·계좌·사용자 식별 정보 전달 금지).
API 키가 없거나 호출이 실패하면 None → 파이프라인은 미분류(사용자 확인)로 폴백한다.
"""
from typing import Optional

from app.config import get_settings
from app.llm_client import get_llm_client
from app.pipeline.dictionary import ALL_CATEGORIES, UNCLASSIFIED

_SYSTEM = (
    "당신은 한국 카드 가맹점명을 소비 카테고리로 분류한다. "
    f"가능한 카테고리: {', '.join(ALL_CATEGORIES)}. "
    f"확신이 없으면 '{UNCLASSIFIED}'만 답한다. 카테고리 이름 하나만 출력한다."
)


def build_llm_categorizer():
    """LLM(vLLM 또는 OpenAI)이 설정된 경우에만 호출 함수를 반환한다."""
    settings = get_settings()
    client = get_llm_client(timeout=20, max_retries=0)   # 분류는 실패 시 사용자 확인으로 폴백하므로 재시도하지 않는다
    if client is None:
        return None

    def categorize(merchant_name: str) -> Optional[str]:
        resp = client.chat.completions.create(
            model=settings.llm_model,
            temperature=0,
            max_tokens=16,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": merchant_name},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text if text in ALL_CATEGORIES else None

    return categorize
