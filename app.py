"""BDD vignette rating app (Streamlit).

Run locally:   streamlit run app.py
Config:        .streamlit/secrets.toml  (see secrets.toml.example)
"""
from __future__ import annotations

import os

import streamlit as st

import db
import pi_view
import rater_view
from auth import verify
from config import APP_DATE, APP_VERSION, RATERS, TEST_RATERS

st.set_page_config(page_title="BDD Vignette Rating", page_icon="📝", layout="wide")


def _secrets() -> dict:
    try:
        return dict(st.secrets)
    except Exception:  # noqa: BLE001  (no secrets file)
        return {}


SEC = _secrets()
DB_URL = SEC.get("DATABASE_URL") or os.environ.get("DATABASE_URL") or "sqlite:///rating.db"
USERS = {k: dict(v) for k, v in SEC.get("users", {}).items()}


@st.cache_resource
def engine(url: str):
    return db.get_engine(url)


def login():
    st.title("📝 BDD Vignette Rating")
    if not USERS:
        st.error("ยังไม่ได้ตั้งค่าผู้ใช้ใน secrets (ดู README)")
        st.stop()
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("เข้าสู่ระบบ", type="primary"):
            info = USERS.get(u.strip())
            if info and verify(p, info.get("password_hash", "")):
                st.session_state.user = {"username": u.strip(), **info}
                with db.Session(engine(DB_URL)) as s:
                    db.log(s, u.strip(), "login")
                    s.commit()
                st.rerun()
            st.error("Username หรือ password ไม่ถูกต้อง")
    st.caption(f"{APP_VERSION} · {APP_DATE} · ข้อมูลทั้งหมดเป็น vignette สังเคราะห์ ไม่มีข้อมูลผู้ป่วยจริง")


def main():
    user = st.session_state.get("user")
    if not user:
        login()
        return
    eng = engine(DB_URL)
    with st.sidebar:
        st.markdown(f"**{user.get('name', user['username'])}** ({user['role']})")
        if st.button("ออกจากระบบ"):
            st.session_state.clear()
            st.rerun()
        if DB_URL.startswith("sqlite") and user["role"] == "pi":
            st.warning("กำลังใช้ SQLite: บน Streamlit Cloud ข้อมูลจะหายเมื่อแอปรีสตาร์ต "
                       "ใช้ Postgres สำหรับการเก็บข้อมูลจริง")
        st.divider()
    if user["role"] == "pi":
        st.title("หน้า PI")
        pi_view.render(eng, user)
    elif user["role"] == "rater" and user.get("rater") in RATERS + TEST_RATERS:
        st.title("แบบประเมิน vignette · DSM-5-TR")
        if user["rater"] in TEST_RATERS:
            st.info(f"🧪 บัญชีทดสอบ ({user['rater']}): ผลที่บันทึกแยกจากข้อมูลจริง "
                    "ไม่ถูกนำไปคำนวณ κ, consensus หรือ export")
        st.caption("ประเมินแยกกัน ไม่ปรึกษาผู้ประเมินอีกคนจนกว่าจะส่งครบ")
        rater_view.render(eng, user)
    else:
        st.error("บัญชีนี้ตั้งค่า role ไม่ถูกต้อง")


main()
