"""에이전트 평가 러너 — 시나리오(JSON)를 돌려 정해진 기대와 비교한다

두 가지 모음이 있다.
- watch_cases.json : 변화 감시 에이전트. 가상 변화를 주입하고 에이전트를 실행해 상태·계획 변경 판정·재설계 제안·경고 이벤트를 본다.
- chat_cases.json  : 대화 에이전트. 질문이 올바른 도구·인자 호출로 바뀌는지, 위험한 요청(종목 추천·이체·금액 누락)에 안전하게 답하는지 본다.

규칙 경로(LLM 없음)는 pytest(`tests/test_agent_eval.py`)가 매번 돌려 회귀를 막고,
실제 AI는 `python -m evals.run --llm` 으로 돌려 도구 선택률·인자 정확도·근거성을 측정한다.
채점은 전부 코드가 한다(LLM이 채점하지 않는다).
"""
import json
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent import change_agent, chat_agent, demo
from app.db.session import Base
from app.models import entities  # noqa: F401
from app.models.entities import Goal, User
from app.pipeline.mydata_source import load_user_data, user_dir
from app.services import pipeline_service

HERE = Path(__file__).resolve().parent
TOOL_LABEL = {**change_agent.TOOL_LABEL}


def load_cases(name: str) -> List[dict]:
    return json.loads((HERE / f"{name}_cases.json").read_text(encoding="utf-8"))


def new_db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def seed(db: Session, user_id: int) -> None:
    from datetime import date
    meta = json.load(open(user_dir(user_id) / "_user.json", encoding="utf-8"))
    db.add(User(id=user_id, name=meta["name"]))
    for g in meta["goals"]:
        db.add(Goal(user_id=user_id, name=g["name"], goal_type=g["goal_type"], target_amount=g["target_amount"],
                    current_amount=g["current_amount"], priority=g["priority"],
                    target_date=date.fromisoformat(g["target_date"]) if g.get("target_date") else None))
    db.commit()
    pipeline_service.record_consent(db, user_id)
    pipeline_service.sync_user(db, user_id, load_user_data(user_dir(user_id)), use_llm=False)


# ---------------------------------------------------------------------------
# 변화 감시 에이전트
# ---------------------------------------------------------------------------
def _apply(db: Session, uid: int, step: str) -> None:
    if step == "resync":
        pipeline_service.compute_and_store_snapshot(db, uid)       # 같은 데이터를 다시 동기화한 것과 같다
    else:
        demo.simulate_change(db, uid, step)


def run_watch_case(case: dict, use_llm: bool = False) -> dict:
    db = new_db()
    try:
        uid = case["user"]
        seed(db, uid)
        if not case.get("run_first"):
            change_agent.ensure_baseline(db, uid)
        for step in case["setup"]:
            _apply(db, uid, step)
        r = change_agent.run(db, uid, use_llm=use_llm)
        for step in case.get("then", []):
            _apply(db, uid, step)
            r = change_agent.run(db, uid, use_llm=use_llm)
        return {"id": case["id"], "name": case["name"], "result": r, "checks": grade_watch(case["expect"], r, use_llm)}
    finally:
        db.close()


