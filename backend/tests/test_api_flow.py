"""1차 API 흐름: 온보딩 → 동의 → 동기화 → 프로필·분석 → 분류 수정"""
import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.entities import Goal, User


@pytest.fixture()
def client(db):
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    db.add(User(id=1, name="김철수"))
    db.add(Goal(user_id=1, name="전세보증금 마련", goal_type="long_term", target_amount=50_000_000,
                current_amount=14_000_000, priority=1))
    db.commit()
    yield TestClient(app)          # `with` 없이 사용 → startup(init_db) 미실행
    app.dependency_overrides.clear()


ONBOARDING = {
    "birth_date": "1998-03-14", "gender": "MALE", "employment_status": "FULL_TIME",
    "housing_type": "MONTHLY_RENT", "housing_cost_monthly": 550000,
    "location_region": "서울", "location_district": "서초구", "risk_tolerance": "BALANCED",
    "manual_assets": [{"asset_type": "CASH", "name": "현금", "amount": 150000}],
}


def test_full_phase1_flow(client):
    # 1) 온보딩
    r = client.put("/api/onboarding/1", json=ONBOARDING)
    assert r.status_code == 200 and r.json()["manual_assets"][0]["amount"] == 150000

    # 2) 동의 전에는 동기화 불가
    assert client.post("/api/mydata/1/sync", params={"use_llm": False}).status_code == 403
    # 부분 동의는 1차에서 거부
    assert client.post("/api/mydata/1/consent", json={"is_consent_trans_memo": False}).status_code == 422
    assert client.post("/api/mydata/1/consent", json={}).status_code == 200

    # 3) 동기화 → 분류 + 스냅샷
    r = client.post("/api/mydata/1/sync", params={"use_llm": False})
    assert r.status_code == 200 and r.json()["needs_review"] >= 15      # 가게 이름 없는 페이 결제 3건 + 낯선 가게 12건

    # 4) 프로필 스냅샷
    snap = client.get("/api/profile/1/snapshot").json()
    assert snap["monthly_income_net"] == 3_200_000
    assert {"cash_flow", "balance_sheet", "emergency_fund", "spending", "health", "potential"} \
        <= set(snap["details"])
    assert client.get("/api/profile/1/snapshots").json()["snapshots"][0]["snapshot_id"] == snap["snapshot_id"]

    # 5) 수입·지출·자산 분석
    a = client.get("/api/profile/1/analysis").json()
    assert len(a["monthly"]) >= 5 and a["asset_composition"]["cash"] > 0
    assert a["monthly"][0]["income"] == 3_200_000

    # 6) 목표 달성 가능성 (최신 스냅샷의 월 여유 자금 기준)
    goals = client.get("/api/goals/1").json()
    feas = client.get(f"/api/goals/item/{goals[0]['id']}/feasibility").json()
    assert feas["shortfall"] == 36_000_000 and feas["achievable"] is True

    # 7) 분류 확인·수정
    review = client.get("/api/classification/1/review").json()["items"]
    assert review and review[0]["current_category"] == "미분류"
    assert client.get("/api/classification/1/summary").json()["needs_review"] >= 15
    fid = review[0]["flow_ids"][0]
    assert client.put(f"/api/classification/1/flows/{fid}", json={"category": "쇼핑"}).status_code == 200
    assert client.put("/api/classification/1/override",
                      json={"merchant": "스타벅스 역삼점", "category": "없는분류"}).status_code == 422
    assert client.put("/api/classification/1/override",
                      json={"merchant": "스타벅스 역삼점", "category": "식비"}).status_code == 200
    assert len(client.get("/api/profile/1/snapshots").json()["snapshots"]) >= 3


def test_onboarding_rejects_minor_and_missing_rent(client):
    assert client.put("/api/onboarding/1", json={**ONBOARDING, "birth_date": "2015-01-01"}).status_code == 422
    assert client.put("/api/onboarding/1", json={**ONBOARDING, "housing_cost_monthly": None}).status_code == 422
    assert client.put("/api/onboarding/1", json={**ONBOARDING, "employment_status": "STUDENT"}).status_code == 422
    assert client.put("/api/onboarding/99", json=ONBOARDING).status_code == 404


def test_snapshot_before_sync_is_404(client):
    assert client.get("/api/profile/1/snapshot").status_code == 404
    assert client.get("/api/profile/1/analysis").status_code == 404


def test_user_list_for_frontend(client):
    users = client.get("/api/users").json()
    assert users == [{"id": 1, "name": "김철수", "job": None, "persona_type": None, "description": None,
                      "mydata_connected": False, "mydata_last_synced_at": None}]


