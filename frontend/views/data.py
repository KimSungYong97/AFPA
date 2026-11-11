"""내 정보·연동 — ① 내 정보 ② 금융 데이터 연동 ③ 분류 확인"""
from datetime import date

import pandas as pd
import streamlit as st

from lib import ui
from lib.api import call, ctx, error_text, get_ok, uid
from lib.fmt import short_won, won

EMP = {"FULL_TIME": "회사원(정규직)", "FREELANCER": "프리랜서", "SELF_EMPLOYED": "자영업", "UNEMPLOYED": "무직·학생"}
HOUSING = {"OWNED": "자가", "JEONSE": "전세", "MONTHLY_RENT": "월세"}
RISK = {"CONSERVATIVE": "안정형 (손실이 싫어요)", "BALANCED": "중립형", "AGGRESSIVE": "공격형 (수익을 더 원해요)"}
ASSET_TYPE = {"CASH": "집·지갑에 둔 현금", "GOLD": "금 (실물)", "OTHER": "기타 자산"}
STAGE_TEXT = {0: "가게 이름이 없었어요", 1: "이미 아는 가게였어요", 2: "이름으로 종류를 짐작했어요",
              3: "AI가 추정했어요", 4: "자동으로 알 수 없었어요"}


def render() -> None:
    st.title("⚙️ 내 정보·연동")
    tab1, tab2, tab3, tab4 = st.tabs(["① 내 정보", "② 금융 데이터 연동", "③ 분류 확인", "④ 거래 내역"])
    with tab1:
        _profile()
    with tab2:
        _connect()
    with tab3:
        _review()
    with tab4:
        _transactions()


# ---------------------------------------------------------------------------
def _profile() -> None:
    st.caption("금융 데이터로는 알 수 없는 정보만 받아요. 월급·지출·잔액은 직접 입력하지 않아도 돼요.")
    ok, cur = get_ok(f"/api/onboarding/{uid()}")
    cur = cur if ok else {}

    c1, c2 = st.columns(2)
    birth = c1.date_input("생년월일", value=date.fromisoformat(cur["birth_date"]) if cur.get("birth_date") else date(1995, 1, 1),
                          min_value=date(1930, 1, 1), max_value=date.today(), help="만 19세 이상부터 이용할 수 있어요.")
    emp_keys = list(EMP)
    emp = c2.selectbox("하는 일", emp_keys, format_func=EMP.get, index=emp_keys.index(cur.get("employment_status", "FULL_TIME")))
    house_keys = list(HOUSING)
    housing = c1.selectbox("사는 곳 형태", house_keys, format_func=HOUSING.get,
                           index=house_keys.index(cur["housing_type"]) if cur.get("housing_type") in house_keys else 1)
    rent = c2.number_input("월세 (원)", min_value=0, step=10_000, value=int(cur.get("housing_cost_monthly") or 0),
                           disabled=housing != "MONTHLY_RENT", help="월세로 사는 경우에만 입력해요.")
    region = c1.text_input("사는 지역 (시/도)", value=cur.get("location_region") or "서울")
    district = c2.text_input("사는 지역 (구/군)", value=cur.get("location_district") or "")
    with st.expander("투자 성향 · 성별 (선택)"):
        risk_keys = list(RISK)
        risk = st.selectbox("투자 성향", risk_keys, format_func=RISK.get, index=risk_keys.index(cur.get("risk_tolerance", "BALANCED")),
                            help="입력하지 않으면 중립형으로 가정해요.")
        genders = [None, "MALE", "FEMALE", "OTHER"]
        gender = st.selectbox("성별", genders, index=genders.index(cur.get("gender")) if cur.get("gender") in genders else 0,
                              format_func=lambda g: {"MALE": "남성", "FEMALE": "여성", "OTHER": "기타"}.get(g, "입력 안 함"))
    st.markdown("**금융 데이터에 없는 자산**")
    st.caption("집에 둔 현금이나 금처럼 은행·증권사에서 가져올 수 없는 자산이에요. 비상금 계산에는 포함하지 않아요.")
    existing = cur.get("manual_assets") or []
    rows = [{"종류": ASSET_TYPE.get(a["asset_type"], a["asset_type"]), "이름": a.get("name") or "", "금액(원)": a["amount"]}
            for a in existing] or [{"종류": ASSET_TYPE["CASH"], "이름": "", "금액(원)": 0}]
    edited = st.data_editor(pd.DataFrame(rows), num_rows="dynamic", width="stretch", key=f"manual_{uid()}", column_config={
        "종류": st.column_config.SelectboxColumn("종류", options=list(ASSET_TYPE.values()), required=True),
        "이름": st.column_config.TextColumn("이름"),
        "금액(원)": st.column_config.NumberColumn("금액(원)", min_value=0, step=10_000, required=True)})
    type_by_label = {v: k for k, v in ASSET_TYPE.items()}

    if st.button("저장하기", type="primary"):
        body = {
            "birth_date": birth.isoformat(), "gender": gender, "employment_status": emp, "housing_type": housing,
            "housing_cost_monthly": float(rent) if housing == "MONTHLY_RENT" and rent else None,
            "location_region": region, "location_district": district, "risk_tolerance": risk,
            "manual_assets": [{"asset_type": type_by_label[r["종류"]], "name": r["이름"] or None, "amount": float(r["금액(원)"])}
                              for r in edited.to_dict("records") if r.get("금액(원)") and r["금액(원)"] > 0]}
        status, res = call("PUT", f"/api/onboarding/{uid()}", json=body)
        if status == 200:
            st.toast("저장했어요. 분석 결과도 새로 계산했어요.", icon="✅")
        else:
            st.error(error_text(res))


