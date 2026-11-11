"""이번 달 전망 카드 — 지금 소비 속도로 월말까지 가면 어떻게 되는지 (계산은 백엔드 코드가 한 값)"""
import streamlit as st

from lib import ui
from lib.api import get_ok, uid

RISK = {"ok": ("안전", "good"), "watch": ("주의", "warn"), "danger": ("위험", "bad")}


def _won(v: float) -> str:
    return f"{round(v):,}원"


def _md(iso: str) -> str:
    return f"{int(iso[5:7])}월 {int(iso[8:10])}일"


def card(compact: bool = False) -> None:
    ok, f = get_ok(f"/api/planner/{uid()}/forecast")
    if not ok or f.get("status") != "ok":
        if ok and f.get("note"):
            st.caption(f"이번 달 전망: {f['note']}")
        return
    label, tone = RISK[f["risk"]]
    with st.container(border=True):
        st.markdown(f"**📈 이번 달 전망** " + ui.badge(label, tone), unsafe_allow_html=True)
        if f["risk"] == "danger":
            st.write(f"이 속도로 쓰면 **{_md(f['min_cash_date'])}쯤 현금이 부족**해질 수 있어요 (월중 최저 {_won(f['min_cash'])}).")
        elif f["risk"] == "watch":
            st.write("이번 달은 평소보다 많이 쓰는 속도예요. 조금 신경 쓰면 좋아요.")
        else:
            st.write("지금 속도라면 이번 달은 무리 없이 지나갈 것 같아요.")
        c1, c2, c3 = st.columns(3)
        c1.metric("지금까지 쓴 변동지출", _won(f["spent_so_far"]))
        c2.metric("월말까지 예상", _won(f["projected_variable"]), f"{f['overspend']:+,}원 (평소 대비)", delta_color="inverse")
        c3.metric("월말 예상 잔액", _won(f["end_cash"]))
        for c in f["overspent_categories"]:
            st.caption(f"• {c['category']}: 평소 {_won(c['baseline'])} → 이번 달 예상 {_won(c['projected'])} ({c['over_pct']}% 초과)")
        if not compact and f["upcoming"]:
            with st.expander("앞으로 나갈 돈·들어올 돈"):
                for e in f["upcoming"]:
                    sign = "＋" if e["kind"] == "수입" else "－"
                    st.markdown(f"- {_md(e['date'])} · {e['name']} · {sign}{_won(e['amount'])} ({e['kind']})")
            st.caption(f"{f['days_elapsed']}일 지난 시점({_md(f['as_of'])})까지의 거래로 계산한 전망이에요. 소비를 줄이면 달라져요.")
