"""통합 플래너 서비스: Action Plan · 이행 추적 · 경로 이탈 · 재설계(승인 후 적용) · 모니터링 · 알림 · 브리핑"""
import json
from datetime import date, timedelta

import pytest

from app.models.entities import ActionItem, ClassifiedFlow, Goal, MonitoringEvent, PlanVersion, User
from app.pipeline.mydata_source import load_user_data, user_dir
from app.services import briefing_service, pipeline_service
from app.services import planner_service as ps

TODAY = date(2026, 8, 10)


def _seed(db, uid=1):
    meta = json.load(open(user_dir(uid) / "_user.json", encoding="utf-8"))
    db.add(User(id=uid, name=meta["name"]))
    for g in meta["goals"]:
        db.add(Goal(user_id=uid, name=g["name"], goal_type=g["goal_type"], target_amount=g["target_amount"],
                    current_amount=g["current_amount"], priority=g["priority"],
                    target_date=date.fromisoformat(g["target_date"]) if g.get("target_date") else None))
    db.commit()
    pipeline_service.record_consent(db, uid)
    pipeline_service.sync_user(db, uid, load_user_data(user_dir(uid)), use_llm=False)


@pytest.fixture()
def seeded(db):
    _seed(db)
    return db


def _item(db, key):
    return db.query(ActionItem).filter_by(item_key=key).first()


def _add_fixed_flow(db, amount, counterparty="신규 정기지출"):
    """관측 기간 매월 고정지출을 추가해 월 여유 자금을 낮춘다(경로 이탈 재현용)"""
    for m in range(3, 8):
        db.add(ClassifiedFlow(user_id=1, occurred_on=date(2026, m, 15), amount=amount, direction="out",
                              source="bank", counterparty=counterparty, merchant_norm="", major_class="fixed",
                              category="주거", stage=1, rule="test", is_recurring=True))
    db.commit()
    pipeline_service.compute_and_store_snapshot(db, 1)


# ---------------------------------------------------------------- Action Plan
def test_generate_plan_creates_active_v1_with_mandatory_emergency_first(seeded):
    plan = ps.generate_plan(seeded, 1, TODAY)["active"]
    assert plan["version"] == 1 and plan["baseline"]["goals"][0]["name"] == "전세보증금 마련"
    items = plan["items"]
    assert items[0]["key"] == "emergency" and items[0]["mandatory"] and items[0]["priority"] == 0
    assert all(i["status"] == "PROPOSED" and i["rationale"] for i in items)
    assert items[0]["path_effect"]["months_saved"] < 0                   # 비상금을 먼저 채우면 목표가 늦어진다
    # 다시 생성해도 항목이 중복되지 않는다
    again = ps.generate_plan(seeded, 1, TODAY)["active"]
    assert [i["key"] for i in again["items"]] == [i["key"] for i in items]


