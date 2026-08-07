"""DB 엔티티 정의 (SQLAlchemy ORM)"""
from datetime import datetime, date
from enum import Enum
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
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
