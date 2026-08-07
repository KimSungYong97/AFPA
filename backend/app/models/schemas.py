"""API 요청/응답 스키마 (Pydantic)"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------- 5.1 금융 프로필 ----------
class ProfileInput(BaseModel):
    monthly_income: float = Field(ge=0, description="월 소득")
    monthly_fixed_expense: float = Field(ge=0, description="월 고정 지출")
    monthly_variable_expense: float = Field(ge=0, description="월 변동 지출")
    deposit: float = Field(ge=0, default=0, description="예금")
    savings: float = Field(ge=0, default=0, description="적금")
    investment: float = Field(ge=0, default=0, description="투자 자산")
    other_assets: float = Field(ge=0, default=0, description="기타 자산")
    total_debt: float = Field(ge=0, default=0, description="총 부채")


class ProfileSummary(BaseModel):
    total_assets: float
    total_debt: float
    net_worth: float
    monthly_surplus: float          # 월 여유 자금
    savings_rate: float             # 저축률 (%)
    debt_to_asset_ratio: float      # 자산 대비 부채 (%)
    cash_ratio: float               # 현금 보유율 (%)
    health_score: float             # 금융 건강도 점수 (0~100)
    health_grade: str               # 등급 (A~E)


# ---------- 5.2 목표 관리 ----------
class GoalCreate(BaseModel):
    name: str
    goal_type: str = "long_term"
    target_amount: float = Field(gt=0)
    current_amount: float = Field(ge=0, default=0)
    target_date: Optional[date] = None
    priority: int = 1


class GoalOut(GoalCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class GoalFeasibility(BaseModel):
    goal_id: int
    required_monthly_saving: float   # 목표 달성에 필요한 월 저축액
    expected_completion: Optional[date]  # 현재 저축 속도 기준 달성 예상 시기
    shortfall: float                 # 부족 자금
    achievable: bool


# ---------- 5.4 / 5.8 Action Plan ----------
class ActionItem(BaseModel):
    category: str        # saving | spending | card | loan | invest
    action: str          # 실행 내용
    expected_effect: str # 기대 효과


class ActionPlanOut(BaseModel):
    goal_id: Optional[int]
    actions: list[ActionItem]
    rationale: str               # 추천 근거
    expected_outcome: str        # 예상 결과
    created_at: datetime


# ---------- 5.5 / 5.6 모니터링 ----------
class MonitoringAlert(BaseModel):
    alert_type: str      # spending_change | rate_change | policy_change ...
    message: str
    severity: str        # info | warning | critical
    detected_at: datetime
