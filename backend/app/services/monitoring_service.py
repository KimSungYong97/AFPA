"""5.5 소비 변화 모니터링 / 5.6 금융 정보 변화 모니터링"""
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.entities import Transaction
from app.models.schemas import MonitoringAlert

# 소비 증가 감지 임계값 (%)
SPENDING_INCREASE_THRESHOLD = 15.0


def detect_spending_changes(db: Session, user_id: int) -> list[MonitoringAlert]:
    """5.5 소비 패턴 변화 감지
    - 이번 달 소비(월 진행 일수로 환산한 페이스) vs 직전 3개월 평균 비교
    """
    alerts: list[MonitoringAlert] = []
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    three_months_ago = month_start - timedelta(days=90)

    current = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(
            Transaction.user_id == user_id,
            Transaction.is_fixed == False,  # noqa: E712 - 변동 지출만 비교
            Transaction.transacted_at >= month_start,
        )
        .scalar()
    )

    # 월 진행률 기준으로 월말 예상 소비액 환산 (월초 왜곡 방지)
    days_elapsed = max((now - month_start).days + 1, 1)
    projected = current / days_elapsed * 30

    past_total = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0.0))
        .filter(
            Transaction.user_id == user_id,
            Transaction.is_fixed == False,  # noqa: E712
            Transaction.transacted_at >= three_months_ago,
            Transaction.transacted_at < month_start,
        )
        .scalar()
    )
    past_avg = past_total / 3 if past_total else 0

    if past_avg > 0:
        change_pct = (projected - past_avg) / past_avg * 100
        if change_pct >= SPENDING_INCREASE_THRESHOLD:
            alerts.append(
                MonitoringAlert(
                    alert_type="spending_change",
                    message=f"이번 달 소비가 평균보다 {change_pct:.0f}% 증가할 것으로 예상됩니다.",
                    severity="warning",
                    detected_at=now,
                )
            )

    return alerts


async def detect_market_changes(db: Session, user_id: int) -> list[MonitoringAlert]:
    """5.6 금융 환경 변화 감지 (MVP 스텁)

    TODO:
    - 기준금리 변경 감지 (이전 조회값 저장 후 비교)
    - 신규 고금리 상품 출시 감지
    - 정책/규제 변경 감지
    """
    return []
