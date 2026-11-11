"""AI 에이전트 — ① 변화 감시 에이전트(프로필 변화를 지켜보고 알림) ② AI 플래너 시험판(처음 만든 LLM Planning Agent)

'할 일'의 추천은 계산 결과(경로·효과)를 근거로 하지만, 이 화면의 AI 플래너는 LLM이 사용자 자료를 읽고
금융 전략을 글로 작성해 줍니다. 두 결과는 별개이며, 숫자 검증을 하지 않는 시험판이에요.
"""
import streamlit as st

from lib import ui
from lib.api import call, error_text, get_ok, post_ok, uid
from lib.fmt import short_won
from lib.nav import go

CATEGORY = {"saving": ("💰", "저축"), "spending": ("🛒", "소비"), "card": ("💳", "카드"),
            "loan": ("🏦", "대출"), "invest": ("📈", "투자")}
TOOL_LABEL = {"get_profile_summary": "내 자산·빚·저축률", "get_goals_with_feasibility": "내 목표와 달성 가능성",
              "get_market_products": "예·적금 상품과 금리", "get_spending_alerts": "소비 변화 알림",
              "get_rule_based_suggestions": "규칙 기반 제안"}
MODE_LABEL = {"tool_calling": "AI가 필요한 자료를 직접 골라 조회했어요",
              "prefetched_context": "자료를 먼저 조회해 AI에게 건네 주었어요 (AI 서버가 도구 호출을 지원하지 않아요)"}


def _prototype() -> None:
    st.subheader("🧪 AI 플래너 (시험판)")
    st.write("AI가 내 자산·목표·소비 자료를 읽고 금융 전략을 글로 써 줘요. "
             "**'할 일'의 추천과는 별개**이고, 숫자를 따로 검증하지 않는 시험판이라 참고용으로만 봐 주세요.")

    ok, goals = get_ok(f"/api/goals/{uid()}")
    goal_opts = {None: "전체 (목표를 따로 정하지 않아요)"}
    if ok and isinstance(goals, list):
        goal_opts.update({g["id"]: g["name"] for g in goals})
    goal_id = st.selectbox("어떤 목표를 중심으로 볼까요?", list(goal_opts), format_func=goal_opts.get)

    c1, c2, _ = st.columns([1.3, 2, 2.7])
    ask = c1.button("전략 작성하기", type="primary")
    replan = c2.button("소비 변화 보고 다시 짜기")
    key = f"agent_result_{uid()}"

    if ask:
        with st.spinner("AI가 자료를 읽고 전략을 쓰는 중이에요. 시간이 조금 걸려요..."):
            status, res = call("POST", f"/api/planning/{uid()}/action-plan", params={"goal_id": goal_id} if goal_id else None)
        st.session_state[key] = {"kind": "plan", "status": status, "res": res}
    if replan:
        with st.spinner("소비 변화를 확인하는 중이에요..."):
            status, res = call("POST", f"/api/planning/{uid()}/replan", params={"goal_id": goal_id} if goal_id else None)
        st.session_state[key] = {"kind": "replan", "status": status, "res": res}

    saved = st.session_state.get(key)
    if not saved:
        ui.empty_state("위 버튼을 눌러 AI의 전략을 받아 보세요.")
        return
    if saved["status"] != 200:
        st.error(error_text(saved["res"]))
        return
    plan = saved["res"]
    if plan is None:
        st.success("평소와 달라진 소비가 없어서 계획을 다시 짜지 않았어요. 👍")
        return
    _show(plan)


