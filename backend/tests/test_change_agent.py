"""변화 감시 에이전트: 변화 감지 → (LLM 조사) → 검증 → 알림·재설계 제안"""
import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent import change_agent, demo
from app.db.session import get_db
from app.main import app
from app.models.entities import AgentRun, Goal, Notification, PlanVersion, User
from app.pipeline.mydata_source import load_user_data, user_dir
from app.services import pipeline_service

TODAY = date(2026, 8, 10)


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


# ---------------------------------------------------------------- 규칙 경로
def test_first_run_records_baseline_then_no_new_data(seeded):
    first = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    assert first["status"] == "baseline"
    second = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    assert second["status"] == "no_new_data"
    assert seeded.query(AgentRun).count() == 1                   # 새 데이터가 없으면 기록도 남기지 않는다


def test_income_drop_detected_and_replan_proposed(seeded):
    demo.simulate_change(seeded, 1, "income_drop")
    r = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    assert r["status"] == "reported" and r["severity"] == "important" and r["generated_by"] == "rule"
    assert r["plan_change_needed"] is True and r["replan_version_id"]
    assert any(c["field"] == "monthly_income_net" and c["direction"] == "down" for c in r["changes"])
    assert any(g["delay"] and "늦어짐" in g["delay"] for g in r["plan_change"]["goals"])
    pv = seeded.get(PlanVersion, r["replan_version_id"])
    assert pv.status == "pending"                                # 승인 전에는 기존 계획 유지
    assert seeded.query(PlanVersion).filter_by(status="active").count() == 1
    assert seeded.query(Notification).filter_by(kind="agent_change").count() == 1
    assert [s["kind"] for s in r["steps"]][0] == "observe" and r["steps"][-1]["kind"] == "act"


def test_other_changes_are_reported(seeded):
    demo.simulate_change(seeded, 1, "new_fixed")
    r = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    assert r["status"] == "reported" and r["plan_change_needed"] is True
    seeded2 = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    assert seeded2["status"] == "no_new_data"
    demo.simulate_change(seeded, 1, "spending_surge")
    r2 = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    assert r2["status"] in ("reported", "no_change")
    with pytest.raises(ValueError):
        demo.simulate_change(seeded, 1, "meteor")


# ---------------------------------------------------------------- LLM 경로 (스텁)
class FakeLLM:
    """tool_calls → 도구 결과 수신 → 최종 JSON 순서로 응답하는 스텁 클라이언트"""

    def __init__(self, final: dict, tools=("get_profile_changes", "get_spending_events", "get_plan_status")):
        self.final, self.tools, self.calls = final, list(tools), 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls += 1
        if self.tools:
            name = self.tools.pop(0)
            tc = SimpleNamespace(id=f"t{self.calls}", function=SimpleNamespace(name=name, arguments="{}"))
            msg = SimpleNamespace(tool_calls=[tc], content=None,
                                  model_dump=lambda exclude_none=True, tc=tc: {
                                      "role": "assistant", "tool_calls": [{"id": tc.id, "type": "function", "function": {
                                          "name": tc.function.name, "arguments": "{}"}}]})
        else:
            msg = SimpleNamespace(tool_calls=None, content=json.dumps(self.final, ensure_ascii=False))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _use_llm(monkeypatch, fake):
    monkeypatch.setattr(change_agent, "get_llm_client", lambda **k: fake)
    monkeypatch.setattr(change_agent, "llm_enabled", lambda: True)


GOOD = {"headline": "월 소득이 줄어서 여유 자금도 줄었어요.",
        "findings": [{"ref": "C1", "meaning": "소득 감소가 가장 큰 원인이에요."}, {"ref": "ZZ", "meaning": "없는 근거"}],
        "plan_change_needed": False, "plan_change_reason": "여유 자금이 줄어 목표가 늦어져요.",
        "next_step": "새 계획을 확인해 주세요.", "questions": ["소득 감소가 계속될 것 같나요?"]}


def test_llm_agent_investigates_and_code_overrides_plan_decision(seeded, monkeypatch):
    demo.simulate_change(seeded, 1, "income_drop")
    fake = FakeLLM(GOOD)
    _use_llm(monkeypatch, fake)
    r = change_agent.run(seeded, 1, use_llm=True, today=TODAY)
    assert r["generated_by"] == "llm" and r["llm_mode"] == "tool_calling" and r["fallback_reason"] is None
    assert [s["title"] for s in r["steps"] if s["kind"] == "tool"] == ["프로필 변화 조회", "소비 변화 조회", "계획 이탈 여부 확인"]
    assert [f["ref"] for f in r["findings"]] == ["C1"]                      # 근거 id가 없는 항목은 버린다
    assert r["plan_change"]["llm_opinion"] is False and r["plan_change"]["needed"] is True   # 최종 결정은 코드
    assert any(s["title"] == "판단 차이 정정" for s in r["steps"])
    assert r["replan_version_id"]


