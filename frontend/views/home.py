"""홈 — 한 화면에서 '지금 내 상황'과 '지금 하면 좋은 일'만 보여 준다"""
import streamlit as st

from lib import forecast, ui
from lib.api import call, ctx, error_text, get_ok, post_ok, uid
from lib.fmt import GOAL_STATUS, effect_text, friendly_summary, goal_gap_text, goal_sentence, health_words, short_won, ym
from lib.nav import go


def adopt(key: str) -> None:
    """추천을 '해볼게요'로 받아들인다 — Action Plan이 없으면 먼저 만든다"""
    ok, plan = post_ok(f"/api/planner/{uid()}/plan")
    if not ok:
        st.error(error_text(plan))
        return
    item = next((i for i in plan["active"]["items"] if i["key"] == key), None)
    if item is None:
        st.error("이 추천을 찾지 못했어요. 새로고침 후 다시 시도해 주세요.")
        return
    status, res = call("POST", f"/api/planner/{uid()}/items/{item['id']}", json={"action": "accept"})
    if status == 200:
        st.toast("좋아요! '할 일'에서 진행 상황을 확인할 수 있어요.", icon="✅")
        st.rerun()
    else:
        st.error(error_text(res))


def _setup_guide(user: dict) -> None:
    """처음 쓰는 사람을 위한 3단계 안내"""
    st.info("처음이시네요! 아래 3단계만 하면 내 돈 상황을 분석해 드려요.")
    ok_onb, _ = get_ok(f"/api/onboarding/{uid()}")
    ok_goal, goals = get_ok(f"/api/goals/{uid()}")
    steps = [
        ("1", "내 정보 입력", "나이·직업·거주 형태처럼 금융 데이터로는 알 수 없는 정보만 받아요.", ok_onb),
        ("2", "금융 데이터 연동", "은행·카드·증권 데이터를 불러와 자동으로 정리해 드려요.", user["mydata_connected"]),
        ("3", "목표 정하기", "집 마련, 결혼, 여행 등 모으고 싶은 목표를 알려 주세요.", ok_goal and bool(goals)),
    ]
    for n, title, desc, done in steps:
        st.markdown(f'<div class="afpa-step">{"✅" if done else "⬜"} <b>{n}. {title}</b>'
                    f'<div class="afpa-muted">{desc}</div></div>', unsafe_allow_html=True)
    if st.button("시작하기", type="primary"):
        go("data" if not (ok_onb and user["mydata_connected"]) else "goals")