def _show(plan: dict) -> None:
    by_ai = plan.get("generated_by") == "llm"
    st.markdown(ui.badge("🤖 AI가 작성했어요" if by_ai else "📏 규칙으로 만들었어요", "info" if by_ai else "gray"),
                unsafe_allow_html=True)
    if by_ai:
        mode = MODE_LABEL.get(plan.get("llm_mode") or "", "")
        used = ", ".join(TOOL_LABEL.get(t, t) for t in plan.get("llm_tools_used", []))
        st.caption(f"{mode}" + (f" · 살펴본 자료: {used}" if used else ""))
    elif plan.get("fallback_reason"):
        st.warning("AI를 쓰지 못해 규칙으로 대신 만들었어요.")
        with st.expander("이유 자세히 보기"):
            st.code(plan["fallback_reason"])

    ui.section("실행할 일")
    for a in plan["actions"]:
        icon, label = CATEGORY.get(a["category"], ("•", a["category"]))
        with st.container(border=True):
            st.markdown(f"**{icon} {label}** · {a['action']}")
            st.caption("기대 효과: " + a["expected_effect"])

    ui.section("이렇게 추천한 이유")
    st.write(plan["rationale"])
    st.markdown(f"**예상 결과** · {plan['expected_outcome']}")
    st.caption("이 화면의 내용은 자동 검증을 거치지 않았어요. 정확한 숫자와 효과는 '홈'과 '할 일'을 기준으로 봐 주세요.")


# ===========================================================================
# ① 변화 감시 에이전트
# ===========================================================================
STEP_ICON = {"observe": "👀", "tool": "🔧", "decide": "🧠", "act": "⚡"}
STEP_KIND = {"observe": "관찰", "tool": "조사", "decide": "판단", "act": "행동"}


def _run_view(r: dict) -> None:
    status = r.get("status")
    if status == "baseline":
        st.info("지금 상태를 기준으로 기억해 뒀어요. 이후 돈 상황이 달라지면 알려 드릴게요.")
        return
    if status == "no_new_data":
        st.info("지난번 확인 이후 새 데이터가 없어서 확인할 게 없어요.")
        return
    if status == "no_change":
        st.success("새 데이터를 확인했는데 알릴 만큼 달라진 점은 없었어요. 👍")
        return

    by_ai = r.get("generated_by") == "llm"
    tone = "bad" if r.get("severity") == "important" else "info"
    st.markdown(ui.badge("중요" if tone == "bad" else "참고", tone)
                + ui.badge("🤖 AI가 직접 조사했어요" if by_ai else "📏 규칙으로 정리했어요", "info" if by_ai else "gray"),
                unsafe_allow_html=True)
    ui.hero(r["headline"])
    if not by_ai and r.get("fallback_reason"):
        with st.expander("AI를 쓰지 못한 이유"):
            st.code(r["fallback_reason"])

    with st.expander("에이전트가 한 일 보기", expanded=True):
        for s in r.get("steps", []):
            detail = f" — {s['detail']}" if s.get("detail") else ""
            st.markdown(f"{STEP_ICON.get(s['kind'], '•')} **{STEP_KIND.get(s['kind'], '')}** · {s['title']}{detail}")

    ui.section("달라진 점")
    for f in r.get("findings", []):
        with st.container(border=True):
            st.markdown(f"**{f.get('text') or f.get('message', '')}**")
            st.write(f["meaning"])

    pc = r.get("plan_change", {})
    ui.section("계획을 바꿔야 할까요?")
    if pc.get("needed"):
        with st.container(border=True):
            st.markdown("🔄 **네, 계획 변경이 필요해요.**")
            st.write(pc.get("reason", ""))
            if pc.get("llm_opinion") is False:
                st.caption("AI는 변경이 필요 없다고 봤지만, 계산 결과(계획 이탈 기준)에 따라 '필요'로 확정했어요.")
            for g in pc.get("goals", []):
                if g.get("delay") and g["delay"] != "변화 없음":
                    st.markdown(f"- **{g['goal']}**: {g['planned']} → {g['now']} ({g['delay']})")
            st.caption("새 계획안은 이미 만들어 두었어요. 승인하기 전에는 지금 계획이 그대로 유지돼요.")
            if st.button("새 계획 비교하고 결정하기", type="primary", key="agent_to_todo"):
                go("todo")
    else:
        st.success("아니요, 지금 계획을 유지해도 괜찮아요. " + (pc.get("reason") or ""))

    if r.get("next_step"):
        st.markdown(f"**👉 지금 하면 좋은 일** · {r['next_step']}")

    temp = [e for e in r.get("events", []) if e["judgement"] == "temporary" and e["event_type"] == "category_increase"]
    if r.get("questions") or temp:
        ui.section("에이전트가 궁금해해요", "알려 주시면 다음 판단에 반영돼요")
        for q in r.get("questions", []):
            st.markdown(f"- {q}")
        for e in temp[:3]:
            if st.button(f"'{e['category']}' 지출은 이번 한 번뿐이었어요", key=f"oneoff_{r['id']}_{e['category']}"):
                ok, res = post_ok(f"/api/planner/{uid()}/events/one-off", {"category": e["category"], "month": e["month"]})
                st.toast("일회성으로 표시했어요. 평균 계산에서 빼 둘게요." if ok else error_text(res), icon="✅" if ok else "⚠️")


