"""알림 — 소비가 달라진 점과 받은 알림"""
import streamlit as st

from lib import ui
from lib.api import call, error_text, get_ok, uid
from lib.fmt import short_won

TONE = {"high": ("중요", "bad"), "medium": ("참고", "warn"), "low": ("가볍게 보세요", "gray")}
DELIVERY = {"immediate": "바로 알림", "daily": "하루 요약", "weekly": "주간 요약"}


def render() -> None:
    st.title("🔔 알림")
    ok, ev = get_ok(f"/api/planner/{uid()}/events")
    if not ok:
        ui.empty_state("알림을 보려면 먼저 금융 데이터를 연동해야 해요.", "연동하러 가기", "data")
        return

    ui.section("소비가 달라진 점", "평소보다 많이 늘었거나 줄어든 항목이에요. 한 번만 늘어난 건 '가볍게 보세요'로 알려 드려요.")
    events = ev.get("events", [])
    if not events:
        st.success("평소와 크게 달라진 소비가 없어요. 👍")
    for e in events:
        label, tone = TONE[e["grade"]]
        kind = "계속되는 변화" if e["judgement"] == "structural" else "일시적인 변화"
        with st.container(border=True):
            st.markdown(f'{ui.badge(label, tone)}{ui.badge(kind, "info")} <span class="afpa-muted">{e["month"]}</span>',
                        unsafe_allow_html=True)
            st.write(e["message"])
            st.caption("판단 이유: " + e["reason"])
            if e["event_type"] == "category_increase":
                if st.button("이번 달만 쓴 일회성 지출이에요", key=f"oneoff_{e['id']}",
                             help="평소 소비 계산에서 이 달을 빼요."):
                    status, res = call("POST", f"/api/planner/{uid()}/events/one-off",
                                       json={"category": e["category"], "month": e["month"]})
                    if status == 200:
                        st.rerun()
                    else:
                        st.error(error_text(res))

    st.write("")
    ui.section("받은 알림")
    ok, nt = get_ok(f"/api/planner/{uid()}/notifications")
    notes = nt.get("notifications", []) if ok else []
    if not notes:
        st.caption("받은 알림이 없어요.")
    unread = [n for n in notes if n["status"] == "unread"]
    if unread and st.button(f"모두 읽음으로 표시 ({len(unread)})"):
        for n in unread:
            call("POST", f"/api/planner/{uid()}/notifications/{n['id']}/read")
        st.rerun()
    for n in notes:
        label, tone = TONE[n["grade"]]
        with st.container(border=True):
            dot = "🔵 " if n["status"] == "unread" else ""
            st.markdown(f'{dot}**{ui.esc(n["title"])}** {ui.badge(label, tone)}'
                        f'<span class="afpa-muted">{DELIVERY[n["delivery"]]} · {n["created_on"]}</span>',
                        unsafe_allow_html=True)
            st.write(n["body"])