# ---------------------------------------------------------------------------
def _connect() -> None:
    user = ctx()["user"]
    if user["mydata_connected"]:
        st.success(f"연동되어 있어요 · 마지막 동기화 {(user['mydata_last_synced_at'] or '')[:16].replace('T', ' ')}")
    st.write("은행·카드·증권 데이터를 불러와서 수입·지출·자산을 자동으로 정리해 드려요.")
    st.caption("지금은 연습용 가상 데이터를 사용해요.")
    with st.expander("어떤 정보를 가져오나요?"):
        st.markdown("- 가게 이름·사업자번호\n- 통장 거래 메모\n- 결제 상품 분류\n\n"
                    "이 정보로 지출을 식비·교통·쇼핑 등으로 자동 분류해요. 이름·계좌번호 같은 개인 식별 정보는 AI에 보내지 않아요.")
    agree = st.checkbox("위 정보를 가져와 분석하는 데 동의해요")
    with st.expander("고급 설정"):
        use_llm = st.checkbox("가게 종류를 AI로도 추정하기", value=False,
                              help="이름만으로 종류를 알 수 없는 가게를 AI가 추정해요. 가게 이름만 전달돼요.")
    if st.button("연동하고 분석하기" if not user["mydata_connected"] else "다시 불러오기", type="primary", disabled=not agree):
        status, res = call("POST", f"/api/mydata/{uid()}/consent",
                           json={"is_consent_merchant_name_regno": True, "is_consent_trans_memo": True,
                                 "is_consent_trans_category": True})
        if status != 200:
            st.error(error_text(res))
            return
        with st.spinner("거래를 정리하고 분석하는 중이에요..."):
            status, res = call("POST", f"/api/mydata/{uid()}/sync", params={"use_llm": use_llm})
        if status == 200:
            st.success(f"거래 {res['flows']}건을 정리했어요.")
            if res.get("agent") == "scheduled":
                st.caption("🤖 변화 감시 에이전트가 달라진 점이 있는지 확인하고 있어요. 결과는 홈과 'AI 에이전트'에 알려 드려요.")
            if res["needs_review"]:
                st.info(f"종류를 확인하면 좋은 거래가 {res['needs_review']}건 있어요. '③ 분류 확인' 탭에서 알려 주세요.")
            st.session_state["refresh_users"] = True
        else:
            st.error(error_text(res))


