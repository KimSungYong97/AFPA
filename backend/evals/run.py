"""에이전트 평가 실행기

    python -m evals.run                 # 규칙 경로(LLM 없음)만: 변화 감시 시나리오
    python -m evals.run --llm           # 실제 AI로 변화 감시 + 대화 평가 (LLM_BASE_URL, LLM_MODEL 필요)
    python -m evals.run --llm --suite chat --out evals/last_report.json
    python -m evals.run --llm --min-pass 0.8   # 통과율이 낮으면 종료 코드 1
"""
import argparse
import json
import sys
from pathlib import Path

from evals import runner


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="실제 AI로 평가한다(느림, 서버 필요)")
    ap.add_argument("--suite", choices=["watch", "chat", "all"], default="all")
    ap.add_argument("--min-pass", type=float, default=0.0, help="사례 통과율이 이 값 미만이면 실패로 종료")
    ap.add_argument("--out", help="결과(JSON)를 저장할 경로")
    args = ap.parse_args()

    from app.llm_client import llm_enabled
    if args.llm and not llm_enabled():
        print("LLM이 설정되어 있지 않습니다. LLM_BASE_URL / LLM_MODEL 환경변수를 확인하세요.", file=sys.stderr)
        return 2

    report, worst = {}, 1.0
    if args.suite in ("watch", "all"):
        rows = [runner.run_watch_case(c, use_llm=args.llm) for c in runner.load_cases("watch")]
        print(runner.format_report("변화 감시 에이전트" + (" (AI)" if args.llm else " (규칙)"), rows))
        report["watch"] = {"summary": runner.summarize(rows), "rows": rows}
        worst = min(worst, report["watch"]["summary"]["case_pass_rate"])
    if args.suite in ("chat", "all") and args.llm:
        rows = [runner.run_chat_case(c) for c in runner.load_cases("chat")]
        print(runner.format_report("대화 에이전트 (AI)", rows))
        report["chat"] = {"summary": runner.summarize(rows), "rows": rows}
        worst = min(worst, report["chat"]["summary"]["case_pass_rate"])
    elif args.suite == "chat":
        print("대화 평가는 AI가 필요합니다(--llm).")

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if worst >= args.min_pass else 1


if __name__ == "__main__":
    sys.exit(main())
