"""내 목표 — 진행 상황 / 만약에? / 목표 추가"""
from datetime import date

import pandas as pd
import streamlit as st

from lib import ui
from lib.api import call, ctx, error_text, get_ok, uid
from lib.fmt import GOAL_STATUS, goal_sentence, months_text, short_won, won, ym
from lib.nav import go


def render() -> None:
    st.title("🎯 내 목표")
    tab1, tab2, tab3 = st.tabs(["진행 상황", "만약에? 해보기", "목표 추가"])
    with tab1:
        _progress()
    with tab2:
        _what_if()
    with tab3:
        _add()


# ---------------------------------------------------------------------------
def _progress() -> None:
    ok_g, goals = get_ok(f"/api/goals/{uid()}")
    if not ok_g or not goals:
        ui.empty_state("아직 목표가 없어요. '목표 추가' 탭에서 만들어 보세요.")
        return
    ok, path = get_ok(f"/api/planner/{uid()}/path")
    if not ok:
        ui.empty_state("목표가 언제 이루어질지 계산하려면 먼저 금융 데이터를 연동해야 해요.", "연동하러 가기", "data")
        for g in goals:
            st.markdown(f"- **{g['name']}**: {short_won(g['current_amount'])} / {short_won(g['target_amount'])}")
        return

    by_name = {g["name"]: g for g in path["base"]["goals"]}
    st.caption(f"{ym(path['as_of'])} 기준 · 지금처럼 매달 {short_won(path['monthly_budget'])}씩 모은다고 가정했어요.")
    for g in goals:
        p = by_name.get(g["name"])
        label, tone = GOAL_STATUS[p["status"]] if p else ("-", "gray")
        with st.container(border=True):
            head = st.columns([4, 2])
            head[0].markdown(f"#### {g['name']}")
            head[1].markdown(ui.badge(label, tone), unsafe_allow_html=True)
            pct = min(g["current_amount"] / g["target_amount"], 1.0) if g["target_amount"] else 0
            st.progress(pct, text=f"{short_won(g['current_amount'])} 모았어요 · 목표 {short_won(g['target_amount'])}")
            if p:
                st.write(goal_sentence(p))
                m1, m2, m3 = st.columns(3)
                m1.metric("앞으로 더 모아야 할 돈", short_won(max(g["target_amount"] - g["current_amount"], 0)))
                m2.metric("기한을 지키려면 매달", short_won(p["required_monthly"]) if p["required_monthly"] else "-",
                          help="목표일까지 남은 기간으로 나눈 금액이에요.")
                m3.metric("지금 매달 모으는 돈", short_won(p["first_month_alloc"]),
                          help="매달 남는 돈을 중요한 목표부터 나눠 담은 금액이에요.")
            with st.expander("관리"):
                sure = st.checkbox("정말 삭제할래요", key=f"sure_{g['id']}")
                if st.button("이 목표 삭제", key=f"del_{g['id']}", disabled=not sure):
                    call("DELETE", f"/api/goals/item/{g['id']}")
                    st.rerun()

    st.write("")
    ui.section("목표가 모이는 모습", "목표별로 쌓이는 금액을 월별로 보여 드려요.")
    rows = [{"날짜": s["date"], **s["balances"]} for s in path["base"]["series"]]
    st.line_chart(pd.DataFrame(rows).set_index("날짜"))


