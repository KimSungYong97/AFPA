"""5.1 사용자 금융 프로필 서비스
- 자산 분석 / 소비 분석 / 금융 건강도 분석
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.entities import FinancialProfile, User
from app.models.schemas import ProfileInput, ProfileSummary


def upsert_profile(db: Session, user_id: int, data: ProfileInput) -> FinancialProfile:
    """프로필 생성/갱신"""
    profile = db.query(FinancialProfile).filter_by(user_id=user_id).first()
    if profile is None:
        profile = FinancialProfile(user_id=user_id)
        db.add(profile)

    for field, value in data.model_dump().items():
        setattr(profile, field, value)

    profile.health_score = _calc_health_score(data)
    db.commit()
    db.refresh(profile)
    return profile


def get_summary(db: Session, user_id: int) -> Optional[ProfileSummary]:
    """자산 요약 + 금융 건강도 요약"""
    p = db.query(FinancialProfile).filter_by(user_id=user_id).first()
    if p is None:
        return None

    total_assets = p.deposit + p.savings + p.investment + p.other_assets
    monthly_expense = p.monthly_fixed_expense + p.monthly_variable_expense
    monthly_surplus = p.monthly_income - monthly_expense

    savings_rate = (monthly_surplus / p.monthly_income * 100) if p.monthly_income > 0 else 0
    debt_ratio = (p.total_debt / total_assets * 100) if total_assets > 0 else 0
    cash_ratio = ((p.deposit + p.savings) / total_assets * 100) if total_assets > 0 else 0

    score = p.health_score or 0
    return ProfileSummary(
        total_assets=total_assets,
        total_debt=p.total_debt,
        net_worth=total_assets - p.total_debt,
        monthly_surplus=monthly_surplus,
        savings_rate=round(savings_rate, 1),
        debt_to_asset_ratio=round(debt_ratio, 1),
        cash_ratio=round(cash_ratio, 1),
        health_score=score,
        health_grade=_grade(score),
    )


def _calc_health_score(data: ProfileInput) -> float:
    """금융 건강도 점수 (0~100)
    - 저축률(40점) + 부채비율(30점) + 비상금(30점) 가중 합산 (MVP 단순 버전)
    """
    total_assets = data.deposit + data.savings + data.investment + data.other_assets
    monthly_expense = data.monthly_fixed_expense + data.monthly_variable_expense

    # 1) 저축률 점수 (저축률 30% 이상이면 만점)
    surplus = data.monthly_income - monthly_expense
    savings_rate = (surplus / data.monthly_income) if data.monthly_income > 0 else 0
    score_savings = min(savings_rate / 0.3, 1.0) * 40

    # 2) 부채비율 점수 (부채 0%면 만점, 100% 이상이면 0점)
    debt_ratio = (data.total_debt / total_assets) if total_assets > 0 else 1.0
    score_debt = max(1.0 - debt_ratio, 0.0) * 30

    # 3) 비상금 점수 (월 지출 6개월치 이상 보유 시 만점)
    emergency_months = ((data.deposit + data.savings) / monthly_expense) if monthly_expense > 0 else 0
    score_emergency = min(emergency_months / 6, 1.0) * 30

    return round(score_savings + score_debt + score_emergency, 1)


def _grade(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    return "E"


def get_or_create_user(db: Session, user_id: int, name: str = "사용자") -> User:
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id, name=name)
        db.add(user)
        db.commit()
    return user