def test_llm_output_with_unfounded_numbers_is_discarded(seeded, monkeypatch):
    demo.simulate_change(seeded, 1, "income_drop")
    bad = dict(GOOD, headline="월 소득이 9,999,999원이나 줄었어요.")
    _use_llm(monkeypatch, FakeLLM(bad))
    r = change_agent.run(seeded, 1, use_llm=True, today=TODAY)
    assert r["generated_by"] == "rule" and "수치" in r["fallback_reason"]
    assert "9,999,999" not in r["headline"]
    assert r["plan_change_needed"] is True                                   # LLM이 실패해도 알림·재설계는 그대로 진행


def test_llm_failure_falls_back_to_rules(seeded, monkeypatch):
    demo.simulate_change(seeded, 1, "income_drop")

    class Boom:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kw):
            raise TimeoutError("server down")

    _use_llm(monkeypatch, Boom())
    r = change_agent.run(seeded, 1, use_llm=True, today=TODAY)
    assert r["generated_by"] == "rule" and "TimeoutError" in r["fallback_reason"] and r["status"] == "reported"


def test_what_if_tool_validates_range(seeded):
    c = change_agent._Ctx(seeded, 1, TODAY, [], [])
    ok = change_agent.tool_what_if_save_more(c, monthly_amount=100_000)
    assert ok["goals"] and "effect" in ok["goals"][0]
    assert "error" in change_agent.tool_what_if_save_more(c, monthly_amount=10**12)     # 범위를 벗어난 값은 거부


# ---------------------------------------------------------------- API
def test_agent_api(seeded):
    def override():
        yield seeded

    app.dependency_overrides[get_db] = override
    try:
        c = TestClient(app)
        assert c.get("/api/agent/1/latest").json() is None
        d = c.post("/api/agent/1/demo-change", json={"kind": "income_drop"})
        assert d.status_code == 200
        r = c.post("/api/agent/1/run", params={"use_llm": False}).json()
        assert r["status"] == "reported" and r["plan_change_needed"]
        assert c.get("/api/agent/1/latest").json()["id"] == r["id"]
        assert len(c.get("/api/agent/1/runs").json()) == 2                   # 기준 + 보고
        assert c.post("/api/agent/1/demo-change", json={"kind": "x"}).status_code == 422
        assert c.post("/api/agent/99/run").status_code == 404
        assert set(c.get("/api/agent/demo/kinds").json()) == set(demo.KINDS)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------- 동기화 직후 자동 실행
def test_sync_triggers_agent_automatically(seeded):
    def override():
        yield seeded

    app.dependency_overrides[get_db] = override
    try:
        c = TestClient(app)
        r = c.post("/api/mydata/1/sync", params={"use_llm": False})
        assert r.json()["agent"] == "scheduled"
        runs = c.get("/api/agent/1/runs").json()
        assert [x["status"] for x in runs] == ["baseline"]                 # 응답 뒤 백그라운드에서 실행됨
        demo.simulate_change(seeded, 1, "income_drop")                     # 새 데이터가 들어온 것처럼
        r = c.post("/api/mydata/1/sync", params={"use_llm": False, "agent": False})
        assert r.json()["agent"] == "skipped" and len(c.get("/api/agent/1/runs").json()) == 1
        assert c.get("/api/agent/1/status").json() == {"running": False}
    finally:
        app.dependency_overrides.clear()


def test_same_event_is_not_reported_twice(seeded):
    demo.simulate_change(seeded, 1, "income_drop")
    first = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    assert first["events"]
    pipeline_service.compute_and_store_snapshot(seeded, 1)               # 같은 상태의 새 스냅샷(다시 동기화한 것과 같다)
    second = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    assert second["status"] == "no_change" and not second["events"]       # 이미 알린 변화는 반복하지 않는다


def test_run_guard_blocks_concurrent_runs(seeded):
    change_agent._RUNNING.add(1)
    try:
        assert change_agent.run_guarded(seeded, 1, use_llm=False) is None
        assert change_agent.is_running(1)
    finally:
        change_agent._RUNNING.discard(1)
    assert change_agent.run_guarded(seeded, 1, use_llm=False)["status"] == "baseline"


# ---------------------------------------------------------------- 월중 현금 전망 경고
def test_month_spike_triggers_forecast_alert_once(seeded):
    demo.simulate_change(seeded, 1, "month_spike")
    r = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    fc = [e for e in r["events"] if e["event_type"] == "cash_forecast"]
    assert r["status"] == "reported" and len(fc) == 1 and fc[0]["judgement"] == "forecast"
    assert "예상돼요" in fc[0]["message"] or "부족" in fc[0]["message"]
    assert seeded.query(Notification).filter_by(kind="agent_change").count() == 1
    pipeline_service.compute_and_store_snapshot(seeded, 1)               # 같은 상태에서 다시 확인해도
    again = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    assert again["status"] == "no_change"                                # 같은 달·같은 위험도는 반복해서 알리지 않는다


def test_forecast_api(seeded):
    def override():
        yield seeded

    app.dependency_overrides[get_db] = override
    try:
        f = TestClient(app).get("/api/planner/1/forecast").json()
        assert f["status"] == "ok" and f["risk"] in ("ok", "watch", "danger") and f["days_in_month"] >= 28
    finally:
        app.dependency_overrides.clear()