# ---------------------------------------------------------------------------
def _what_if() -> None:
    ok, path = get_ok(f"/api/planner/{uid()}/path")
    if not ok:
        ui.empty_state("시뮬레이션을 하려면 먼저 금융 데이터를 연동해야 해요.", "연동하러 가기", "data")
        return
    goals = path["base"]["goals"]
    head = next((g for g in goals if g["status"] != "done"), None)
    st.write("궁금한 상황을 골라 보세요. 지금 계획과 비교해서 목표가 얼마나 달라지는지 알려 드려요.")

    presets = {
        "save10": ("매달 10만 원 더 저축하면", {"kind": "save_delta", "delta": 100_000}),
        "save30": ("매달 30만 원 더 저축하면", {"kind": "save_delta", "delta": 300_000}),
        "trip": ("3개월 뒤 300만 원을 한 번에 쓰면", {"kind": "expense", "month": 3, "amount": 3_000_000}),
        "raise": ("월급이 50만 원 오르면", {"kind": "income", "delta": 500_000}),
        "opt": ("투자 수익이 좋으면 (연 4%)", {"kind": "return", "case": "optimistic"}),
    }
    if head:
        presets["delay"] = (f"'{head['name']}' 목표를 1년 미루면",
                            {"kind": "goal", "goal": head["name"], "shift_months": 12})
    chosen = st.multiselect("상황 (최대 3개)", list(presets), format_func=lambda k: presets[k][0],
                            default=["save10"], max_selections=3)
    specs = [dict(presets[k][1], label=presets[k][0]) for k in chosen]

    with st.expander("직접 입력해서 해보기"):
        kind = st.selectbox("종류", ["사용 안 함", "매달 저축 늘리기/줄이기", "한 번에 큰돈 쓰기", "월급 변화"], key="wi_kind")
        if kind == "매달 저축 늘리기/줄이기":
            d = st.number_input("매달 늘리는 금액 (줄이려면 음수)", value=50_000, step=10_000, key="wi_d1")
            specs.append({"kind": "save_delta", "delta": d, "label": f"매달 저축 {d:+,.0f}원"})
        elif kind == "한 번에 큰돈 쓰기":
            m = st.number_input("몇 개월 뒤에", 1, 120, 6, key="wi_m")
            a = st.number_input("얼마를 쓰나요 (원)", value=2_000_000, step=100_000, key="wi_a")
            specs.append({"kind": "expense", "month": int(m), "amount": a, "label": f"{int(m)}개월 뒤 {short_won(a)} 사용"})
        elif kind == "월급 변화":
            d = st.number_input("월급이 바뀌는 금액 (줄면 음수)", value=300_000, step=50_000, key="wi_d2")
            specs.append({"kind": "income", "delta": d, "label": f"월급 {d:+,.0f}원"})

    if len(specs) > 3:
        st.warning("한 번에 3개까지만 비교할 수 있어요. 일부를 빼 주세요.")
        return
    if not st.button("결과 보기", type="primary", disabled=not specs):
        return
    status, res = call("POST", f"/api/planner/{uid()}/scenarios", json={"scenarios": specs})
    if status != 200:
        st.error(error_text(res))
        return

    for sc in res["scenarios"]:
        with st.container(border=True):
            st.markdown(f"#### {sc['label']}")
            for e in sc["effects"]:
                st.markdown(_effect_line(e))
            if sc["net_worth_diff"] is not None and abs(sc["net_worth_diff"]) >= 1000:
                more = sc["net_worth_diff"] > 0
                st.caption(f"5년 뒤 내 자산은 지금 계획보다 {short_won(abs(sc['net_worth_diff']))} "
                           f"{'더 많아져요' if more else '더 적어져요'}.")
    comp = pd.DataFrame({"지금 계획": pd.DataFrame(res["base"]["series"]).set_index("date")["net_worth"]})
    for sc in res["scenarios"]:
        comp[sc["label"]] = pd.DataFrame(sc["series"]).set_index("date")["net_worth"]
    st.caption("내 자산이 늘어나는 모습 (원)")
    st.line_chart(comp)


def _effect_line(e: dict) -> str:
    name = e["goal"]
    if e["becomes_unreachable"]:
        return f"- ⚠️ **{name}**: 달성하기 어려워져요"
    if e["makes_reachable"]:
        return f"- 🎉 **{name}**: 달성할 수 있게 돼요 ({ym(e['new_completion'])})"
    ms = e["months_saved"]
    if ms is None:
        return f"- **{name}**: 변화가 없어요 (계속 달성하기 어려워요)"
    if ms > 0:
        return f"- ✅ **{name}**: {months_text(ms)} 빨라져요 ({ym(e['base_completion'])} → {ym(e['new_completion'])})"
    if ms < 0:
        return f"- ⚠️ **{name}**: {months_text(ms)} 늦어져요 ({ym(e['base_completion'])} → {ym(e['new_completion'])})"
    return f"- **{name}**: 달라지지 않아요"


# ---------------------------------------------------------------------------
def _add() -> None:
    _, goals = get_ok(f"/api/goals/{uid()}")
    n = len(goals) if isinstance(goals, list) else 0
    with st.form("goal_form", clear_on_submit=True):
        name = st.text_input("목표 이름", placeholder="예: 전세보증금 마련, 일본 여행")
        gtype = st.radio("어떤 목표인가요?", ["long_term", "life_event"], horizontal=True,
                         format_func=lambda x: "크게 모으는 목표 (집·결혼·은퇴)" if x == "long_term" else "한 번 쓰는 큰 지출 (여행·차량·가전)")
        c1, c2 = st.columns(2)
        target = c1.number_input("필요한 돈 (원)", min_value=0, step=1_000_000)
        current = c2.number_input("지금까지 모은 돈 (원)", min_value=0, step=100_000)
        has_date = st.checkbox("정해진 기한이 있어요", value=True)
        tdate = st.date_input("목표일", value=date(date.today().year + 3, 12, 31))
        prio = st.selectbox("얼마나 중요한가요?", list(range(1, n + 2)),
                            format_func=lambda i: "가장 중요 (1순위)" if i == 1 else f"{i}순위", index=min(n, n))
        if st.form_submit_button("목표 추가", type="primary"):
            if not name or target <= 0:
                st.error("목표 이름과 필요한 돈을 입력해 주세요.")
            else:
                status, res = call("POST", f"/api/goals/{uid()}", json={
                    "name": name, "goal_type": gtype, "target_amount": target, "current_amount": current,
                    "target_date": tdate.isoformat() if has_date else None, "priority": int(prio)})
                if status == 200:
                    st.toast("목표를 추가했어요!", icon="🎯")
                    st.rerun()
                else:
                    st.error(error_text(res))
    st.caption("새 목표는 다음에 금융 데이터를 동기화하면 점수에도 반영돼요.")
