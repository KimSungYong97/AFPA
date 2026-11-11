"""LLM 클라이언트 공통 팩토리

vLLM 서버처럼 OpenAI 호환 엔드포인트(`LLM_BASE_URL`)를 쓰거나, 없으면 OpenAI API(`OPENAI_API_KEY`)를 쓴다.
둘 다 설정되지 않으면 LLM은 비활성이며, 호출하는 쪽은 규칙 기반 폴백으로 동작한다.
"""
from typing import Optional

from app.config import get_settings


def llm_enabled() -> bool:
    s = get_settings()
    return bool(s.llm_base_url or s.openai_api_key)


def get_llm_client(timeout: Optional[float] = None, max_retries: int = 2):
    """OpenAI 호환 클라이언트. 비활성이거나 openai 패키지가 없으면 None."""
    s = get_settings()
    if not llm_enabled():
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None
    return OpenAI(
        base_url=s.llm_base_url or None,
        api_key=s.openai_api_key or "EMPTY",      # vLLM은 키를 검사하지 않는다
        timeout=timeout or s.llm_timeout,
        max_retries=max_retries,
    )
