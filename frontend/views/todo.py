"""할 일 — 추천받은 일을 해보고, 얼마나 잘 되고 있는지 확인한다"""
import streamlit as st

from lib import ui
from lib.api import call, error_text, get_ok, post_ok, uid
from lib.fmt import effect_text, short_won, ym

REJECT_REASONS = ["이미 하고 있어요", "필요 없는 지출이에요", "지금은 어려워요", "그냥 하기 싫어요"]


def _respond(item_id: int, action: str, reason: str = "") -> None:
    status, res = call("POST", f"/api/planner/{uid()}/items/{item_id}", json={"action": action, "reason": reason or None})
    if status == 200:
        st.rerun()
    else:
        st.error(error_text(res))


def render() -> None:
    st.title("✅ 할 일")
    ok, plan = get_ok(f"/api/planner/{uid()}/plan")
    if not ok:
        st.error(error_text(plan))
        return

    if plan["pending"]:
        _replan_card(plan["pending"])

    act = plan["active"]
    if act is None:
        ui.empty_state("아직 할 일 목록이 없어요. 추천받은 일을 목록으로 만들어 드릴게요.")
        if st.button("추천 할 일 만들기", type="primary"):
            ok, res = post_ok(f"/api/planner/{uid()}/plan")
            if ok:
                st.rerun()
            else:
                st.error(error_text(res))
        return

    items = act["items"]
    by = lambda s: [i for i in items if i["status"] == s]
    done_saving = sum(i["monthly_saving"] for i in by("DONE") if i["monthly_saving"] > 0)

    c1, c2, c3 = st.columns(3)
    c1.metric("해볼 일", f"{len(by('PROPOSED'))}개")
    c2.metric("하는 중", f"{len(by('ACCEPTED'))}개")
    c3.metric("끝낸 일로 아끼는 돈", f"매달 {short_won(done_saving)}" if done_saving else "-")
    st.caption(f"{ym(act['as_of'])}에 만든 계획 (버전 {act['version']})")

    # --- 해볼 일
    proposed = by("PROPOSED")
    ui.section("해볼 일")
    if not proposed:
        st.caption("지금 제안할 일이 없어요.")
    for it in proposed:
        with st.container(border=True):
            sentence, tone = effect_text(it["path_effect"], it["mandatory"])
            head = st.columns([5, 2.2])
            tag = ui.badge("먼저 해야 해요", "warn") if it["mandatory"] else ""
            head[0].markdown(f'<span class="afpa-title">{ui.esc(it["title"])}</span><br>{tag}{ui.badge(sentence, tone)}',
                             unsafe_allow_html=True)
            head[0].caption(it["description"])
            with head[0].expander("왜 추천하나요?"):
                st.write(it["rationale"])
            if it["key"] == "deficit":
                if head[1].button("확인했어요", key=f"ack_{it['id']}"):
                    _respond(it["id"], "reject", "확인함")
                continue
            if head[1].button("해볼게요", key=f"acc_{it['id']}", type="primary"):
                _respond(it["id"], "accept")
            with head[1].popover("안 할래요"):
                reason = st.radio("이유를 알려 주세요", REJECT_REASONS, key=f"rs_{it['id']}")
                st.caption("알려 주신 이유는 다음 추천에 참고해요.")
                if st.button("확인", key=f"rej_{it['id']}"):
                    _respond(it["id"], "reject", reason)

    # --- 하는 중
    doing = by("ACCEPTED")
    if doing:
        ui.section("하는 중", "마이데이터로 잘 지키고 있는지 자동으로 확인해요.")
    for it in doing:
        with st.container(border=True):
            st.markdown(f'<span class="afpa-title">{ui.esc(it["title"])}</span>', unsafe_allow_html=True)
            prog = it["progress"]
            if prog.get("ratio") is not None:
                r = min(max(prog["ratio"], 0), 1.0)
                st.progress(r, text=f"{r * 100:.0f}% 지키고 있어요")
                if prog.get("saved") is not None:
                    st.caption(f"{prog.get('month', '')}에 평소보다 {short_won(prog['saved'])} 줄였어요.")
            else:
                st.caption("⏳ " + (prog.get("note") or "곧 확인해 드려요."))
            if it["tracked_by"] == "user":
                if st.button("했어요! 완료 체크", key=f"done_{it['id']}"):
                    _respond(it["id"], "done")
            else:
                st.caption("🤖 다음 달 데이터가 들어오면 자동으로 확인해요.")

    # --- 끝낸 일
    done = by("DONE")
    if done:
        ui.section("끝낸 일 🎉")
        for it in done:
            st.markdown(f"- ✅ **{it['title']}** · 매달 {short_won(abs(it['monthly_saving']))}")

    # --- 안 하기로 한 일
    rest = by("REJECTED") + by("EXPIRED")
    if rest:
        with st.expander(f"안 하기로 했거나 기간이 지난 일 ({len(rest)})"):
            for it in rest:
                why = f" — {it['reject_reason']}" if it["reject_reason"] else " — 기간이 지났어요"
                st.markdown(f"- {it['title']}{why}")

    st.divider()
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("추천 새로고침"):
        post_ok(f"/api/planner/{uid()}/plan")
        st.rerun()
    if c2.button("지금 상황 점검"):
        status, res = call("POST", f"/api/planner/{uid()}/track")
        if status == 200:
            if res["deviation"]:
                st.warning("계획과 달라진 점이 있어요: " + res["deviation"]["message"])
            else:
                st.success("계획대로 잘 진행되고 있어요.")
            if res["changes"]:
                st.rerun()


def _replan_card(pend: dict) -> None:
    cmp_ = pend["comparison"]
    with st.container(border=True):
        st.subheader("🔔 계획을 다시 짜 볼까요?")
        st.write(cmp_["message"] + ".")
        st.caption("승인하기 전까지는 기존 계획이 그대로 유지돼요.")
        st.markdown(f"**매달 남는 돈**: {short_won(cmp_['budget_before'])} → **{short_won(cmp_['budget_after'])}**")
        for g in cmp_["goals"]:
            st.markdown(f"- **{g['name']}**: {ym(g['before'])} → **{ym(g['after']) if g['after'] else '달성 어려움'}**")
        if pend["items"]:
            st.write("새로 추천하는 일")
            for it in pend["items"][:4]:
                sentence, _ = effect_text(it["path_effect"], it["mandatory"])
                st.markdown(f"- {it['title']} · {sentence}")
        c1, c2 = st.columns(2)
        if c1.button("좋아요, 적용할게요", type="primary", key="pend_ok"):
            status, res = call("POST", f"/api/planner/{uid()}/plans/{pend['id']}/decision", json={"approve": True})
            if status == 200:
                st.rerun()
            else:
                st.error(error_text(res))
        if c2.button("지금은 괜찮아요", key="pend_no", help="같은 이유로는 30일 동안 다시 묻지 않아요."):
            status, res = call("POST", f"/api/planner/{uid()}/plans/{pend['id']}/decision", json={"approve": False})
            if status == 200:
                st.rerun()
            else:
                st.error(error_text(res))