def grade_watch(expect: dict, r: dict, use_llm: bool) -> List[dict]:
    out: List[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        out.append({"name": name, "ok": bool(ok), "detail": detail})

    check("상태", r["status"] == expect["status"], f"기대 {expect['status']} / 실제 {r['status']}")
    if "severity" in expect:
        check("중요도", r.get("severity") == expect["severity"], f"기대 {expect['severity']} / 실제 {r.get('severity')}")
    if "plan_change_needed" in expect:
        check("계획 변경 판단(코드)", r.get("plan_change_needed") == expect["plan_change_needed"],
              f"기대 {expect['plan_change_needed']} / 실제 {r.get('plan_change_needed')}")
    if expect.get("replan"):
        check("새 계획안(승인 대기) 생성", bool(r.get("replan_version_id")))
    for f in expect.get("change_fields", []):
        check(f"변화 감지: {f}", any(c["field"] == f for c in r.get("changes", [])))
    for ev in expect.get("events", []):
        check(f"이벤트: {ev}", any(e["event_type"] == ev for e in r.get("events", [])))
    if use_llm and r["status"] == "reported":
        check("AI 문장이 수치 검증을 통과(근거성)", r.get("generated_by") == "llm", r.get("fallback_reason") or "")
        used = {s["title"] for s in r.get("steps", []) if s["kind"] == "tool"}
        for t in expect.get("tools_if_llm", []):
            check(f"AI가 도구 호출: {t}", TOOL_LABEL.get(t, t) in used, f"호출한 도구 {sorted(used)}")
    return out


# ---------------------------------------------------------------------------
# 대화 에이전트
# ---------------------------------------------------------------------------
def _args_match(want: dict, got: dict) -> List[str]:
    miss = []
    for k, v in want.items():
        if k.endswith("~"):                                         # 부분 일치(문자열)
            key = k[:-1]
            if v not in str(got.get(key, "")):
                miss.append(f"{key}에 '{v}' 포함 기대 / 실제 {got.get(key)!r}")
        elif isinstance(v, (int, float)):
            g = got.get(k)
            if not isinstance(g, (int, float)) or abs(float(g) - float(v)) > 1e-6:
                miss.append(f"{k} 기대 {v} / 실제 {g!r}")
        elif got.get(k) != v:
            miss.append(f"{k} 기대 {v!r} / 실제 {got.get(k)!r}")
    return miss


def grade_chat(expect: dict, r: dict) -> List[dict]:
    out: List[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        out.append({"name": name, "ok": bool(ok), "detail": detail})

    calls = r.get("calls", [])
    names = [c["name"] for c in calls]
    if expect.get("no_tools"):
        check("도구를 부르지 않음", not calls, f"호출한 도구 {names}")
    if "tool" in expect:
        hit = next((c for c in calls if c["name"] == expect["tool"]), None)
        check(f"도구 선택: {expect['tool']}", hit is not None, f"호출한 도구 {names}")
        if hit is not None and expect.get("args"):
            miss = _args_match(expect["args"], hit["args"])
            check("인자 정확도", not miss, "; ".join(miss) or json.dumps(hit["args"], ensure_ascii=False))
        if hit is not None and not expect.get("tool_error_ok"):
            check("도구 결과 정상", "error" not in hit["result"], str(hit["result"].get("error", "")))
        if hit is not None and expect.get("tool_error_ok"):
            check("잘못된 요청은 도구가 거부", "error" in hit["result"], "도구가 거부하지 않았어요")
    for bad in expect.get("answer_not_contains", []):
        check(f"답변에 '{bad}' 없음", bad not in r.get("answer", ""))
    if calls and not expect.get("tool_error_ok"):
        check("답변 수치가 계산 결과에 근거", r.get("source") == "llm", r.get("error") or "")
    return out


def run_chat_case(case: dict, use_llm: bool = True) -> dict:
    db = new_db()
    try:
        uid = case.get("user", 1)
        seed(db, uid)
        r = chat_agent.chat(db, uid, case["q"], use_llm=use_llm)
        return {"id": case["id"], "name": case["q"], "result": r, "checks": grade_chat(case["expect"], r)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 집계
# ---------------------------------------------------------------------------
def summarize(rows: List[dict]) -> dict:
    cases_ok = sum(1 for r in rows if all(c["ok"] for c in r["checks"]))
    checks = [c for r in rows for c in r["checks"]]
    return {"cases": len(rows), "cases_passed": cases_ok, "case_pass_rate": round(cases_ok / len(rows), 3) if rows else None,
            "checks": len(checks), "checks_passed": sum(1 for c in checks if c["ok"])}


def format_report(title: str, rows: List[dict]) -> str:
    lines = [f"## {title}", ""]
    for r in rows:
        ok = all(c["ok"] for c in r["checks"])
        lines.append(f"- {'✅' if ok else '❌'} {r['id']} {r['name']}")
        for c in r["checks"]:
            if not c["ok"]:
                lines.append(f"    - ✗ {c['name']}: {c['detail']}")
    s = summarize(rows)
    lines += ["", f"**{s['cases_passed']}/{s['cases']} 사례 통과 ({(s['case_pass_rate'] or 0) * 100:.0f}%)** · 세부 검사 {s['checks_passed']}/{s['checks']}", ""]
    return "\n".join(lines)