def _watcher() -> None:
    st.subheader("👀 변화 감시 에이전트")
    st.write("에이전트가 내 금융 프로필을 지켜보다가 **달라진 점이 생기면 알려 주고, 계획을 바꿔야 하는지도 판단**해 줘요. "
             "숫자 계산과 계획 이탈 판정은 코드가 하고, AI는 무엇을 조사할지 정해 도구를 호출하며 변화의 의미를 설명해요.")

    ui.section("① 변화 만들어 보기 (데모)", "실제로는 새 거래가 들어올 때 일어나는 일이에요. 지금은 가상 데이터라 직접 만들어 봐요.")
    ok, kinds = get_ok("/api/agent/demo/kinds")
    if ok:
        c1, c2 = st.columns([3, 1.2])
        kind = c1.selectbox("어떤 변화를 일으켜 볼까요?", list(kinds), format_func=kinds.get, label_visibility="collapsed")
        if c2.button("변화 일으키기", key="agent_demo"):
            status, res = call("POST", f"/api/agent/{uid()}/demo-change", json={"kind": kind})
            if status == 200:
                st.session_state.pop(f"agent_watch_{uid()}", None)
                st.toast("변화를 만들었어요. 이제 에이전트를 실행해 보세요.", icon="✅")
            else:
                st.error(error_text(res))
        st.caption("'내 정보·연동'에서 데이터를 다시 연동하면 원래대로 돌아가요.")

    ui.section("② 에이전트 실행", "데이터를 연동하면 에이전트가 알아서 확인하고, 아래 버튼으로 직접 시킬 수도 있어요.")
    okr, running = get_ok(f"/api/agent/{uid()}/status")
    if okr and running.get("running"):
        st.info("🤖 에이전트가 지금 달라진 점을 확인하는 중이에요. 잠시 후 '지난 기록'이나 이 화면을 새로고침해 주세요.")
    use_ai = st.checkbox("AI가 직접 조사하고 설명하게 하기", value=True, key="agent_use_ai",
                         help="끄면 같은 감지·판정 결과를 정해진 문장으로만 알려 줘요.")
    key = f"agent_watch_{uid()}"
    if st.button("에이전트에게 확인시키기", type="primary", key="agent_run"):
        with st.spinner("에이전트가 달라진 점을 조사하는 중이에요. AI를 쓰면 30초쯤 걸려요..."):
            status, res = call("POST", f"/api/agent/{uid()}/run", params={"use_llm": use_ai})
        st.session_state[key] = {"status": status, "res": res}
    saved = st.session_state.get(key)
    if saved:
        if saved["status"] != 200:
            st.error(error_text(saved["res"]))
        else:
            _run_view(saved["res"])
    else:
        okl, latest = get_ok(f"/api/agent/{uid()}/latest")
        if okl and latest:
            st.caption(f"마지막 확인: {latest['created_at'].replace('T', ' ')}")
            _run_view(latest)
        else:
            ui.empty_state("위 버튼을 눌러 에이전트를 실행해 보세요. 처음에는 지금 상태를 기준으로 기억해 둬요.")

    okh, hist = get_ok(f"/api/agent/{uid()}/runs", limit=8)
    if okh and hist:
        with st.expander("지난 기록"):
            for h in hist:
                label = {"baseline": "기준 저장", "no_change": "변화 없음", "reported": "알림"}.get(h["status"], h["status"])
                st.markdown(f"- {h['created_at'].replace('T', ' ')} · **{label}** · {h.get('headline', '')}")


def render() -> None:
    st.title("🤖 AI 에이전트")
    t1, t2 = st.tabs(["변화 감시 에이전트", "AI 플래너 (시험판)"])
    with t1:
        _watcher()
    with t2:
        _prototype()
