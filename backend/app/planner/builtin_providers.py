"""2차 내장 후보 공급자 — 소비 절감·구독 정리(SpendingProvider), 보유 자산 조정·비상금·적자(AssetProvider)

3차 이후의 도메인 모듈도 이 파일과 같은 모양(`name`, `generate(ctx) -> [후보]`)으로 만들어 registry에 등록한다.
"""
import math
from typing import List

from app.pipeline import params
from app.planner.candidates import CandidateContext, make_candidate


class SpendingProvider:
    """새는 돈 줄이기: 카테고리 절감 · 급증분 복구 · 구독 정리"""
    name = "spending"

    def generate(self, ctx: CandidateContext) -> List[dict]:
        cands: List[dict] = []
        income = ctx.monthly_income or 0
        min_saving = max(params.G_MIN_SAVING_ABS, income * params.G_MIN_SAVING_INCOME_SHARE)
        outlier_by_cat = {o["category"]: o for o in ctx.outliers}
        scale = (ctx.prefs or {}).get("cut_scale", {})      # '금액이 부담돼요'를 고른 카테고리는 규모를 줄여서 제안
        for cat, by_month in ctx.category_monthly.items():
            if cat == "미분류":                  # 분류가 확정되지 않은 지출은 절감 후보로 삼지 않는다(분류 확인이 먼저)
                continue
            vals = [by_month.get(m, 0.0) for m in ctx.window]
            avg = sum(vals) / len(vals) if vals else 0.0
            if cat in params.G_NONESSENTIAL and avg > 0:
                rate = params.G_CUT_RATE_NONESSENTIAL * scale.get(cat, 1.0)
                saving = round(avg * rate, -2)
                if saving >= min_saving:
                    cands.append(make_candidate(
                        f"cut:{cat}", "소비 절감", f"{cat} 지출 {rate * 100:g}% 줄이기",
                        f"{cat} 월 평균 {avg:,.0f}원 중 {saving:,.0f}원을 줄입니다.", saving,
                        {"kind": "category_cut", "category": cat, "baseline_avg": round(avg),
                         "cut_rate": rate},
                        {"월 평균 지출": round(avg), "관측 개월": len(vals)}, f"cat:{cat}", provider=self.name))
            o = outlier_by_cat.get(cat)
            if o:
                saving = round((o["recent"] - o["baseline"]) * scale.get(cat, 1.0), -2)
                if saving >= min_saving:
                    cands.append(make_candidate(
                        f"restore:{cat}", "소비 절감", f"{cat} 급증분 되돌리기",
                        f"{cat}이 직전 3개월 평균 {o['baseline']:,.0f}원에서 {o['recent']:,.0f}원으로 늘었습니다. "
                        f"평균 수준으로 되돌리면 월 {saving:,.0f}원을 아낍니다.", saving,
                        {"kind": "category_cut", "category": cat, "baseline_avg": round(o["baseline"]), "restore": True},
                        {"최근 월": round(o["recent"]), "직전 3개월 평균": round(o["baseline"]),
                         "증가율(%)": o.get("growth_pct")}, f"cat:{cat}", provider=self.name))
        for sub in ctx.subscriptions:                 # 미사용 여부는 데이터로 알 수 없으므로 사용자 확인이 필요하다
            amt = round(sub["monthly_amount"], -2)
            if amt >= params.G_MIN_SAVING_ABS:
                cands.append(make_candidate(
                    f"sub:{sub['merchant']}", "구독 정리", f"구독 '{sub['merchant']}' 점검",
                    f"매월 {amt:,.0f}원이 나가는 정기결제입니다. 쓰지 않는다면 해지해 보세요(사용 여부는 직접 확인 필요).",
                    amt, {"kind": "subscription", "merchant": sub["merchant"], "monthly_amount": amt},
                    {"월 결제액": amt}, f"sub:{sub['merchant']}", provider=self.name))
        return cands


class AssetProvider:
    """보유 자산 간 조정(R-01): 월 적자 해소 · 비상금 우선 적립(필수) · 남는 현금 이동"""
    name = "asset"

    def generate(self, ctx: CandidateContext) -> List[dict]:
        out: List[dict] = []
        em = ctx.emergency or {}
        coverage = em.get("coverage_ratio")
        budget = ctx.path_input.monthly_budget
        if budget < 0:
            out.append(make_candidate(
                "deficit", "저축 금액 조정", "월 적자부터 해소하기",
                f"매달 {-budget:,.0f}원 적자입니다. 저축·목표 배분보다 먼저 아래 절감안으로 적자를 메워야 합니다.",
                0.0, {"kind": "deficit_first", "deficit": round(-budget)},
                {"월 적자": round(-budget)}, "budget", mandatory=True, provider=self.name))
        if coverage is not None and coverage < 100 and em.get("required") and budget > 0:
            shortage = em["required"] - em.get("liquid_cash", 0)
            monthly = max(round(min(shortage / params.G_EMERGENCY_FILL_MONTHS, budget), -2), 1_000)
            months = min(math.ceil(shortage / monthly), 60)
            out.append(make_candidate(
                "emergency", "비상금 우선 적립", "비상금 먼저 채우기",
                f"비상금이 {shortage:,.0f}원 부족합니다(충당률 {coverage:.1f}%). 투자·장기 적립보다 먼저, "
                f"월 {monthly:,.0f}원씩 {months}개월 동안 입출금·CMA에 모아 두세요.",
                -monthly, {"kind": "emergency_first", "shortage": round(shortage), "monthly": monthly, "months": months},
                {"충당률(%)": coverage, "필요 비상금": em["required"], "보유 현금성": em.get("liquid_cash", 0)},
                "budget", mandatory=True, provider=self.name,
                change={"one_offs": {k: monthly for k in range(1, months + 1)}}))   # 목표 적립 대신 비상금으로 돌리는 달들
        elif coverage is not None and coverage >= 100:
            excess = em.get("liquid_cash", 0) - em.get("required", 0) - em.get("monthly_essential_expense", 0)
            if excess >= params.G_CASH_EXCESS_MIN:
                gain = round(excess * (params.G_DEPOSIT_RATE - params.G_CHECKING_RATE) / 12, -2)
                if gain > 0:
                    out.append(make_candidate(
                        "cash_move", "자산 비중 조정", "남는 현금을 저축성 자산으로 옮기기",
                        f"비상금과 한 달 생활비를 뺀 현금 {excess:,.0f}원이 입출금에 있습니다. "
                        f"저축성 자산으로 옮기면 월 약 {gain:,.0f}원의 이자를 더 받습니다(금리 가정 기준).",
                        gain, {"kind": "cash_move", "excess": round(excess)},
                        {"이동 대상 금액": round(excess),
                         "금리 가정": f"{params.G_CHECKING_RATE:.1%} → {params.G_DEPOSIT_RATE:.1%}"},
                        "cash", provider=self.name))
        return out
