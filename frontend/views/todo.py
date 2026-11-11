"""할 일 — 추천받은 일을 해보고, 얼마나 잘 되고 있는지 확인한다"""
import streamlit as st

from lib import ui
from lib.api import call, error_text, get_ok, post_ok, uid
from lib.fmt import effect_text, short_won, ym

REJECT_REASONS = {"already": "이미 하고 있어요", "needed": "꼭 필요한 지출이에요", "burden": "금액이 부담돼요",
                  "later": "나중에 할게요", "other": "그냥 하기 싫어요"}
REJECT_HINT = {"already": "이 제안은 1년 동안 다시 드리지 않아요.", "needed": "이 제안은 1년 동안 다시 드리지 않아요.",
               "burden": "30일 쉬었다가, 다음에는 더 작은 금액으로 제안해 드려요.", "later": "30일 뒤에 다시 알려 드려요.",
               "other": "90일 동안 다시 드리지 않아요."}
STATE_LABEL = {"achieved": ("✅ 잘 지키고 있어요", "good"), "partial": ("🟡 일부 지키고 있어요", "warn"),
               "not_yet": ("⚪ 아직 효과가 없어요", "gray"), "self_reported": ("🙋 직접 완료로 표시했어요", "info"),
               "waiting": ("⏳ 다음 달에 확인해요", "gray")}


def _respond(item_id: int, action: str, reason: str = "", reason_code: str = "") -> None:
    body = {"action": action, "reason": reason or None}
    if reason_code:
        body["reason_code"] = reason_code
    status, res = call("POST", f"/api/planner/{uid()}/items/{item_id}", json=body)
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

    _outcomes()
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
                code = st.radio("이유를 알려 주세요", list(REJECT_REASONS), format_func=REJECT_REASONS.get, key=f"rs_{it['id']}")
                st.caption(REJECT_HINT[code] if not it["mandatory"] else "꼭 필요한 항목이라 계속 보여 드려요.")
                if st.button("확인", key=f"rej_{it['id']}"):
                    _respond(it["id"], "reject", REJECT_REASONS[code], code)

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

    _learned()

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


def _outcomes() -> None:
    """사후 보고 — 실천한 제안이 실제로 얼마나 효과가 있었는지"""
    ok, r = get_ok(f"/api/planner/{uid()}/outcomes")
    if not ok or not r.get("items"):
        return
    with st.container(border=True):
        st.markdown("**📊 지금까지의 성과**")
        st.write(r["headline"])
        if r["items"]:
            with st.expander("제안별 결과 보기"):
                for i in r["items"]:
                    label, tone = STATE_LABEL.get(i["state"], (i["state"], "gray"))
                    amount = f" · 지난달 {short_won(i['actual'])} / 목표 {short_won(i['expected'])}" if i["actual"] is not None else ""
                    st.markdown(f"{ui.badge(label, tone)} **{i['title']}**{amount}", unsafe_allow_html=True)
        st.caption("실제 거래 데이터로 확인한 값이에요. '덕분에 빨라진 기간'은 이 행동이 없었다고 가정한 경로와 비교한 계산이에요.")


def _learned() -> None:
    """거절 학습 — 거절에서 배운 것을 보여 주고, 다시 제안받을 수 있게 한다"""
    ok, prefs = get_ok(f"/api/planner/{uid()}/preferences")
    if not ok or not prefs:
        return
    with st.expander(f"내가 거절해서 달라진 추천 ({len(prefs)})"):
        st.caption("거절한 이유를 기억해 다음 추천에 반영하고 있어요. 마음이 바뀌면 지워서 다시 제안받을 수 있어요.")
        for p in prefs:
            if p["kind"] == "exclude":
                until = f"{p['until']}까지" if p["until"] else "계속"
                text = f"**{p['target']}** 제안을 {until} 쉬어요 — {p['reason']}"
            else:
                text = f"**{p['target']}** 절감 제안을 평소의 {p['value'] * 100:.0f}% 규모로 줄여요 — {p['reason']}"
            cols = st.columns([5, 1.4])
            cols[0].markdown("- " + text)
            if cols[1].button("다시 제안받기", key=f"pref_{p['id']}"):
                status, res = call("DELETE", f"/api/planner/{uid()}/preferences/{p['id']}")
                if status == 200:
                    st.rerun()
                else:
                    st.error(error_text(res))
