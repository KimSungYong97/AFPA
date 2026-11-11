"""피드백 루프: 거절 학습(다시 제안하지 않음·규모 축소) + 사후 보고(실천 결과·목표 단축 효과)"""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agent import change_agent, demo
from app.db.session import get_db
from app.main import app
from app.models.entities import ActionItem, ClassifiedFlow, Goal, PlannerPreference, User
from app.pipeline.mydata_source import load_user_data, user_dir
from app.services import feedback_service as fb
from app.services import pipeline_service
from app.services import planner_service as ps

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
    ps.generate_plan(db, 1, TODAY)
    return db


def _item(db, key):
    return db.query(ActionItem).filter_by(item_key=key).first()


def _keys(db):
    return [c["key"] for c in ps.ranked_candidates(db, 1)["candidates"]]


def _saving(db, key):
    return next(c["monthly_saving"] for c in ps.ranked_candidates(db, 1)["candidates"] if c["key"] == key)


# ---------------------------------------------------------------- 거절 학습
def test_needed_rejection_is_remembered_for_a_year(seeded):
    ps.respond_item(seeded, 1, _item(seeded, "sub:넷플릭스").id, "reject", "꼭 필요한 지출이에요", TODAY, "needed")
    assert "sub:넷플릭스" not in _keys(seeded)                         # 같은 제안을 다시 하지 않는다
    far = fb.learned(seeded, 1, date.today() + timedelta(days=200))
    assert "sub:넷플릭스" in far["exclude"]                            # 200일 뒤에도 유지(1년)
    assert "sub:넷플릭스" not in fb.learned(seeded, 1, date.today() + timedelta(days=400))["exclude"]


def test_burden_rejection_pauses_the_item_and_halves_the_category_scale(seeded):
    ps.respond_item(seeded, 1, _item(seeded, "cut:쇼핑").id, "reject", "금액이 부담돼요", TODAY, "burden")
    assert "cut:쇼핑" not in _keys(seeded)                             # 30일 동안은 쉰다
    assert fb.learned(seeded, 1)["cut_scale"]["쇼핑"] == 0.5
    far = fb.learned(seeded, 1, date.today() + timedelta(days=31))
    assert "cut:쇼핑" not in far["exclude"]                            # 30일이 지나면 다시 제안 대상이 된다


def test_scale_makes_the_proposal_smaller_or_drops_it_when_too_small(seeded):
    from app.pipeline import params
    from app.planner import candidates as ce
    from app.planner.path import PathGoal, PathInput
    months = ["2026-03", "2026-04", "2026-05"]
    mk = lambda scale: ce.generate(ce.CandidateContext(
        path_input=PathInput(date(2026, 8, 7), 1_000_000, [PathGoal("전세", 30_000_000, 0, date(2028, 8, 7), 1)], annual_return=0.0),
        monthly_income=3_000_000, category_monthly={"쇼핑": {m: 600_000 for m in months}}, window=months,
        emergency={"coverage_ratio": 150, "required": 3_000_000, "liquid_cash": 4_500_000, "monthly_essential_expense": 1_000_000},
        prefs={"cut_scale": scale}))
    full = next(c for c in mk({}) if c["key"] == "cut:쇼핑")
    half = next(c for c in mk({"쇼핑": 0.5}) if c["key"] == "cut:쇼핑")
    assert full["monthly_saving"] == 90_000 and half["monthly_saving"] == 45_000      # 15% → 7.5%
    assert "7.5%" in half["title"] and half["params"]["cut_rate"] == pytest.approx(params.G_CUT_RATE_NONESSENTIAL * 0.5)
    assert not [c for c in mk({"쇼핑": 0.01}) if c["key"] == "cut:쇼핑"]               # 너무 작아지면 제안하지 않는다


def test_repeated_burden_stops_at_minimum_scale(seeded):
    for _ in range(4):
        fb.record_rejection(seeded, 1, "cut:쇼핑", False, "burden", "", TODAY)
    assert fb.learned(seeded, 1)["cut_scale"]["쇼핑"] == 0.25


def test_mandatory_items_are_never_learned_away(seeded):
    emergency = _item(seeded, "emergency")
    ps.respond_item(seeded, 1, emergency.id, "reject", "나중에 할게요", TODAY, "later")
    assert seeded.query(PlannerPreference).count() == 0
    assert "emergency" in _keys(seeded)                                # 비상금은 거절해도 계속 보여 준다


