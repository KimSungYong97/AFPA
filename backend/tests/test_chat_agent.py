"""대화 에이전트: 질문 → 도구 호출 → 계산 결과로만 답변"""
import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent import chat_agent
from app.db.session import get_db
from app.main import app
from app.models.entities import Goal, User
from app.pipeline.mydata_source import load_user_data, user_dir
from app.services import pipeline_service


@pytest.fixture()
def seeded(db):
    meta = json.load(open(user_dir(1) / "_user.json", encoding="utf-8"))
    db.add(User(id=1, name=meta["name"]))
    for g in meta["goals"]:
        db.add(Goal(user_id=1, name=g["name"], goal_type=g["goal_type"], target_amount=g["target_amount"],
                    current_amount=g["current_amount"], priority=g["priority"],
                    target_date=date.fromisoformat(g["target_date"]) if g.get("target_date") else None))
    db.commit()
    pipeline_service.record_consent(db, 1)
    pipeline_service.sync_user(db, 1, load_user_data(user_dir(1)), use_llm=False)
    return db


class ScriptedLLM:
    """정해 둔 순서대로 응답한다: [('tool', name, args), ..., ('say', text)]"""

    def __init__(self, script):
        self.script, self.n = list(script), 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        kind, *rest = self.script.pop(0)
        self.n += 1
        if kind == "tool":
            name, args = rest
            tc = SimpleNamespace(id=f"t{self.n}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
            msg = SimpleNamespace(tool_calls=[tc], content=None, model_dump=lambda exclude_none=True, tc=tc: {
                "role": "assistant", "tool_calls": [{"id": tc.id, "type": "function",
                                                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}]})
        else:
            msg = SimpleNamespace(tool_calls=None, content=rest[0])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _use(monkeypatch, script):
    monkeypatch.setattr(chat_agent, "get_llm_client", lambda **k: ScriptedLLM(script))
    monkeypatch.setattr(chat_agent, "llm_enabled", lambda: True)


def test_question_becomes_tool_call_and_grounded_answer(seeded, monkeypatch):
    _use(monkeypatch, [("tool", "what_if_save_more", {"monthly_amount": 300000}), ("say", "월 30만 원을 더 모으면 목표가 빨라져요.")])
    r = chat_agent.chat(seeded, 1, "월 30만 원 더 저축하면?")
    assert r["source"] == "llm" and r["calls"][0]["name"] == "what_if_save_more"
    assert r["calls"][0]["result"]["goals"] and "월 300,000원" in r["calls"][0]["result"]["scenario"]


def test_answer_with_invented_numbers_is_replaced_by_calculation(seeded, monkeypatch):
    _use(monkeypatch, [("tool", "what_if_save_more", {"monthly_amount": 300000}), ("say", "목표가 77개월 빨라지고 9,999,999원이 모여요.")])
    r = chat_agent.chat(seeded, 1, "월 30만 원 더 저축하면?")
    assert r["source"] == "rule" and "9,999,999" not in r["answer"] and "계산 결과" in r["answer"]
    assert "전세보증금" in r["answer"]                                     # 도구 결과를 그대로 정리해 보여 준다


def test_tool_arguments_are_validated_by_code(seeded, monkeypatch):
    _use(monkeypatch, [("tool", "what_if_save_more", {"monthly_amount": 10 ** 12}), ("say", "계산할 수 없는 금액이에요.")])
    r = chat_agent.chat(seeded, 1, "1조 원 저축하면?")
    assert "error" in r["calls"][0]["result"]                              # 비현실적 금액은 도구가 거부
    _use(monkeypatch, [("tool", "delete_everything", {}), ("say", "할 수 없어요.")])
    r2 = chat_agent.chat(seeded, 1, "다 지워줘")
    assert "쓸 수 없는 도구" in json.dumps(r2["calls"][0]["result"], ensure_ascii=False)


def test_forecast_tool_and_no_llm_and_bad_input(seeded, monkeypatch):
    _use(monkeypatch, [("tool", "get_cash_forecast", {}), ("say", "이번 달은 안전해요.")])
    r = chat_agent.chat(seeded, 1, "이번 달 말에 돈이 모자랄까요?")
    assert r["calls"][0]["result"]["risk"] == "안전" and r["calls"][0]["result"]["month_end_cash"].endswith("원")
    monkeypatch.setattr(chat_agent, "llm_enabled", lambda: False)
    off = chat_agent.chat(seeded, 1, "아무거나")
    assert off["source"] == "rule" and off["calls"] == []
    with pytest.raises(ValueError):
        chat_agent.chat(seeded, 1, "   ")
    with pytest.raises(ValueError):
        chat_agent.chat(seeded, 1, "가" * 501)


def test_llm_failure_returns_graceful_message(seeded, monkeypatch):
    class Boom:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kw):
            raise TimeoutError("down")

    monkeypatch.setattr(chat_agent, "get_llm_client", lambda **k: Boom())
    monkeypatch.setattr(chat_agent, "llm_enabled", lambda: True)
    r = chat_agent.chat(seeded, 1, "목표는 언제 달성돼요?")
    assert r["source"] == "rule" and "TimeoutError" in r["error"]


def test_chat_api(seeded, monkeypatch):
    def override():
        yield seeded

    app.dependency_overrides[get_db] = override
    try:
        _use(monkeypatch, [("tool", "get_goal_status", {}), ("say", "목표 현황을 알려 드릴게요.")])
        c = TestClient(app)
        r = c.post("/api/agent/1/chat", json={"message": "내 목표는 어때요?", "history": []})
        assert r.status_code == 200 and r.json()["calls"][0]["name"] == "get_goal_status"
        assert c.post("/api/agent/1/chat", json={"message": ""}).status_code == 422
        assert len(c.get("/api/agent/chat/examples").json()) >= 3
    finally:
        app.dependency_overrides.clear()


def test_goal_name_is_resolved_leniently_but_not_when_ambiguous(seeded):
    from app.agent import tools as T
    c = T.Ctx(seeded, 1)
    assert T.resolve_goal(c, "전세보증금 마련") == ("전세보증금 마련", None)          # 정확히 일치
    assert T.resolve_goal(c, "전세보증금") == ("전세보증금 마련", None)               # 한쪽이 다른 쪽을 포함 → 유일하면 찾는다
    name, err = T.resolve_goal(c, "여행")
    assert name == "일본 여행" and err is None
    name, err = T.resolve_goal(c, "자동차")
    assert name is None and "전세보증금 마련" in err and "일본 여행" in err           # 없으면 선택지를 알려 준다
    out = T.tool_what_if_goal_shift(c, goal="전세보증금", shift_months=6)
    assert out["scenario"] == "'전세보증금 마련' 목표 조정" and out["goals"]
