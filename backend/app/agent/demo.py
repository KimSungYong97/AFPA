"""데모용 '가상 변화 주입' — 에이전트가 반응할 변화를 만들기 위해 분류된 거래를 직접 바꾼다

실제 서비스에서는 마이데이터 재동기화로 새 거래가 들어오는 것이 이 역할이다. 여기서는 가상 사용자 데이터에
변화를 흉내 내 보기 위해서만 쓴다. 다시 '연동'(동기화)하면 원래 데이터로 돌아간다.
"""
from datetime import date
from typing import List

from sqlalchemy.orm import Session

from app.agent import change_agent
from app.models.entities import ClassifiedFlow
from app.services import pipeline_service, planner_service as ps

KINDS = {
    "income_drop": "월 소득이 크게 줄어든 상황 (최근 3개월 수입이 40% 감소)",
    "new_fixed": "새 정기 지출이 생긴 상황 (매달 35만 원, 최근 4개월)",
    "spending_surge": "쇼핑 지출이 갑자기 늘어난 상황 (최근 2개월 매달 45만 원 추가)",
}


def _recent_months(as_of: date, n: int) -> List[tuple]:
    out, y, m = [], as_of.year, as_of.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def simulate_change(db: Session, user_id: int, kind: str) -> dict:
    if kind not in KINDS:
        raise ValueError(f"알 수 없는 변화 종류: {kind}")
    snap = pipeline_service.latest_snapshot(db, user_id)
    if snap is None:
        raise LookupError("프로필이 없습니다. 먼저 마이데이터를 동기화하세요.")
    if ps.active_plan(db, user_id) is None:          # 변화 전의 '계획'이 있어야 계획 이탈을 판정할 수 있다
        ps.generate_plan(db, user_id)
    change_agent.ensure_baseline(db, user_id)         # 변화 전 상태를 에이전트의 기준으로 기억

    as_of = snap.as_of
    if kind == "income_drop":
        months = set(_recent_months(as_of, 3))
        for f in db.query(ClassifiedFlow).filter_by(user_id=user_id, major_class="income"):
            if (f.occurred_on.year, f.occurred_on.month) in months:
                f.amount = round(f.amount * 0.6)
    elif kind == "new_fixed":
        for y, m in _recent_months(as_of, 4):
            db.add(ClassifiedFlow(user_id=user_id, occurred_on=date(y, m, 15), amount=350_000, direction="out",
                                  source="bank", counterparty="신규 정기 납입", merchant_norm="", major_class="fixed",
                                  category="기타", stage=1, rule="demo", is_recurring=True))
    else:
        for y, m in _recent_months(as_of, 2):
            for day in (5, 12, 19):
                db.add(ClassifiedFlow(user_id=user_id, occurred_on=date(y, m, day), amount=150_000, direction="out",
                                      source="card", counterparty="온라인 쇼핑몰", merchant_norm="", major_class="variable",
                                      category="쇼핑", stage=1, rule="demo"))
    db.commit()
    new = pipeline_service.compute_and_store_snapshot(db, user_id)
    return {"kind": kind, "description": KINDS[kind], "snapshot_id": new.id}
