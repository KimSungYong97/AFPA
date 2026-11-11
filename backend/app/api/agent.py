"""변화 감시 에이전트 API — 프로필 변화를 지켜보고 알리며 계획 변경 필요 여부를 알려 준다"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent import change_agent, demo
from app.db.session import get_db

router = APIRouter()


class DemoChangeIn(BaseModel):
    kind: str


@router.post("/{user_id}/run")
def run_agent(user_id: int, use_llm: bool = True, db: Session = Depends(get_db)):
    """에이전트를 한 번 실행한다. 새 데이터가 없으면 아무것도 하지 않는다."""
    try:
        r = change_agent.run_guarded(db, user_id, use_llm=use_llm)
    except LookupError as e:
        raise HTTPException(404, str(e))
    if r is None:
        raise HTTPException(409, "에이전트가 이미 확인하는 중이에요. 잠시 후 다시 확인해 주세요.")
    return r


@router.get("/{user_id}/runs")
def runs(user_id: int, limit: int = 10, db: Session = Depends(get_db)):
    return change_agent.history(db, user_id, limit)


@router.get("/{user_id}/status")
def status(user_id: int):
    """에이전트가 지금 이 사용자의 변화를 확인하는 중인지"""
    return {"running": change_agent.is_running(user_id)}


@router.get("/{user_id}/latest")
def latest(user_id: int, db: Session = Depends(get_db)):
    r = change_agent.last_run(db, user_id)
    return change_agent.run_dict(r) if r else None


@router.get("/demo/kinds")
def demo_kinds():
    return demo.KINDS


@router.post("/{user_id}/demo-change")
def demo_change(user_id: int, body: DemoChangeIn, db: Session = Depends(get_db)):
    """(데모) 가상 변화를 주입한다. 다시 마이데이터를 연동하면 원래대로 돌아간다."""
    try:
        return demo.simulate_change(db, user_id, body.kind)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


class ChatIn(BaseModel):
    message: str
    history: list = []
    use_llm: bool = True


@router.post("/{user_id}/chat")
def chat(user_id: int, body: ChatIn, db: Session = Depends(get_db)):
    """자연어 질문 → 도구 호출 → 계산 결과로 답변. 숫자는 코드가 계산한 값만 쓴다."""
    from app.agent import chat_agent
    try:
        return chat_agent.chat(db, user_id, body.message, body.history, use_llm=body.use_llm)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.get("/chat/examples")
def chat_examples():
    from app.agent import chat_agent
    return chat_agent.EXAMPLES