def render() -> None:
    c = ctx()
    user = c["user"]
    st.title(f"안녕하세요, {user['name']}님 👋")

    if not user["mydata_connected"]:
        _setup_guide(user)
        return

    ok, b = get_ok(f"/api/planner/{uid()}/briefing", use_llm=c["use_llm"])
    if not ok:
        st.error(error_text(b))
        return
    _, snap = get_ok(f"/api/profile/{uid()}/snapshot")

    ui.hero(b["narrative"] if b["narrative_source"] == "llm" else friendly_summary(b))
    st.caption(f"{ym(b['as_of'])} 기준 · 모든 숫자는 계산으로 구한 값이에요"
               + (" · 요약 문장은 AI가 다듬었어요" if b["narrative_source"] == "llm" else ""))
    st.write("")

    # --- 이번 달 전망 (월중 현금 전망)
    forecast.card(compact=True)

    # --- 변화 감시 에이전트의 최신 보고
    okl, latest = get_ok(f"/api/agent/{uid()}/latest")
    if okl and latest and latest["status"] == "reported":
        with st.container(border=True):
            cols = st.columns([5, 1.4])
            cols[0].markdown(f"🤖 **에이전트가 알려요** · {latest['headline']}"
                             + (" 계획을 바꿔야 한다고 판단했어요." if latest.get("plan_change_needed") else ""))
            if cols[1].button("자세히 보기", key="home_agent"):
                go("agent")

    # --- 알림 배너
    if b["pending_replan"]:
        with st.container(border=True):
            cols = st.columns([5, 1.4])
            cols[0].markdown("🔔 **계획을 다시 짜 보자는 제안이 있어요.** 확인하고 승인하면 적용돼요.")
            if cols[1].button("확인하기", key="home_replan"):
                go("todo")

    # --- 핵심 카드 3개
    c1, c2, c3 = st.columns(3)
    with c1:
        budget = b["monthly_budget"]
        ui.stat("매달 남는 돈", short_won(budget),
                "수입에서 고정·변동 지출을 뺀 평균이에요" if budget >= 0 else "매달 쓰는 돈이 수입보다 많아요",
                "good" if budget > 0 else "bad")
    with c2:
        hp = b["headline_path"]
        if hp:
            label, tone = GOAL_STATUS[hp["status"]]
            ui.stat(f"가장 중요한 목표 · {hp['name']}", ym(hp["completion_date"]) if hp["completion_date"] else "달성 어려움",
                    goal_gap_text(hp), tone, label)
        else:
            ui.stat("가장 중요한 목표", "-", "목표를 추가해 보세요")
    with c3:
        score = snap.get("health_score") if isinstance(snap, dict) else None
        words, tone = health_words(score)
        ui.stat("금융 건강 점수", "-" if score is None else f"{score:.0f}점", words, tone)

    st.write("")

    # --- 지금 하면 좋은 일
    ui.section("지금 하면 좋은 일", "목표를 얼마나 빨리 이룰 수 있는지(효과)를 기준으로 골랐어요.")
    hidden = st.session_state.setdefault("hidden_actions", set())
    shown = [a for a in b["actions"] if a["key"] not in hidden][:3]
    if not shown:
        st.success("지금 추천할 일이 없어요. 잘하고 계세요! 👏")
    for i, a in enumerate(shown, 1):
        with st.container(border=True):
            left, right = st.columns([5, 1.6])
            sentence, tone = effect_text(a["path_effect"], a["mandatory"])
            tag = ui.badge("먼저 해야 해요", "warn") if a["mandatory"] else ""
            left.markdown(
                f'<span class="afpa-num">{i}</span><span class="afpa-title">{ui.esc(a["title"])}</span><br>'
                f'{tag}{ui.badge(sentence, tone)}'
                + (f'<span class="afpa-muted">매달 {short_won(abs(a["monthly_saving"]))}</span>' if a["monthly_saving"] else ""),
                unsafe_allow_html=True)
            left.caption(a["description"])
            if a["key"] == "deficit":
                if right.button("알겠어요", key=f"ok_{a['key']}"):
                    hidden.add(a["key"])
                    st.rerun()
            else:
                if right.button("해볼게요", key=f"adopt_{a['key']}", type="primary"):
                    adopt(a["key"])
                if right.button("다음에", key=f"later_{a['key']}"):
                    hidden.add(a["key"])
                    st.rerun()
            if a["conflicts_with"]:
                left.caption("⚠️ 같은 지출을 줄이는 다른 방법과는 함께 하기 어려워요.")
            with left.expander("왜 추천하나요?"):
                st.write(a["rationale"])

    # --- 내 목표 한눈에
    st.write("")
    ui.section("내 목표 한눈에")
    if not b["goals"]:
        ui.empty_state("아직 목표가 없어요.", "목표 추가하기", "goals")
    for g in b["goals"]:
        label, tone = GOAL_STATUS[g["status"]]
        with st.container(border=True):
            top = st.columns([4, 2])
            top[0].markdown(f"**{g['name']}**")
            top[1].markdown(ui.badge(label, tone), unsafe_allow_html=True)
            pct = min(g["start_amount"] / g["target_amount"], 1.0) if g["target_amount"] else 0
            st.progress(pct, text=f"{short_won(g['start_amount'])} / {short_won(g['target_amount'])}")
            st.caption(goal_sentence(g))

    if b["events"]:
        st.write("")
        e = b["events"][0]
        st.markdown(f"💡 **소비 변화** · {e['message']}")