def test_item_state_transitions(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    cut = _item(seeded, "cut:쇼핑")
    accepted = ps.respond_item(seeded, 1, cut.id, "accept", today=TODAY)
    assert accepted["status"] == "ACCEPTED" and accepted["tracked_by"] == "auto"
    with pytest.raises(ValueError):                                       # 이미 수락한 항목은 다시 수락할 수 없다
        ps.respond_item(seeded, 1, cut.id, "accept", today=TODAY)
    sub = _item(seeded, "sub:넷플릭스")
    rejected = ps.respond_item(seeded, 1, sub.id, "reject", "안 보지만 가족이 써요", TODAY)
    assert rejected["status"] == "REJECTED" and "가족" in rejected["reject_reason"]   # 거절 사유 저장(학습 기반)
    with pytest.raises(LookupError):
        ps.respond_item(seeded, 2, cut.id, "reject", today=TODAY)         # 다른 사용자 항목은 접근 불가


def test_adopted_items_are_excluded_from_new_candidates(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    ps.respond_item(seeded, 1, _item(seeded, "cut:쇼핑").id, "accept", today=TODAY)
    keys = [c["key"] for c in ps.ranked_candidates(seeded, 1)["candidates"]]
    assert "cut:쇼핑" not in keys


# ---------------------------------------------------------------- 이행 추적
def test_tracking_marks_done_only_after_a_later_complete_month(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    cut = _item(seeded, "cut:쇼핑")
    ps.respond_item(seeded, 1, cut.id, "accept", today=TODAY)
    assert cut.accepted_as_of == "2026-07"                                # 수락 시점의 마지막 완결월
    assert ps.track(seeded, 1, TODAY) == []                               # 수락 이후 완결된 달이 아직 없다
    assert cut.status == "ACCEPTED"


def test_tracking_auto_detects_reduced_spending_and_cancelled_subscription(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    cut, sub = _item(seeded, "cut:쇼핑"), _item(seeded, "sub:넷플릭스")
    ps.respond_item(seeded, 1, cut.id, "accept", today=TODAY)
    ps.respond_item(seeded, 1, sub.id, "accept", today=TODAY)
    cut.accepted_as_of = sub.accepted_as_of = "2026-06"                   # 수락 후 7월이 완결된 상황을 만든다
    seeded.query(ClassifiedFlow).filter(
        ClassifiedFlow.category == "쇼핑", ClassifiedFlow.occurred_on >= date(2026, 7, 1),
        ClassifiedFlow.occurred_on < date(2026, 8, 1)).delete()
    seeded.query(ClassifiedFlow).filter(
        ClassifiedFlow.counterparty == "넷플릭스", ClassifiedFlow.occurred_on >= date(2026, 7, 1),
        ClassifiedFlow.occurred_on < date(2026, 8, 1)).delete()
    seeded.commit()
    changes = ps.track(seeded, 1, TODAY)
    assert {c["key"] for c in changes} == {"cut:쇼핑", "sub:넷플릭스"}
    assert cut.status == "DONE" and sub.status == "DONE"
    assert json.loads(cut.progress_json)["ratio"] >= 0.8


def test_partial_reduction_stays_accepted_with_progress(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    cut = _item(seeded, "cut:쇼핑")
    ps.respond_item(seeded, 1, cut.id, "accept", today=TODAY)
    cut.accepted_as_of = "2026-06"
    seeded.commit()
    ps.track(seeded, 1, TODAY)                                            # 7월 지출은 그대로 → 절감 0
    assert cut.status == "ACCEPTED" and json.loads(cut.progress_json)["ratio"] < 0.8


def test_stale_proposals_expire(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    changes = ps.track(seeded, 1, TODAY + timedelta(days=31))
    assert changes and all(c["status"] == "EXPIRED" for c in changes)


# ---------------------------------------------------------------- 경로 이탈 · 재설계
def test_no_deviation_right_after_planning(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    assert ps.deviation(seeded, 1) is None
    assert ps.propose_replan(seeded, 1, TODAY) is None


def test_budget_drop_triggers_replan_proposal_that_waits_for_approval(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    ps.respond_item(seeded, 1, _item(seeded, "cut:쇼핑").id, "accept", today=TODAY)
    _add_fixed_flow(seeded, 400_000)                                      # 월 여유 자금 −400,000원 (−34%)
    dev = ps.deviation(seeded, 1)
    assert dev["trigger"] == "budget_change" and dev["reason_key"] == "budget_change:down"

    pending = ps.propose_replan(seeded, 1, TODAY)
    assert pending["version"] == 2 and pending["comparison"]["budget_after"] < pending["comparison"]["budget_before"]
    assert pending["comparison"]["carried_over"] == ["쇼핑 지출 15% 줄이기"]
    state = ps.plan_dict(seeded, 1)
    assert state["active"]["version"] == 1                                # 승인 전에는 기존 계획이 유지된다
    assert ps.propose_replan(seeded, 1, TODAY) is None                    # 승인 대기 중에는 새 제안을 만들지 않는다
    note = [n for n in ps.list_notifications(seeded, 1) if n["kind"] == "replan_proposal"]
    assert note and note[0]["grade"] == "high"

    res = ps.decide_plan(seeded, 1, pending["id"], approve=True, today=TODAY)
    assert res == {"status": "active", "version": 2}
    state = ps.plan_dict(seeded, 1)
    assert state["active"]["version"] == 2 and state["pending"] is None
    keys = [i["key"] for i in state["active"]["items"]]
    assert keys.count("cut:쇼핑") == 1                                    # 수락한 항목은 새 버전으로 이어진다
    assert seeded.query(PlanVersion).filter_by(version=1).one().status == "superseded"
    assert ps.deviation(seeded, 1) is None                                # 새 기준으로 다시 정렬됨


def test_rejected_replan_is_not_reproposed_for_30_days(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    _add_fixed_flow(seeded, 400_000)
    pending = ps.propose_replan(seeded, 1, TODAY)
    ps.decide_plan(seeded, 1, pending["id"], approve=False, note="지금은 괜찮아요", today=TODAY)
    assert ps.plan_dict(seeded, 1)["active"]["version"] == 1
    assert ps.propose_replan(seeded, 1, TODAY + timedelta(days=10)) is None       # 같은 사유 30일 금지
    assert ps.propose_replan(seeded, 1, TODAY + timedelta(days=31)) is not None


def test_goal_change_triggers_replan(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    g = seeded.query(Goal).filter_by(user_id=1, priority=1).one()
    g.target_amount += 10_000_000
    seeded.commit()
    dev = ps.deviation(seeded, 1)
    assert dev["trigger"] == "goal_change"


# ---------------------------------------------------------------- 소비 변화 모니터링 · 알림
def _add_card_spend(db, month_amounts, category="쇼핑"):
    for (y, m), amt in month_amounts.items():
        db.add(ClassifiedFlow(user_id=1, occurred_on=date(y, m, 20), amount=amt, direction="out", source="card",
                              counterparty="특가몰", merchant_norm="특가몰", major_class="variable",
                              category=category, stage=1, rule="test"))
    db.commit()


def test_monitoring_flags_two_month_increase_as_structural_with_goal_impact_and_notification(seeded):
    _add_card_spend(seeded, {(2026, 6): 400_000, (2026, 7): 400_000})
    res = ps.run_monitoring(seeded, 1, TODAY)
    ev = next(e for e in res["events"] if e["category"] == "쇼핑")
    assert ev["judgement"] == "structural" and ev["grade"] in ("medium", "high")
    assert ev["goal_delay_months"] is None or ev["goal_delay_months"] > 0
    n = [x for x in ps.list_notifications(seeded, 1) if x["kind"] == "spending_change"]
    assert n and ps.run_monitoring(seeded, 1, TODAY)["events"]            # 다시 실행해도 알림은 중복 생성되지 않는다
    assert len([x for x in ps.list_notifications(seeded, 1) if x["kind"] == "spending_change"]) == len(n)


def test_one_off_mark_removes_event(seeded):
    seeded.query(ClassifiedFlow).filter_by(user_id=1, category="쇼핑").delete()     # 통제된 시계열로 교체
    _add_card_spend(seeded, {(2026, 3): 300_000, (2026, 4): 300_000, (2026, 5): 300_000,
                             (2026, 6): 300_000, (2026, 7): 900_000})          # 한 달만 급증 → 일시적
    ev = [e for e in ps.run_monitoring(seeded, 1, TODAY)["events"] if e["category"] == "쇼핑"][0]
    assert ev["judgement"] == "temporary" and ev["grade"] == "low"
    res = ps.mark_one_off(seeded, 1, "쇼핑", "2026-07")
    assert not [e for e in res["events"] if e["category"] == "쇼핑"]      # 일회성 지정 → 평균·판정에서 제외


def test_notification_dedupe_and_immediate_limit(seeded):
    a = ps.notify(seeded, 1, "replan_proposal", "high", "A", "a", "key:a", today=TODAY)
    b = ps.notify(seeded, 1, "replan_proposal", "high", "B", "b", "key:b", today=TODAY)
    dup = ps.notify(seeded, 1, "replan_proposal", "high", "A2", "a", "key:a", today=TODAY + timedelta(days=3))
    again = ps.notify(seeded, 1, "replan_proposal", "high", "A3", "a", "key:a", today=TODAY + timedelta(days=8))
    assert a.delivery == "immediate" and b.delivery == "daily"            # 즉시 알림은 하루 1건
    assert dup is None and again is not None                              # 같은 이벤트는 7일간 재알림 안 함
    low = ps.notify(seeded, 1, "spending_change", "low", "L", "l", "key:l", today=TODAY)
    assert low.delivery == "weekly"
    assert ps.mark_read(seeded, 1, a.id) and ps.list_notifications(seeded, 1, unread_only=True)


# ---------------------------------------------------------------- 경로 · 시나리오 · 브리핑
def test_path_view_shows_base_and_improved_paths(seeded):
    ps.generate_plan(seeded, 1, TODAY)
    view = ps.path_view(seeded, 1)
    assert view["base"]["goals"][0]["name"] == "전세보증금 마련"
    assert view["improved"]["extra_monthly"] > 0
    assert len(view["base"]["series"]) > 24


def test_scenarios_view_and_validation(seeded):
    out = ps.scenarios_view(seeded, 1, [{"kind": "save_delta", "delta": 200_000},
                                        {"kind": "expense", "month": 3, "amount": 3_000_000}])
    assert len(out["scenarios"]) == 2
    assert out["scenarios"][0]["effects"][0]["months_saved"] > 0
    assert out["scenarios"][1]["effects"][0]["months_saved"] < 0
    with pytest.raises(ValueError):
        ps.scenarios_view(seeded, 1, [{"kind": "expense", "month": 0, "amount": 1000}])


def test_briefing_template_and_llm_number_validation(seeded, monkeypatch):
    b = briefing_service.compose(seeded, 1, use_llm=False)
    assert b["narrative_source"] == "template" and "월 여유 자금" in b["narrative"]
    assert b["actions"][0]["mandatory"] and b["headline_path"]["name"] == "전세보증금 마련"

    facts = briefing_service.facts_text(b)
    monkeypatch.setattr(briefing_service, "_llm_narrative", lambda f: f"월 여유 자금은 {b['monthly_budget']:,}원이에요.")
    assert briefing_service.compose(seeded, 1, use_llm=True)["narrative_source"] == "llm"
    monkeypatch.setattr(briefing_service, "_llm_narrative", lambda f: "월 여유 자금은 9,999,999원이에요.")
    bad = briefing_service.compose(seeded, 1, use_llm=True)
    assert bad["narrative_source"].startswith("template") and "9,999,999" not in bad["narrative"]
    assert briefing_service.validate_numbers("1순위 행동이에요", facts)           # 작은 서수는 허용
    assert not briefing_service.validate_numbers("수익률 7%", facts)


def test_after_sync_runs_monitoring_tracking_and_replan_check(seeded):
    out = pipeline_service.sync_user(seeded, 1, load_user_data(user_dir(1)), use_llm=False)
    assert set(out["planner"]) == {"monitoring_events", "tracked_changes", "replan_proposed"}
    assert seeded.query(MonitoringEvent).filter_by(user_id=1).count() == out["planner"]["monitoring_events"]


def test_facts_text_states_direction_and_mandatory_items(seeded):
    b = briefing_service.compose(seeded, 1)
    facts = briefing_service.facts_text(b)
    assert "필수 '비상금 먼저 채우기'" in facts and "늦어짐" in facts and "-2" not in facts   # 지연을 '단축'으로 쓰지 않는다
    assert "단축" not in facts.split("필수")[1].splitlines()[0]
