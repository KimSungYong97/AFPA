"""2차 통합 플래너 API 흐름: 브리핑 → 후보 → Action Plan → 응답 → 시나리오 → 알림"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.entities import Goal, User
from app.pipeline.mydata_source import user_dir


@pytest.fixture()
def client(db):
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    meta = json.load(open(user_dir(1) / "_user.json", encoding="utf-8"))
    db.add(User(id=1, name=meta["name"]))
    for g in meta["goals"]:
        db.add(Goal(user_id=1, name=g["name"], goal_type=g["goal_type"], target_amount=g["target_amount"],
                    current_amount=g["current_amount"], priority=g["priority"],
                    target_date=date.fromisoformat(g["target_date"]) if g.get("target_date") else None))
    db.commit()
    c = TestClient(app)
    assert c.post("/api/mydata/1/consent", json={}).status_code == 200
    r = c.post("/api/mydata/1/sync", params={"use_llm": False})
    assert r.status_code == 200 and "planner" in r.json()
    yield c
    app.dependency_overrides.clear()


def test_planner_endpoints_end_to_end(client):
    # 관리자 브리핑: 효과 큰 행동 순위 + 경로 + 안내문
    b = client.get("/api/planner/1/briefing").json()
    assert b["actions"][0]["mandatory"] and b["narrative"] and b["headline_path"]["status"] in ("late", "on_track")
    assert b["has_plan"] is False

    c = client.get("/api/planner/1/candidates").json()
    keys = [x["key"] for x in c["candidates"]]
    assert keys[0] == "emergency" and "cut:쇼핑" in keys
    comb = client.post("/api/planner/1/candidates/combine", json={"selected": ["cut:쇼핑", "cut:문화/여가"]}).json()
    assert comb["total_monthly_saving"] > 0 and comb["combined_months_saved"] >= 1

    # Action Plan 생성 → 수락/거절 → 상태 확인
    plan = client.post("/api/planner/1/plan").json()["active"]
    by_key = {i["key"]: i for i in plan["items"]}
    r = client.post(f"/api/planner/1/items/{by_key['cut:쇼핑']['id']}", json={"action": "accept"})
    assert r.status_code == 200 and r.json()["status"] == "ACCEPTED"
    r = client.post(f"/api/planner/1/items/{by_key['sub:넷플릭스']['id']}", json={"action": "reject", "reason": "사용 중"})
    assert r.json()["status"] == "REJECTED"
    assert client.post(f"/api/planner/1/items/{by_key['cut:쇼핑']['id']}", json={"action": "accept"}).status_code == 422
    assert client.post("/api/planner/1/items/9999", json={"action": "accept"}).status_code == 404
    assert client.post("/api/planner/1/items/1", json={"action": "explode"}).status_code == 422

    # 경로: 기준 + 개선
    path = client.get("/api/planner/1/path").json()
    assert path["improved"] is not None and path["base"]["goals"][0]["name"] == "전세보증금 마련"

    # 시나리오: 정상 / 범위 검증 / 3개 초과
    ok = client.post("/api/planner/1/scenarios", json={"scenarios": [
        {"kind": "save_delta", "delta": 200000}, {"kind": "return", "case": "optimistic"}]})
    assert ok.status_code == 200 and len(ok.json()["scenarios"]) == 2
    assert client.post("/api/planner/1/scenarios", json={"scenarios": [
        {"kind": "expense", "month": 0, "amount": 100}]}).status_code == 422
    assert client.post("/api/planner/1/scenarios", json={"scenarios": [
        {"kind": "save_delta", "delta": 1000}] * 4}).status_code == 422

    # 이행 추적 · 재설계 · 모니터링 · 알림
    t = client.post("/api/planner/1/track").json()
    assert t["deviation"] is None
    assert client.post("/api/planner/1/replan").json()["proposed"] is False
    assert "events" in client.get("/api/planner/1/events").json()
    assert client.post("/api/planner/1/events/one-off", json={"category": "쇼핑", "month": "2026-07"}).status_code == 200
    assert client.post("/api/planner/1/events/one-off", json={"category": "쇼핑", "month": "7월"}).status_code == 422
    assert "notifications" in client.get("/api/planner/1/notifications").json()


def test_planner_requires_synced_profile(db):
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    try:
        db.add(User(id=5, name="신규"))
        db.commit()
        c = TestClient(app)
        for path in ("briefing", "path", "candidates"):
            assert c.get(f"/api/planner/5/{path}").status_code == 404
    finally:
        app.dependency_overrides.clear()
