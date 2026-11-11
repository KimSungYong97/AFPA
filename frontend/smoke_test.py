"""화면 점검 스크립트 — 실행 중인 백엔드에 연결해 7개 화면을 사용자별로 그려 보고 오류가 없는지 확인한다.

    # 백엔드를 먼저 실행한 뒤
    cd frontend
    python smoke_test.py http://127.0.0.1:8080

오류가 있으면 종료 코드 1로 끝난다. (화면 모양은 확인하지 못하고 '예외 없이 그려지는지'만 본다)
"""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
ROOT = str(Path(__file__).resolve().parent)
VIEWS = ["home", "goals", "money", "todo", "alerts", "data", "agent"]

TEMPLATE = '''
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from lib import ui
from lib.api import call
ui.inject_css()
st.session_state["api_url"] = "{api}"
users = call("GET", "/api/users")[1]
st.session_state["ctx"] = {{"user": users[{idx}], "use_llm": False}}
from lib.nav import register
register({{}})
from views import {view}
{view}.render()
'''


def main() -> int:
    from lib.api import call  # noqa: F401  (경로 확인용 import)
    problems = 0
    n_users = 3
    for idx in range(n_users):
        for view in VIEWS:
            at = AppTest.from_string(TEMPLATE.format(root=ROOT, api=API, idx=idx, view=view), default_timeout=60)
            at.run()
            errs = [str(e.value)[:200] for e in at.exception] + [str(e.value)[:200] for e in at.error]
            mark = "OK " if not errs else "FAIL"
            print(f"{mark} 사용자#{idx} {view}" + (f" — {errs}" if errs else ""))
            problems += bool(errs)
    print("\n모든 화면이 정상적으로 그려졌어요." if not problems else f"\n문제가 있는 화면 {problems}곳")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    sys.exit(main())
