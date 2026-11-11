"""내 돈 현황 — 번 돈·쓴 돈·남는 돈, 금융 건강 점수, 자산과 빚"""
import pandas as pd
import streamlit as st

from lib import ui
from lib.api import ctx, error_text, get_ok, uid
from lib.fmt import health_words, level_words, pct, short_won, won, ym

KIND_LABEL = {"cash": "현금·입출금", "savings": "예·적금", "invest": "투자", "pension": "연금", "other": "기타"}


def render() -> None:
    st.title("💰 내 돈 현황")
    ok, snap = get_ok(f"/api/profile/{uid()}/snapshot")
    if not ok:
        ui.empty_state("아직 분석할 데이터가 없어요. 금융 데이터를 먼저 연동해 주세요.", "연동하러 가기", "data")
        return
    _, ana = get_ok(f"/api/profile/{uid()}/analysis")
    d = snap["details"]
    cf, bs, em, sp = d["cash_flow"], d["balance_sheet"], d["emergency_fund"], d["spending"]

    st.caption(f"{ym(snap['as_of'])} 기준 · 최근 {len(d['window_months'])}개월 평균이에요.")
    for q in d.get("data_quality", []):
        st.warning(q)

    # --- 번 돈 / 쓴 돈 / 남는 돈
    spend = (cf["fixed_expense"] or 0) + (cf["variable_expense"] or 0)
    c1, c2, c3 = st.columns(3)
    with c1:
        ui.stat("매달 들어오는 돈", short_won(cf["monthly_income"]),
                {"정기수입 평균": "월급처럼 꾸준히 들어오는 돈의 평균이에요"}.get(cf["income_basis"], cf["income_basis"]))
    with c2:
        ui.stat("매달 쓰는 돈", short_won(spend),
                f"꼭 나가는 돈 {short_won(cf['fixed_expense'])} + 그때그때 쓰는 돈 {short_won(cf['variable_expense'])}")
    with c3:
        left = cf["net_cash_flow"]
        ui.stat("매달 남는 돈", short_won(left), "목표에 모을 수 있는 돈이에요" if (left or 0) > 0 else "쓰는 돈이 수입보다 많아요",
                "good" if (left or 0) > 0 else "bad")
    st.write("")

    # --- 금융 건강 점수
    health = d["health"]
    score = health.get("score")
    words, tone = health_words(score)
    ui.section("금융 건강 점수", "지금 내 돈 상태가 얼마나 튼튼한지 4가지로 살펴봤어요.")
    left_col, right_col = st.columns([1.2, 3])
    with left_col:
        ui.stat("종합", "-" if score is None else f"{score:.0f}점", words, tone)
    with right_col:
        if not health.get("components"):
            st.info("수입을 알 수 없어서 점수를 계산하지 못했어요.")
        comps = health.get("components", {})
        months_cash = (em["liquid_cash"] / em["monthly_essential_expense"]
                       if em.get("monthly_essential_expense") else None)
        rows = [
            ("saving", "저축·투자 습관",
             f"소득의 {pct(health['metrics'].get('savings_ratio'))}를 저축·투자해요 (권장 30% 이상)"),
            ("debt", "빚 부담", f"소득의 {pct(bs['dsr_ratio'])}를 대출 상환에 써요 (권장 30% 이하)"),
            ("emergency", "비상금",
             f"비상금으로 약 {months_cash:.1f}개월 생활할 수 있어요 (권장 {em['months']}개월)" if months_cash is not None else "-"),
            ("spending", "지출 관리",
             f"소득의 {pct((cf['variable_expense'] or 0) / cf['monthly_income'] * 100 if cf['monthly_income'] else None)}를 "
             f"그때그때 쓰는 데 써요 (권장 50% 이하)"),
        ]
        for key, title, sentence in rows:
            comp = comps.get(key)
            if comp is None:
                continue
            word, t = level_words(comp["ratio"])
            cols = st.columns([1.7, 2.1, 3.4])
            cols[0].markdown(f"**{title}**")
            cols[1].progress(min(max(comp["ratio"], 0), 1.0), text=word)
            cols[2].caption(sentence)
    if em.get("coverage_ratio") is not None and em["coverage_ratio"] < 100:
        st.warning("비상금이 부족해요. 투자나 장기 저축보다 비상금을 먼저 채우는 걸 추천해요.")

    pot = d["potential"]
    if pot.get("score") is not None:
        with st.expander(f"목표를 이룰 수 있는 힘: {pot['score']:.0f}점"):
            st.caption("지금 상태가 아니라 앞으로의 가능성을 봐요. 소득이 낮아도 저축 여력과 시간이 있으면 높게 나올 수 있어요.")
            names = {"velocity": "목표 진행 속도", "surplus": "저축 여력", "income_growth": "소득 성장 가능성", "horizon": "시간 여유"}
            for k, comp in pot["components"].items():
                word, _t = level_words(comp["ratio"])
                cc = st.columns([1.6, 2.4, 3])
                cc[0].markdown(f"**{names.get(k, k)}**")
                cc[1].progress(min(max(comp["ratio"], 0), 1.0), text=word)
            if pot.get("kind") == "basic":
                st.caption("목표가 없어서 '기초 점수'로 계산했어요. 목표를 만들면 더 정확해져요.")

    st.divider()

    # --- 어디에 쓰나요
    left_col, right_col = st.columns(2)
    with left_col:
        ui.section("그때그때 쓰는 돈, 어디에 쓸까요?")
        shares = sp.get("category_share_pct") or {}
        if shares:
            top = pd.Series(shares).head(7)
            st.bar_chart(top.rename("비중(%)"), horizontal=True)
        else:
            st.caption("분류할 소비 내역이 부족해요.")
        if sp.get("outliers"):
            for o in sp["outliers"]:
                st.warning(f"**{o['category']}** 지출이 평소보다 {o['growth_pct']:.0f}% 늘었어요 "
                           f"({short_won(o['baseline'])} → {short_won(o['recent'])})")
    with right_col:
        ui.section("달마다 얼마 벌고 썼나요?")
        if isinstance(ana, dict) and ana.get("monthly"):
            df = pd.DataFrame(ana["monthly"]).set_index("month")
            df["쓴 돈"] = df["fixed"] + df["variable"]
            st.bar_chart(df[["income", "쓴 돈"]].rename(columns={"income": "번 돈"}))
            st.caption("가장 최근 달은 아직 끝나지 않아 일부만 반영돼요.")

    st.divider()

    # --- 자산과 빚
    ui.section("내 자산과 빚")
    a1, a2, a3 = st.columns(3)
    a1.metric("총 자산", short_won(bs["total_assets"]))
    a2.metric("총 빚", short_won(bs["total_debt"]))
    a3.metric("순자산 (자산 − 빚)", short_won(bs["net_worth"]))
    if isinstance(ana, dict) and ana.get("assets"):
        tab1, tab2 = st.tabs(["자산 구성", "자산·빚 목록"])
        with tab1:
            comp = pd.Series({KIND_LABEL.get(k, k): v for k, v in ana["asset_composition"].items()})
            st.bar_chart(comp.rename("금액(원)"), horizontal=True)
        with tab2:
            rows = [{"구분": "자산", "이름": a["name"], "종류": KIND_LABEL.get(a["kind"], a["kind"]), "금액": won(a["amount"])}
                    for a in ana["assets"]]
            rows += [{"구분": "빚", "이름": l["name"], "종류": l["sub"], "금액": won(l["amount"])} for l in ana["liabilities"]]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    with st.expander("전문 지표 자세히 보기"):
        st.dataframe(pd.DataFrame([
            ("소득 대비 대출 상환 비율 (DSR)", pct(bs["dsr_ratio"], 1)),
            ("자산 대비 빚 비율", pct(bs["debt_ratio"], 1)),
            ("소득 대비 소비 비율", pct(sp["consumption_ratio"], 1)),
            ("소득 대비 저축·투자 비율", pct(health["metrics"].get("savings_ratio"), 1)),
            ("비상금 준비율", pct(em["coverage_ratio"], 1)),
            ("필요 비상금", won(em["required"])), ("보유 현금성 자산", won(em["liquid_cash"])),
        ], columns=["지표", "값"]), hide_index=True, width="stretch")

        _, hist = get_ok(f"/api/profile/{uid()}/snapshots")
        if isinstance(hist, dict) and hist.get("snapshots"):
            df = pd.DataFrame(hist["snapshots"]).iloc[::-1]
            df["분석 시각"] = df["calculated_at"].str[:16].str.replace("T", " ")
            st.caption("분석 이력 (동기화·분류 수정·내 정보 변경 때마다 쌓여요)")
            st.dataframe(df[["분석 시각", "health_score", "potential_score", "net_cash_flow"]].rename(columns={
                "health_score": "건강 점수", "potential_score": "목표 달성 힘", "net_cash_flow": "매달 남는 돈"}),
                hide_index=True, width="stretch")
