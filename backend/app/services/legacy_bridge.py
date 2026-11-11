"""신규 파이프라인 결과 → 기존 테이블(FinancialProfile / Transaction) 호환 브리지

기존 Planning Agent·소비 모니터링은 FinancialProfile / Transaction을 읽는다.
2차에서 통합 플래너가 스냅샷을 직접 읽도록 바뀌면 이 브리지는 제거한다.
"""
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from app.models.entities import FinancialProfile, Transaction
from app.pipeline.engines import EngineResult
from app.pipeline.types import Flow, Holding


def sync_legacy_tables(db: Session, user_id: int, flows: List[Flow], holdings: List[Holding],
                       result: EngineResult) -> None:
    cf = result.details["cash_flow"]

    deposit = savings = investment = other = debt = 0.0
    for h in holdings:
        if h.side == "liability":
            debt += h.amount
        elif h.kind == "cash":
            deposit += h.amount
        elif h.kind == "savings":
            if h.sub in ("적금", "청약"):
                savings += h.amount
            else:
                deposit += h.amount
        elif h.kind == "invest":
            investment += h.amount
        else:
            other += h.amount

    profile = db.query(FinancialProfile).filter_by(user_id=user_id).first()
    if profile is None:
        profile = FinancialProfile(user_id=user_id)
        db.add(profile)
    profile.monthly_income = cf["monthly_income"] or 0
    profile.monthly_fixed_expense = cf["fixed_expense"] or 0
    profile.monthly_variable_expense = cf["variable_expense"] or 0
    profile.deposit, profile.savings = deposit, savings
    profile.investment, profile.other_assets, profile.total_debt = investment, other, debt
    profile.health_score = result.health_score

    db.query(Transaction).filter_by(user_id=user_id).delete()
    for f in flows:
        if f.direction != "out" or f.major not in ("fixed", "variable"):
            continue
        db.add(Transaction(
            user_id=user_id, amount=f.amount, category=f.category, is_fixed=(f.major == "fixed"),
            description=f.counterparty, transacted_at=datetime.combine(f.occurred_on, datetime.min.time()),
        ))
