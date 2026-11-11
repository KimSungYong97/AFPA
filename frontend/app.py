"""AFPA — 내 돈 관리 도우미 (Streamlit 확인용 화면)

내 금융 데이터를 바탕으로 '지금 내 상황'과 '목표를 더 빨리 이루는 방법'을 알려 주는 화면이다.
숫자는 모두 백엔드가 계산한 값이며, 이 화면은 보여 주기만 한다.

실행:
    cd frontend
    pip install -r requirements.txt
    streamlit run app.py
백엔드 주소는 사이드바 '연결 설정'에서 바꾸거나 환경변수 AFPA_API_URL 로 지정한다.
"""
import streamlit as st

st.set_page_config(page_title="AFPA · 내 돈 관리 도우미", page_icon="💰", layout="wide")

from lib import ui                                       # noqa: E402
from lib.api import DEFAULT_API, call, error_text, get_ok  # noqa: E402
from lib.nav import register                             # noqa: E402
from views import agent, alerts, data, goals, home, money, todo  # noqa: E402

ui.inject_css()

# --- 사이드바: 사용자 선택과 연결 설정 -------------------------------------------------
st.sidebar.markdown("## 💰 AFPA")
st.sidebar.caption("내 돈 관리 도우미")
st.session_state.setdefault("api_url", DEFAULT_API)
st.session_state.setdefault("use_llm", False)
with st.sidebar.expander("연결 설정"):
    st.text_input("서버 주소", key="api_url")
    st.checkbox("요약 문장을 AI로 다듬기", key="use_llm",
                help="숫자는 그대로 두고 문장만 자연스럽게 바꿔요. AI 서버가 설정되어 있어야 해요.")
use_llm = st.session_state["use_llm"]

status, users = call("GET", "/api/users")
if status != 200:
    st.title("💰 AFPA")
    st.error(users if status is None else f"사용자 정보를 불러오지 못했어요: {error_text(users)}")
    st.info("서버를 먼저 켜 주세요.\n\n`cd backend` → `python -m uvicorn app.main:app --port 8080`\n\n"
            "연습용 사용자가 없다면 `python -m scripts.seed_data --reset` 을 실행하세요.")
    st.stop()
if not users:
    st.title("💰 AFPA")
    st.warning("등록된 사용자가 없어요. `python -m scripts.seed_data --reset` 으로 연습용 사용자를 만드세요.")
    st.stop()

names = {f"{u['name']} ({u.get('persona_type') or '사용자'})": u for u in users}
choice = st.sidebar.selectbox("사용자", list(names))
user = names[choice]
st.sidebar.caption(user.get("description") or "")
st.session_state["ctx"] = {"user": user, "use_llm": use_llm}

if user["mydata_connected"]:
    ok, notes = get_ok(f"/api/planner/{user['id']}/notifications", unread_only="true")
    n = len(notes.get("notifications", [])) if ok else 0
    if n:
        st.sidebar.markdown(f"🔔 읽지 않은 알림 **{n}건**")

# --- 메뉴 ---------------------------------------------------------------------------
pages = {
    "home": st.Page(home.render, title="홈", icon="🏠", url_path="home", default=True),
    "goals": st.Page(goals.render, title="내 목표", icon="🎯", url_path="goals"),
    "money": st.Page(money.render, title="내 돈 현황", icon="💰", url_path="money"),
    "todo": st.Page(todo.render, title="할 일", icon="✅", url_path="todo"),
    "alerts": st.Page(alerts.render, title="알림", icon="🔔", url_path="alerts"),
    "data": st.Page(data.render, title="내 정보·연동", icon="⚙️", url_path="data"),
    "agent": st.Page(agent.render, title="AI 에이전트", icon="🤖", url_path="agent"),
}
register(pages)
st.navigation(list(pages.values()), position="top").run()