def test_label_text_maps_to_reason_without_code_and_unknown_defaults_to_short(seeded):
    ps.respond_item(seeded, 1, _item(seeded, "cut:문화/여가").id, "reject", "이미 하고 있어요", TODAY)
    p = seeded.query(PlannerPreference).filter_by(target="cut:문화/여가").first()
    assert p.reason_code == "already" and p.until > TODAY + timedelta(days=300)
    ps.respond_item(seeded, 1, _item(seeded, "sub:넷플릭스").id, "reject", "그냥", TODAY)
    assert seeded.query(PlannerPreference).filter_by(target="sub:넷플릭스").first().reason_code == "later"


def test_user_can_delete_a_learned_preference(seeded):
    ps.respond_item(seeded, 1, _item(seeded, "sub:넷플릭스").id, "reject", "꼭 필요한 지출이에요", TODAY, "needed")
    prefs = fb.list_preferences(seeded, 1)
    assert prefs and prefs[0]["target"] == "sub:넷플릭스"
    assert fb.delete_preference(seeded, 2, prefs[0]["id"]) is False     # 다른 사용자는 지울 수 없다
    assert fb.delete_preference(seeded, 1, prefs[0]["id"]) is True
    assert "sub:넷플릭스" in _keys(seeded)


# ---------------------------------------------------------------- 사후 보고
def _accept_and_pass_a_month(db, key="cut:쇼핑", cut_to=0.0):
    ps.respond_item(db, 1, _item(db, key).id, "accept", today=TODAY)
    _item(db, key).accepted_as_of = "2026-06"                           # 수락 후 7월이 완결된 상황
    if cut_to is not None:
        db.query(ClassifiedFlow).filter(
            ClassifiedFlow.category == "쇼핑", ClassifiedFlow.occurred_on >= date(2026, 7, 1),
            ClassifiedFlow.occurred_on < date(2026, 8, 1)).delete()
    db.commit()
    ps.track(db, 1, TODAY)


def test_outcome_report_waits_before_the_first_check(seeded):
    ps.respond_item(seeded, 1, _item(seeded, "cut:쇼핑").id, "accept", today=TODAY)
    r = fb.outcome_report(seeded, 1)
    assert r["waiting_count"] == 1 and r["realized_monthly"] == 0 and "다음 달" in r["headline"]


def test_outcome_report_computes_realized_saving_and_goal_effect(seeded):
    _accept_and_pass_a_month(seeded)
    r = fb.outcome_report(seeded, 1)
    item = r["items"][0]
    assert item["state"] == "achieved" and item["actual"] > 0 and item["ratio"] >= 0.8
    assert r["realized_monthly"] == min(item["actual"], round(item["expected"] * 1.5))   # 과대 집계 방지: 목표의 1.5배까지만 인정
    assert r["goal_effect"]["goal"] and "달성" in r["headline"] or "아꼈어요" in r["headline"]


def test_outcome_event_is_reported_once_by_the_agent_and_notification_is_low(seeded):
    change_agent.ensure_baseline(seeded, 1)
    _accept_and_pass_a_month(seeded)
    pipeline_service.compute_and_store_snapshot(seeded, 1)               # 새 데이터가 들어온 상황
    r = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    oc = [e for e in r["events"] if e["event_type"] == "outcome"]
    assert oc and oc[0]["judgement"] == "outcome" and "실천해서" in oc[0]["message"]
    from app.models.entities import Notification
    assert seeded.query(Notification).filter_by(kind="agent_change").first().grade in ("low", "medium", "high")
    pipeline_service.compute_and_store_snapshot(seeded, 1)
    again = change_agent.run(seeded, 1, use_llm=False, today=TODAY)
    assert not [e for e in again["events"] if e["event_type"] == "outcome"]    # 같은 성과는 반복해서 알리지 않는다


# ---------------------------------------------------------------- API
def test_feedback_api(seeded):
    def override():
        yield seeded

    app.dependency_overrides[get_db] = override
    try:
        c = TestClient(app)
        item = next(i for i in c.get("/api/planner/1/plan").json()["active"]["items"] if i["key"] == "sub:넷플릭스")
        r = c.post(f"/api/planner/1/items/{item['id']}", json={"action": "reject", "reason": "금액이 부담돼요", "reason_code": "later"})
        assert r.status_code == 200
        assert c.post(f"/api/planner/1/items/{item['id']}", json={"action": "reject", "reason_code": "bogus"}).status_code == 422
        prefs = c.get("/api/planner/1/preferences").json()
        assert prefs[0]["target"] == "sub:넷플릭스"
        assert c.delete(f"/api/planner/1/preferences/{prefs[0]['id']}").status_code == 200
        assert c.delete("/api/planner/1/preferences/999").status_code == 404
        o = c.get("/api/planner/1/outcomes").json()
        assert o["has_plan"] and "headline" in o
    finally:
        app.dependency_overrides.clear()
