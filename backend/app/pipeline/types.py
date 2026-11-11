"""파이프라인 내부 데이터 구조 (DB 비의존)"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Flow:
    """분류된 입출금·결제 한 건 (수입 / 고정지출 / 변동지출 / 저축·투자 / 이체)"""
    occurred_on: date
    amount: float                 # 항상 양수
    direction: str                # in | out
    source: str                   # bank | card | efin | telecom | insurance | loan
    counterparty: str             # 가맹점명 또는 적요
    major: str                    # income | fixed | variable | saving | transfer | ignored
    category: str                 # 세분류(식비, 주거, 근로수입 등)
    stage: int = 1                # 분류가 확정된 단계 (0~4)
    rule: str = ""
    confidence: float = 1.0
    needs_review: bool = False
    recurring: bool = False


@dataclass
class Holding:
    """자산·부채 보유 항목"""
    side: str                     # asset | liability
    kind: str                     # cash | savings | invest | pension | other / secured | unsecured | other
    sub: str                      # 입출금, 정기예금, 주식/ETF, 전세자금대출 등
    name: str
    amount: float
    emergency_eligible: bool = False   # 비상금 계산용 현금성 인정 여부 (D-06)
    source: str = "mydata"             # mydata | manual


@dataclass
class OnboardingInfo:
    """프로필 산출에 필요한 온보딩 값"""
    birth_date: Optional[date] = None
    employment_status: str = "FULL_TIME"
    housing_type: Optional[str] = None
    housing_cost_monthly: Optional[float] = None
    risk_tolerance: str = "BALANCED"


@dataclass
class GoalInfo:
    name: str
    target_amount: float
    current_amount: float
    target_date: Optional[date]
    priority: int = 1


@dataclass
class ClassificationReport:
    """분류 실행 요약"""
    total: int = 0
    by_stage: dict = field(default_factory=dict)
    needs_review: int = 0
    llm_calls: int = 0