# ---------------------------------------------------------------------------
def _review() -> None:
    ok, summ = get_ok(f"/api/classification/{uid()}/summary")
    if not ok or not summ["total"]:
        ui.empty_state("정리된 거래가 아직 없어요. '② 금융 데이터 연동'을 먼저 해 주세요.")
        return
    auto = 1 - summ["needs_review"] / summ["total"]
    st.progress(auto, text=f"거래 {summ['total']}건 중 {auto * 100:.1f}%는 자동으로 분류했어요")

    _, cats = get_ok("/api/classification/categories")
    options = cats["variable"] + cats["fixed"]
    _, rv = get_ok(f"/api/classification/{uid()}/review")
    items = rv.get("items", [])
    if not items:
        st.success("확인할 거래가 없어요. 🎉")
        return
    st.markdown(f"**아래 {len(items)}곳은 어떤 종류인지 알려 주세요.** 한 번 알려 주면 다음부터 자동으로 적용돼요.")
    for i, it in enumerate(items):
        with st.container(border=True):
            st.markdown(f"**{it['merchant']}** · {it['count']}건 · 합계 {short_won(it['total_amount'])}")
            ai = " 🤖 AI가 추정한 종류예요. 맞는지 확인해 주세요." if it["rule"] in ("llm", "llm_cache") else ""
            st.caption(STAGE_TEXT.get(it["stage"], "") + ai)
            if it["merchant_norm"]:
                c1, c2 = st.columns([3, 1])
                cat = c1.selectbox("종류", options, key=f"cat_{i}", label_visibility="collapsed",
                                   index=options.index(it["current_category"]) if it["current_category"] in options else 0)
                if c2.button("저장", key=f"apply_{i}", type="primary"):
                    status, res = call("PUT", f"/api/classification/{uid()}/override",
                                       json={"merchant": it["merchant"], "category": cat})
                    if status == 200:
                        st.toast(f"{res['updated_flows']}건에 적용했어요.", icon="✅")
                        st.rerun()
                    else:
                        st.error(error_text(res))
            else:
                st.caption("가게 이름이 없어서 거래마다 따로 정해야 해요.")
                for fid in it["flow_ids"]:
                    c1, c2 = st.columns([3, 1])
                    cat = c1.selectbox(f"거래 #{fid}", options, key=f"flow_{fid}", label_visibility="collapsed")
                    if c2.button("저장", key=f"flowbtn_{fid}"):
                        status, res = call("PUT", f"/api/classification/{uid()}/flows/{fid}", json={"category": cat})
                        if status == 200:
                            st.rerun()
                        else:
                            st.error(error_text(res))


# ---------------------------------------------------------------------------
METHOD_LABEL = {
    "exact": "이미 아는 가게", "brand_token": "이름 앞부분으로 판단", "keyword": "이름 속 단어로 판단",
    "llm": "🤖 AI가 추정", "llm_cache": "🤖 AI가 추정 (앞서 분류한 가게)", "user_override": "✋ 내가 직접 지정",
    "unresolved": "❓ 알 수 없음", "no_name": "❓ 가게 이름 없음", "memo_keyword": "거래 메모로 판단",
    "source_api": "전용 데이터(통신·보험·대출 등)", "card_bill": "카드 대금(소비 아님)", "dedup": "다른 데이터와 중복",
    "default": "기본 규칙", "recurrence": "반복되는 입금으로 판단", "": "-",
}
SOURCE_LABEL = {"bank": "은행", "card": "카드", "efin": "페이", "telecom": "통신", "insurance": "보험",
                "loan": "대출", "invest": "증권", "irp": "IRP"}
MAJOR_LABEL = {"income": "수입", "fixed": "고정지출", "variable": "변동지출", "saving": "저축·투자",
               "transfer": "이체", "ignored": "제외"}
