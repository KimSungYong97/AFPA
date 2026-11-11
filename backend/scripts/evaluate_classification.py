"""분류·산출 평가 스크립트 (DB 없이 마이데이터 JSON만 사용)

「평가 기준 및 성능 대시보드」의 1차 평가 항목:
  - 변동지출 카테고리 정확도 (목표 90%+)
  - 고정지출 판별 정밀도·재현율 (목표 정밀도 90%+)
  - 정기수입 판별 (목표 재현율 95%+)
  - 월 고정/변동 지출 평균이 페르소나 정의값과 얼마나 가까운지 (참고)

정답 라벨(`_category`, `_is_fixed`, `_user.json`)은 분류 로직에 입력하지 않고 평가에만 사용한다.

사용법:  cd backend && python -m scripts.evaluate_classification [--llm]
  --llm : 3단계 LLM 분류를 켠다(LLM_BASE_URL/LLM_MODEL 또는 OPENAI_API_KEY 필요)
"""
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime

from app.pipeline.classifier import classify_flows, classify_holdings
from app.pipeline.engines import EngineInput, compute
from app.pipeline.llm_stage import build_llm_categorizer
from app.pipeline.merchant import MerchantClassifier
from app.pipeline.mydata_source import MYDATA_DIR, load_user_data
from app.pipeline.types import GoalInfo


def _labels(user_dir):
    with open(user_dir / "card_approvals.json", encoding="utf-8") as f:
        approvals = json.load(f)["approved_list"]
    return {a["approved_num"]: (a.get("_category"), bool(a.get("_is_fixed"))) for a in approvals}


def evaluate_user(user_dir, use_llm: bool = False) -> dict:
    data = load_user_data(user_dir)
    meta = json.load(open(user_dir / "_user.json", encoding="utf-8"))
    llm = build_llm_categorizer() if use_llm else None
    merchant = MerchantClassifier(llm=llm)              # 기본은 규칙 단계만 평가, --llm 이면 3단계 포함
    flows, report = classify_flows(data, merchant)
    holdings = classify_holdings(data)

    # --- 카드 승인 건 정확도 (순서가 같으므로 approved_num 순으로 매칭)
    labels = _labels(user_dir)
    approvals = [a for a in data["card_approvals"]["approved_list"] if a.get("status") == "01"]
    card_flows = [f for f in flows if f.source == "card"]
    correct_cat = fixed_tp = fixed_fp = fixed_fn = 0
    n = 0
    confusions = Counter()
    for a, f in zip(approvals, card_flows):
        gold_cat, gold_fixed = labels[a["approved_num"]]
        n += 1
        pred_fixed = f.major == "fixed"
        # 정답 라벨의 '구독서비스'는 고정지출 범주이므로 카테고리 일치로 본다
        if f.category == gold_cat:
            correct_cat += 1
        else:
            confusions[(gold_cat, f.category)] += 1
        fixed_tp += pred_fixed and gold_fixed
        fixed_fp += pred_fixed and not gold_fixed
        fixed_fn += (not pred_fixed) and gold_fixed

    # --- 정기수입
    salary = [f for f in flows if f.major == "income"]
    recurring_income = [f for f in salary if f.recurring]

    # --- 6개 엔진
    as_of = max(f.occurred_on for f in flows)
    goals = [GoalInfo(g["name"], g["target_amount"], g["current_amount"],
                      datetime.strptime(g["target_date"], "%Y-%m-%d").date() if g.get("target_date") else None,
                      g.get("priority", 1)) for g in meta.get("goals", [])]
    res = compute(EngineInput(as_of=as_of, flows=flows, holdings=holdings, goals=goals))

    return {
        "user": meta["name"], "card_n": n,
        "category_acc": correct_cat / n if n else None,
        "fixed_precision": fixed_tp / (fixed_tp + fixed_fp) if (fixed_tp + fixed_fp) else None,
        "fixed_recall": fixed_tp / (fixed_tp + fixed_fn) if (fixed_tp + fixed_fn) else None,
        "income_flows": len(salary), "income_recurring": len(recurring_income),
        "stages": report.by_stage, "needs_review": report.needs_review,
        "confusions": dict(confusions), "llm_calls": merchant.llm_calls,
        "llm_flows": sum(1 for f in flows if f.rule in ("llm", "llm_cache")),
        "income": res.monthly_income_net, "income_label": meta["monthly_income"],
        "fixed": res.details["cash_flow"]["fixed_expense"], "fixed_label": meta["monthly_fixed_expense"],
        "variable": res.details["cash_flow"]["variable_expense"],
        "variable_label": meta["monthly_variable_expense"],
        "net_cash_flow": res.net_cash_flow, "net_worth": res.net_worth,
        "health": res.health_score, "potential": res.potential_score,
        "dsr": res.dsr_ratio, "emergency": res.emergency_fund_ratio,
        "consumption": res.consumption_ratio, "savings": res.savings_ratio,
    }


def main() -> None:
    use_llm = "--llm" in sys.argv
    for user_dir in sorted(MYDATA_DIR.glob("user_*")):
        r = evaluate_user(user_dir, use_llm)
        print(f"\n=== {user_dir.name} ({r['user']}) ===")
        print(f"카드 {r['card_n']}건  카테고리 정확도 {r['category_acc']:.1%}  "
              f"고정 정밀도 {r['fixed_precision']}  재현율 {r['fixed_recall']}")
        if use_llm:
            print(f"LLM 호출 {r['llm_calls']}회, LLM으로 분류된 거래 {r['llm_flows']}건")
        print(f"수입 {r['income_flows']}건 중 정기 {r['income_recurring']}건 / 단계별 {r['stages']} / 검토필요 {r['needs_review']}")
        print(f"월 수입 {r['income']:,.0f} (정의 {r['income_label']:,})  "
              f"고정 {r['fixed']:,.0f} (정의 {r['fixed_label']:,})  "
              f"변동 {r['variable']:,.0f} (정의 {r['variable_label']:,})")
        print(f"여유자금 {r['net_cash_flow']:,.0f}  순자산 {r['net_worth']:,.0f}  "
              f"건강도 {r['health']}  잠재력 {r['potential']}  "
              f"DSR {r['dsr']}  비상금 {r['emergency']}  소비성향 {r['consumption']}  저축성향 {r['savings']}")
        if r["confusions"]:
            print("오분류:", r["confusions"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
