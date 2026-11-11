"""DB 엔티티 정의 (SQLAlchemy ORM)"""
from datetime import datetime, date
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    """사용자"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    job: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)           # 직업
    persona_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # 유형 (사회초년생/신혼부부 등)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    mydata_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    mydata_last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    profile: Mapped["FinancialProfile"] = relationship(back_populates="user", uselist=False)
    goals: Mapped[list["Goal"]] = relationship(back_populates="user")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")


class FinancialProfile(Base):
    """5.1 사용자 금융 프로필"""

    __tablename__ = "financial_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # 수입/지출
    monthly_income: Mapped[float] = mapped_column(Float, default=0)
    monthly_fixed_expense: Mapped[float] = mapped_column(Float, default=0)
    monthly_variable_expense: Mapped[float] = mapped_column(Float, default=0)

    # 자산
    deposit: Mapped[float] = mapped_column(Float, default=0)          # 예금
    savings: Mapped[float] = mapped_column(Float, default=0)          # 적금
    investment: Mapped[float] = mapped_column(Float, default=0)       # 투자 자산
    other_assets: Mapped[float] = mapped_column(Float, default=0)     # 기타 자산

    # 부채
    total_debt: Mapped[float] = mapped_column(Float, default=0)

    # 계산 결과 (금융 건강도)
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="profile")


class GoalType(str, Enum):
    LONG_TERM = "long_term"    # 장기 목표 (내 집 마련, 결혼, 은퇴)
    LIFE_EVENT = "life_event"  # Life Event (여행, 차량, 노트북)


class Goal(Base):
    """5.2 금융 목표"""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(100))
    goal_type: Mapped[str] = mapped_column(String(20), default=GoalType.LONG_TERM)
    target_amount: Mapped[float] = mapped_column(Float)          # 필요 자금
    current_amount: Mapped[float] = mapped_column(Float, default=0)
    target_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)    # 낮을수록 높은 우선순위
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="goals")


class Transaction(Base):
    """소비 내역 (5.1 소비 분석 / 5.5 소비 모니터링의 기반 데이터)"""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(50))    # 식비, 교통, 주거, 쇼핑 등
    is_fixed: Mapped[bool] = mapped_column(default=False)  # 고정 지출 여부
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    transacted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="transactions")


class ActionPlan(Base):
    """5.4/5.8 생성된 Action Plan 이력"""

    __tablename__ = "action_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    goal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("goals.id"), nullable=True)
    plan_json: Mapped[str] = mapped_column(Text)          # Action Plan 본문 (JSON)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 추천 근거
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ===========================================================================
# 1차 신규: 온보딩 / 동의 / 분류 / 스냅샷 (스키마 설계 문서의 6개 테이블 + 분류 결과 저장)
# ===========================================================================
class UserProfile(Base):
    """온보딩 입력값 (users와 1:1) — 마이데이터로 알 수 없는 정보만"""

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)           # MALE/FEMALE/OTHER
    employment_status: Mapped[str] = mapped_column(String(20), default="FULL_TIME")     # FULL_TIME/FREELANCER/SELF_EMPLOYED/UNEMPLOYED
    housing_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)      # OWNED/JEONSE/MONTHLY_RENT
    housing_cost_monthly: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location_region: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    location_district: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    risk_tolerance: Mapped[str] = mapped_column(String(20), default="BALANCED")         # 미입력 시 중립형 가정
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MydataConsent(Base):
    """마이데이터 항목별 동의 상태 (1차는 전체 동의 전제, D-09)"""

    __tablename__ = "mydata_consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    is_consent_merchant_name_regno: Mapped[bool] = mapped_column(Boolean, default=True)
    is_consent_trans_memo: Mapped[bool] = mapped_column(Boolean, default=True)
    is_consent_trans_category: Mapped[bool] = mapped_column(Boolean, default=True)
    consented_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class MerchantCategoryOverride(Base):
    """사용자 분류 수정 이력 — 이후 동일 상호는 분류 1단계에서 즉시 적용"""

    __tablename__ = "merchant_category_overrides"
    __table_args__ = (UniqueConstraint("user_id", "merchant_name_norm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    merchant_name_norm: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ManualAsset(Base):
    """마이데이터에 없는 수동 자산 (현금·금 현물 등, D-05)"""

    __tablename__ = "manual_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    asset_type: Mapped[str] = mapped_column(String(10))      # CASH / GOLD / OTHER
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MerchantCandidate(Base):
    """LLM(3단계)이 판별한 분류 후보 — 검수 후에만 사전에 편입한다(자동 승격 금지)"""

    __tablename__ = "merchant_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_name_norm: Mapped[str] = mapped_column(String(120), unique=True)
    category: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10), default="pending")   # pending/approved/rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClassifiedFlow(Base):
    """자동 분류 결과 (동기화 때마다 사용자별로 교체)"""

    __tablename__ = "classified_flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    occurred_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(3))        # in / out
    source: Mapped[str] = mapped_column(String(15))
    counterparty: Mapped[str] = mapped_column(String(200))
    merchant_norm: Mapped[str] = mapped_column(String(120), default="")
    major_class: Mapped[str] = mapped_column(String(10))     # income/fixed/variable/saving/transfer/ignored
    category: Mapped[str] = mapped_column(String(30))
    stage: Mapped[int] = mapped_column(Integer, default=1)   # 분류가 확정된 단계 0~4
    rule: Mapped[str] = mapped_column(String(20), default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)


class AccountHolding(Base):
    """자산·부채 보유 내역 (마이데이터 동기화 때마다 교체)"""

    __tablename__ = "account_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    side: Mapped[str] = mapped_column(String(10))            # asset / liability
    kind: Mapped[str] = mapped_column(String(15))
    sub: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Float)
    emergency_eligible: Mapped[bool] = mapped_column(Boolean, default=False)


class FinancialSnapshot(Base):
    """재무진단 결과 이력 — 동기화 때마다 누적 (추세·모니터링의 기반)"""

    __tablename__ = "financial_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    as_of: Mapped[date] = mapped_column(Date)                # 산출 기준일(데이터의 마지막 일자)

    monthly_income_net: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    savings_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dsr_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    emergency_fund_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    consumption_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    potential_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_cash_flow: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # 월 여유 자금 (D-02)
    net_worth: Mapped[float] = mapped_column(Float, default=0)
    debt_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")                    # 6개 엔진 상세


# ===========================================================================
# 2차 신규: 통합 플래너 (Action Plan · 이행 추적 · 소비 변화 모니터링 · 알림)
# ===========================================================================
class PlanVersion(Base):
    """계획 버전 — 재설계 시 변경 이력을 보존한다 (계획 재설계 설계의 plan_versions)

    status: active(적용 중) / pending(사용자 승인 대기) / superseded(대체됨) / rejected(거절됨)
    """

    __tablename__ = "plan_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="active")
    trigger: Mapped[str] = mapped_column(String(30), default="manual")      # manual / budget_change / delay / goal_change
    reason_key: Mapped[str] = mapped_column(String(60), default="")         # 거절 후 30일 재제안 금지 판단용
    as_of: Mapped[date] = mapped_column(Date)
    budget_at_plan: Mapped[float] = mapped_column(Float, default=0)         # 계획 수립 시 월 여유 자금
    baseline_json: Mapped[str] = mapped_column(Text, default="{}")          # 수립 시 목표별 예상 달성 시기
    comparison_json: Mapped[str] = mapped_column(Text, default="{}")        # 변경 전/후 비교 (재설계 제안)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


class ActionItem(Base):
    """Action Plan 항목 (action_type, description, path_effect, rationale, priority, status)

    status: PROPOSED → ACCEPTED → DONE / REJECTED / EXPIRED
    """

    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_version_id: Mapped[int] = mapped_column(ForeignKey("plan_versions.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(80))
    action_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    monthly_saving: Mapped[float] = mapped_column(Float, default=0)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    path_effect_json: Mapped[str] = mapped_column(Text, default="{}")      # 코드가 계산한 경로 효과
    rationale: Mapped[str] = mapped_column(Text, default="")              # 추천 이유 (근거 수치 + 설명)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="PROPOSED")
    tracked_by: Mapped[str] = mapped_column(String(5), default="user")    # auto / user
    proposed_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    accepted_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    accepted_as_of: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)   # 수락 시점의 데이터 기준월
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    reject_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MonitoringEvent(Base):
    """소비 변화 모니터링 이벤트 (동기화마다 갱신)"""

    __tablename__ = "monitoring_events"
    __table_args__ = (UniqueConstraint("user_id", "event_type", "category", "month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(25))
    category: Mapped[str] = mapped_column(String(60))
    month: Mapped[str] = mapped_column(String(7))
    judgement: Mapped[str] = mapped_column(String(12))        # structural / temporary
    grade: Mapped[str] = mapped_column(String(6))             # high / medium / low
    recent: Mapped[float] = mapped_column(Float, default=0)
    baseline: Mapped[float] = mapped_column(Float, default=0)
    monthly_impact: Mapped[float] = mapped_column(Float, default=0)
    goal_delay_months: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # 목표 달성 시기 영향
    message: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OneOffMark(Base):
    """사용자가 '일회성'으로 지정한 카테고리·월 — 평균 산출과 변화 판정에서 제외한다"""

    __tablename__ = "one_off_marks"
    __table_args__ = (UniqueConstraint("user_id", "category", "month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(60))
    month: Mapped[str] = mapped_column(String(7))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PlannerPreference(Base):
    """거절 학습으로 쌓인 사용자 선호 — 다음 제안에 반영한다 (사용자가 직접 지울 수 있다)

    kind=exclude   : target(후보 키)을 until(포함)까지 다시 제안하지 않는다. until이 없으면 계속
    kind=cut_scale : target(카테고리)의 절감 제안 규모를 value배로 줄인다
    """

    __tablename__ = "planner_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    target: Mapped[str] = mapped_column(String(80))
    value: Mapped[float] = mapped_column(Float, default=1.0)
    until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    reason_code: Mapped[str] = mapped_column(String(12), default="")
    reason_text: Mapped[str] = mapped_column(String(200), default="")
    created_on: Mapped[date] = mapped_column(Date)


class AgentRun(Base):
    """변화 감시 에이전트 실행 이력 — 무엇을 관찰·조사·판단하고 어떤 행동을 했는지 남긴다"""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    snapshot_id: Mapped[int] = mapped_column(Integer)                  # 이번 실행이 관찰한 스냅샷 (다음 실행의 비교 기준)
    status: Mapped[str] = mapped_column(String(12))                    # baseline / no_change / reported
    severity: Mapped[str] = mapped_column(String(10), default="none")  # none / info / important
    generated_by: Mapped[str] = mapped_column(String(5), default="rule")   # llm / rule
    llm_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    fallback_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plan_change_needed: Mapped[bool] = mapped_column(Boolean, default=False)   # 코드(경로 이탈 판정)의 결론
    replan_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")


class Notification(Base):
    """앱 내 알림 센터 (알림 설계: 등급·빈도 제한·중복 억제)"""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))             # spending_change / plan_deviation / replan_proposal
    grade: Mapped[str] = mapped_column(String(6))             # high / medium / low
    delivery: Mapped[str] = mapped_column(String(10))         # immediate / daily / weekly
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(120), index=True)
    related_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="unread")
    created_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