VIEW_OPTIONS = {"all": "전체", "llm": "🤖 AI가 분류한 거래", "review": "확인이 필요한 거래", "user": "내가 직접 지정한 거래"}


def _transactions() -> None:
    ok, probe = get_ok(f"/api/classification/{uid()}/flows", limit=1)
    if not ok or not probe["total"]:
        ui.empty_state("정리된 거래가 아직 없어요. '② 금융 데이터 연동'을 먼저 해 주세요.")
        return

    c1, c2 = st.columns([3, 2])
    c1.markdown("연동한 은행·카드·페이 거래와 **어떤 방법으로 분류했는지**를 볼 수 있어요.")
    c2.metric("AI가 분류한 거래", f"{probe['llm_total']}건")

    view = st.radio("보기", list(VIEW_OPTIONS), format_func=VIEW_OPTIONS.get, horizontal=True, key="tx_view")
    f1, f2, f3 = st.columns(3)
    major = f1.selectbox("종류", ["전체"] + list(MAJOR_LABEL.values()), key="tx_major")
    _, ana = get_ok(f"/api/profile/{uid()}/analysis")
    months = [m["month"] for m in reversed(ana["monthly"])] if isinstance(ana, dict) and ana.get("monthly") else []
    month = f2.selectbox("월", ["전체"] + months, key="tx_month")
    q = f3.text_input("가게·내용 검색", key="tx_q")

    params = {"limit": 300}
    if view != "all":
        params["method"] = view
    if major != "전체":
        params["major"] = {v: k for k, v in MAJOR_LABEL.items()}[major]
    if month != "전체":
        params["month"] = month
    if q:
        params["q"] = q
    ok, res = get_ok(f"/api/classification/{uid()}/flows", **params)
    if not ok:
        st.error(error_text(res))
        return

    if view == "llm" and not res["items"]:
        st.info("아직 AI가 분류한 거래가 없어요. 이름만으로 종류를 알 수 없는 가게가 있을 때 AI가 추정해요. "
                "아래 버튼으로 AI 분류를 실행해 보세요.")
    st.caption(f"{res['total']}건" + (" 중 최근 300건을 보여 드려요" if res["total"] > 300 else ""))
    if res["items"]:
        df = pd.DataFrame([{
            "날짜": r["date"], "구분": "입금" if r["direction"] == "in" else "출금", "가게·내용": r["counterparty"],
            "금액": f"{r['amount']:,.0f}원", "분류": r["category"], "종류": MAJOR_LABEL.get(r["major"], r["major"]),
            "분류 방법": METHOD_LABEL.get(r["rule"], r["rule"]), "출처": SOURCE_LABEL.get(r["source"], r["source"]),
            "확인 필요": "⚠️" if r["needs_review"] else "",
        } for r in res["items"]])
        st.dataframe(df, hide_index=True, width="stretch", height=420)
    if view == "llm" and res["items"]:
        st.caption("AI의 추정은 틀릴 수 있어요. '③ 분류 확인' 탭에서 맞는지 확인하면 그 가게는 다음부터 내가 정한 대로 분류돼요.")

    with st.expander("AI로 분류해 보기"):
        st.write("사전과 이름 속 단어로 알 수 없는 가게를 AI에게 물어봐서 다시 분류해요. 전달하는 정보는 **가게 이름뿐**이에요. "
                 "AI 서버가 설정되어 있어야 하고, 내가 직접 지정한 분류는 그대로 유지돼요.")
        if st.button("AI로 다시 분류하기"):
            with st.spinner("AI가 가게 종류를 추정하는 중이에요..."):
                status, out = call("POST", f"/api/mydata/{uid()}/sync", params={"use_llm": True})
            if status == 200:
                st.success("다시 분류했어요. 위에서 '🤖 AI가 분류한 거래'를 골라 보세요.")
            else:
                st.error(error_text(out))
