"""통합 플래너 API (2차) — 경로 · 시나리오 · 행동 후보 순위 · Action Plan · 이행 추적 · 재설계 · 알림 · 브리핑"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.planner.scenarios import ScenarioError
from app.services import briefing_service, planner_service as ps

router = APIRouter()


class ScenarioIn(BaseModel):
    kind: str = Field(description="save_delta | expense | income | goal | return")
    label: str = ""
    delta: float = 0
    month: int = 1
    amount: float = 0
    goal: Optional[str] = None
    shift_months: int = 0
    case: str = "base"


class ScenariosIn(BaseModel):
    scenarios: List[ScenarioIn]


class CombineIn(BaseModel):
    selected: List[str]


class RespondIn(BaseModel):
    action: str = Field(pattern="^(accept|reject|done)$")
    reason: Optional[str] = None
    reason_code: Optional[str] = Field(default=None, pattern="^(already|needed|burden|later|other)$")


class DecideIn(BaseModel):
    approve: bool
    note: Optional[str] = None


class OneOffIn(BaseModel):
    category: str
    month: str = Field(pattern=r"^\d{4}-\d{2}$")


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, ScenarioError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{user_id}/briefing")
def briefing(user_id: int, use_llm: bool = False, db: Session = Depends(get_db)):
    """관리자 agent 브리핑: 효과 큰 행동 순위, 목표 경로, 소비 변화, 이행 현황, 승인 대기 재설계"""
    return _wrap(briefing_service.compose, db, user_id, use_llm)


@router.get("/{user_id}/path")
def path(user_id: int, db: Session = Depends(get_db)):
    """자산 성장 경로: 기준 경로(현재 패턴 유지)와 개선 경로(Action Plan 실행 시)"""
    return _wrap(ps.path_view, db, user_id)


@router.post("/{user_id}/scenarios")
def scenarios(user_id: int, body: ScenariosIn, db: Session = Depends(get_db)):
    """What-if 시나리오(최대 3개)를 기준 경로 대비 차이로 비교"""
    return _wrap(ps.scenarios_view, db, user_id, [s.model_dump() for s in body.scenarios])


@router.get("/{user_id}/candidates")
def candidates(user_id: int, db: Session = Depends(get_db)):
    """행동 후보를 목표 달성 단축 기간 순으로 정렬 (단독 효과, 합산 금지, 충돌 표시)"""
    return _wrap(ps.ranked_candidates, db, user_id)


@router.post("/{user_id}/candidates/combine")
def combine(user_id: int, body: CombineIn, db: Session = Depends(get_db)):
    """여러 후보를 골랐을 때 조합 전체를 경로에 다시 적용한 효과"""
    return _wrap(ps.combined_effect, db, user_id, body.selected)


@router.get("/{user_id}/plan")
def get_plan(user_id: int, db: Session = Depends(get_db)):
    return ps.plan_dict(db, user_id)


@router.post("/{user_id}/plan")
def generate_plan(user_id: int, db: Session = Depends(get_db)):
    """Action Plan 생성(적용 중인 계획이 없으면 v1, 있으면 제안 항목 새로고침)"""
    return _wrap(ps.generate_plan, db, user_id)


@router.post("/{user_id}/items/{item_id}")
def respond(user_id: int, item_id: int, body: RespondIn, db: Session = Depends(get_db)):
    """제안 항목에 응답: accept(수락) / reject(거절, 사유 저장) / done(직접 완료 체크)"""
    return _wrap(ps.respond_item, db, user_id, item_id, body.action, body.reason, None, body.reason_code)


@router.post("/{user_id}/track")
def track(user_id: int, db: Session = Depends(get_db)):
    """이행 추적 수동 실행 (동기화 직후 자동 실행됨)"""
    return {"changes": _wrap(ps.track, db, user_id), "deviation": _wrap(ps.deviation, db, user_id)}


@router.post("/{user_id}/replan")
def replan(user_id: int, force: bool = False, db: Session = Depends(get_db)):
    """경로 이탈 시 재설계를 제안(승인 대기). 사용자가 승인하기 전에는 기존 계획이 유지된다."""
    pending = _wrap(ps.propose_replan, db, user_id, None, force)
    return {"proposed": pending is not None, "pending": pending}


@router.post("/{user_id}/plans/{version_id}/decision")
def decide(user_id: int, version_id: int, body: DecideIn, db: Session = Depends(get_db)):
    """재설계 제안 승인/거절 (거절한 사유는 30일간 재제안하지 않음)"""
    return _wrap(ps.decide_plan, db, user_id, version_id, body.approve, body.note)


@router.get("/{user_id}/events")
def events(user_id: int, db: Session = Depends(get_db)):
    """소비 변화 이벤트 (구조적 / 일시적 판정 포함)"""
    return {"events": ps.list_events(db, user_id)}


@router.post("/{user_id}/monitoring/run")
def run_monitoring(user_id: int, db: Session = Depends(get_db)):
    return _wrap(ps.run_monitoring, db, user_id)


@router.post("/{user_id}/events/one-off")
def one_off(user_id: int, body: OneOffIn, db: Session = Depends(get_db)):
    """해당 카테고리·월을 '일회성'으로 지정 (평균과 판정에서 제외)"""
    return _wrap(ps.mark_one_off, db, user_id, body.category, body.month)


@router.get("/{user_id}/notifications")
def notifications(user_id: int, unread_only: bool = False, db: Session = Depends(get_db)):
    return {"notifications": ps.list_notifications(db, user_id, unread_only)}


@router.post("/{user_id}/notifications/{notification_id}/read")
def read(user_id: int, notification_id: int, db: Session = Depends(get_db)):
    if not ps.mark_read(db, user_id, notification_id):
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다.")
    return {"read": True}


@router.get("/{user_id}/forecast")
def forecast(user_id: int, db: Session = Depends(get_db)):
    """이번 달 월말 전망: 예상 지출·월중 최저 현금·월말 잔액·위험도"""
    return _wrap(ps.cash_forecast, db, user_id)


@router.get("/{user_id}/outcomes")
def outcomes(user_id: int, db: Session = Depends(get_db)):
    """사후 보고: 실천한 제안의 실제 결과와 그 덕분에 빨라진 목표 달성 시기"""
    from app.services import feedback_service
    return _wrap(feedback_service.outcome_report, db, user_id)


@router.get("/{user_id}/preferences")
def preferences(user_id: int, db: Session = Depends(get_db)):
    """거절에서 배운 것: 다시 제안하지 않는 후보와 줄여서 제안하는 카테고리"""
    from app.services import feedback_service
    return feedback_service.list_preferences(db, user_id)


@router.delete("/{user_id}/preferences/{pref_id}")
def delete_preference(user_id: int, pref_id: int, db: Session = Depends(get_db)):
    """거절 학습 결과를 지워 다시 제안받는다"""
    from app.services import feedback_service
    if not feedback_service.delete_preference(db, user_id, pref_id):
        raise HTTPException(404, "항목을 찾을 수 없습니다.")
    return {"deleted": pref_id}
