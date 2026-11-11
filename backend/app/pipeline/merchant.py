"""가맹점 분류 파이프라인 (변동/고정지출 카테고리 매핑)

단계 (「데이터 자동 분류 로직」):
  0  가맹점명 유무 분기      — 없으면 1~3단계를 건너뛰고 미분류(사용자 확인)
  1  코드·정확매칭          — 사용자 수정 내역(override) 우선, 그다음 정확 매칭 사전
  2  가맹점명 키워드·패턴 규칙
  3  LLM 추론               — 캐시 우선, 불명확 상호에 한정. 결과는 후보로 저장(자동 승격 금지)
  4  사용자 직접 수정        — 어느 단계에서도 확정되지 않으면 미분류로 두고 확인 유도
"""
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from app.pipeline.dictionary import (
    ALL_CATEGORIES, EXACT_MERCHANTS, KEYWORD_RULES, UNCLASSIFIED,
)
from app.pipeline.text import normalize_merchant

LlmCategorizer = Callable[[str], Optional[str]]


@dataclass
class MerchantResult:
    category: str
    stage: int            # 0~4
    rule: str             # no_name | user_override | exact | keyword | llm_cache | llm | unresolved
    confidence: float
    needs_review: bool


class MerchantClassifier:
    def __init__(
        self,
        overrides: Optional[Dict[str, str]] = None,
        llm: Optional[LlmCategorizer] = None,
        llm_cache: Optional[Dict[str, str]] = None,
    ):
        self.overrides = overrides or {}
        self.llm = llm
        self.llm_cache = llm_cache if llm_cache is not None else {}
        self.new_candidates: Dict[str, str] = {}   # 이번 실행에서 LLM이 새로 판별한 후보
        self.llm_calls = 0

    def classify(self, merchant_name: Optional[str]) -> MerchantResult:
        # 0단계: 가맹점명 유무
        if not merchant_name or not merchant_name.strip():
            return MerchantResult(UNCLASSIFIED, 0, "no_name", 0.0, True)

        norm = normalize_merchant(merchant_name)

        # 1단계: 사용자 수정 → 정확 매칭
        if norm in self.overrides:
            return MerchantResult(self.overrides[norm], 1, "user_override", 1.0, False)
        if norm in EXACT_MERCHANTS:
            return MerchantResult(EXACT_MERCHANTS[norm], 1, "exact", 0.98, False)

        # 2단계: 브랜드 토큰(첫 단어가 사전 상호와 일치, 예: "CGV 강남") → 키워드 규칙 (긴 키워드 우선)
        first = norm.split(" ")[0]
        if first in EXACT_MERCHANTS:
            return MerchantResult(EXACT_MERCHANTS[first], 2, "brand_token", 0.9, False)
        text = merchant_name.casefold()
        for kw, cat in KEYWORD_RULES:
            if kw in text:
                return MerchantResult(cat, 2, "keyword", 0.85, False)

        # 3단계: LLM (캐시 → 호출)
        if norm in self.llm_cache:
            return MerchantResult(self.llm_cache[norm], 3, "llm_cache", 0.6, True)
        if self.llm is not None:
            self.llm_calls += 1
            try:
                cat = self.llm(merchant_name)
            except Exception:
                cat = None
            if cat in ALL_CATEGORIES:
                self.llm_cache[norm] = cat
                self.new_candidates[norm] = cat
                return MerchantResult(cat, 3, "llm", 0.6, True)

        # 4단계: 사용자 확인 유도
        return MerchantResult(UNCLASSIFIED, 4, "unresolved", 0.0, True)
