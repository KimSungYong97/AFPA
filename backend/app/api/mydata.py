"""마이데이터 연동 API (1차: 규격 기반 테스트 데이터)"""
from datetime import date
from typing import Optional

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent import change_agent
from app.db.session import get_db
from app.llm_client import llm_enabled
from app.models.schemas import ConsentIn
from app.pipeline.mydata_source import load_user_data, user_dir
from app.services import pipeline_service

router = APIRouter()
logger = logging.getLogger(__name__)


def _agent_after_sync(bind, user_id: int, use_llm: bool) -> None:
    """응답을 보낸 뒤 백그라운드에서 변화 감시 에이전트를 돌린다(AI 조사에 30초쯤 걸려서 동기화 응답을 막지 않는다)."""
    db = Session(bind=bind)
    try:
        change_agent.run_guarded(db, user_id, use_llm=use_llm)
    except Exception:  # noqa: BLE001 - 에이전트 실패가 동기화 결과에 영향을 주면 안 된다
        logger.exception("동기화 후 변화 감시 에이전트 실행 실패 (user %s)", user_id)
    finally:
        db.close()


@router.post("/{user_id}/consent")
def record_consent(user_id: int, body: ConsentIn, db: Session = Depends(get_db)):
    """항목별 동의 기록. 1차는 전체 동의를 전제로 하므로 미동의 항목이 있으면 거부한다(D-09)."""
    try:
        pipeline_service.record_consent(
            db, user_id, body.is_consent_merchant_name_regno,
            body.is_consent_trans_memo, body.is_consent_trans_category)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"user_id": user_id, "consented": True}


@router.post("/{user_id}/sync")
def sync(user_id: int, background: BackgroundTasks, as_of: Optional[date] = None, use_llm: bool = True,
         agent: bool = True, db: Session = Depends(get_db)):
    """마이데이터 동기화: 분류 → 저장 → 프로필 산출(스냅샷 누적).

    1차는 data/mydata/user_XXX 테스트 데이터를 사용한다. 실연동 시 mydata_source만 교체한다.
    """
    path = user_dir(user_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"사용자 {user_id}의 마이데이터가 없습니다.")
    try:
        result = pipeline_service.sync_user(db, user_id, load_user_data(path), as_of, use_llm)
        if agent:                                     # 새 데이터가 들어오면 변화 감시 에이전트가 스스로 확인한다
            background.add_task(_agent_after_sync, db.get_bind(), user_id, llm_enabled())
        result["agent"] = "scheduled" if agent else "skipped"
        return result
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