def _synced(client):
    client.put("/api/onboarding/1", json=ONBOARDING)
    client.post("/api/mydata/1/consent", json={})
    assert client.post("/api/mydata/1/sync", params={"use_llm": False}).status_code == 200


def test_transaction_list_with_filters(client):
    _synced(client)
    allf = client.get("/api/classification/1/flows", params={"limit": 1000}).json()
    assert allf["total"] > 200 and allf["items"][0]["date"] >= allf["items"][-1]["date"]      # 최신순
    first = allf["items"][0]
    assert {"counterparty", "category", "major", "stage", "rule", "source", "needs_review"} <= set(first)

    review = client.get("/api/classification/1/flows", params={"method": "review"}).json()
    assert review["total"] == client.get("/api/classification/1/summary").json()["needs_review"]
    assert all(i["needs_review"] for i in review["items"])
    # 사용자 지정 전에는 AI(LLM)가 분류한 거래가 없다
    assert client.get("/api/classification/1/flows", params={"method": "llm"}).json()["total"] == 0

    q = client.get("/api/classification/1/flows", params={"q": "넷플릭스"}).json()
    assert q["total"] > 0 and all("넷플릭스" in i["counterparty"] for i in q["items"])
    m = client.get("/api/classification/1/flows", params={"month": "2026-07"}).json()
    assert m["total"] > 0 and all(i["date"].startswith("2026-07") for i in m["items"])
    inc = client.get("/api/classification/1/flows", params={"major": "income"}).json()
    assert inc["total"] >= 5 and all(i["direction"] == "in" for i in inc["items"])
    assert client.get("/api/classification/1/flows", params={"month": "7월"}).status_code == 422

    # 사용자가 직접 지정한 거래는 method=user 로 모아 본다
    fid = review["items"][0]["id"]
    client.put(f"/api/classification/1/flows/{fid}", json={"category": "쇼핑"})
    user = client.get("/api/classification/1/flows", params={"method": "user"}).json()
    assert [i["id"] for i in user["items"]] == [fid]


def test_llm_classified_transactions_are_listed(client, monkeypatch):
    """3단계 LLM이 분류한 거래는 method=llm 으로 모아 볼 수 있고 확인 필요로 표시된다"""
    import app.services.pipeline_service as ps
    monkeypatch.setattr(ps, "build_llm_categorizer", lambda: (lambda name: "식비" if "곱창" in name else None))
    client.post("/api/mydata/1/consent", json={})
    assert client.post("/api/mydata/1/sync", params={"use_llm": True}).status_code == 200
    llm = client.get("/api/classification/1/flows", params={"method": "llm"}).json()
    assert llm["total"] == llm["llm_total"] >= 1
    assert all("곱창" in i["counterparty"] and i["category"] == "식비" and i["needs_review"] and i["stage"] == 3
               for i in llm["items"])


def test_prototype_planning_agent_reports_how_it_was_made(client, monkeypatch):
    _synced(client)
    import app.agents.planner as planner_mod
    monkeypatch.setattr(planner_mod, "llm_enabled", lambda: False)
    plan = client.post("/api/planning/1/action-plan").json()
    assert plan["generated_by"] == "rule" and "LLM" in plan["fallback_reason"] and plan["actions"]

    # LLM이 도구 호출을 지원하지 않는 서버(vLLM 기본 실행)여도 사전 조회 방식으로 AI 계획을 만든다
    import json as _json
    import app.llm_client as lc

    class _Msg:
        content = _json.dumps({"actions": [{"category": "saving", "action": "월 30만 원 적금", "expected_effect": "목표 단축"}],
                               "rationale": "근거", "expected_outcome": "1년 뒤 달성"})

    class _Completions:
        def create(self, **kw):
            if "tools" in kw:
                raise RuntimeError('"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser')
            return type("R", (), {"choices": [type("C", (), {"message": _Msg})]})()

    stub = type("Client", (), {"chat": type("Chat", (), {"completions": _Completions()})()})()
    monkeypatch.setattr(planner_mod, "llm_enabled", lambda: True)
    monkeypatch.setattr(lc, "get_llm_client", lambda *a, **k: stub)
    plan = client.post("/api/planning/1/action-plan").json()
    assert plan["generated_by"] == "llm" and plan["llm_mode"] == "prefetched_context"
    assert "get_profile_summary" in plan["llm_tools_used"] and plan["actions"][0]["action"] == "월 30만 원 적금"
