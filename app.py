"""BDD vignette rating app (Streamlit).

Run locally:   streamlit run app.py
Config:        .streamlit/secrets.toml  (see secrets.toml.example)
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import streamlit as st

# --- keep local modules consistent after a redeploy -------------------------------
# Streamlit re-imports only the files that changed; an unchanged module (e.g. rater_view)
# keeps its reference to the OLD version of a changed one (e.g. db), so new code is
# silently not used. When any local file changes we reload all of them in dependency order.
_HERE = Path(__file__).resolve().parent
_LOCAL = ["config", "auth", "stats_kappa", "db", "test_sets", "analysis",
          "rater_view", "pi_view"]


def _local_signature():
    return tuple((m, (_HERE / f"{m}.py").stat().st_mtime_ns)
                 for m in _LOCAL if (_HERE / f"{m}.py").exists())


_sig = _local_signature()
if getattr(sys, "_bdd_rating_sig", None) not in (None, _sig):
    for _m in _LOCAL:
        if _m in sys.modules:
            importlib.reload(sys.modules[_m])
sys._bdd_rating_sig = _sig

import db  # noqa: E402
import pi_view  # noqa: E402
import rater_view  # noqa: E402
from auth import hash_problem, verify  # noqa: E402
from config import APP_DATE, APP_VERSION, RATERS, TEST_RATERS  # noqa: E402

st.set_page_config(page_title="BDD Vignette Rating", page_icon="📝", layout="wide")


def _secrets() -> dict:
    try:
        return dict(st.secrets)
    except Exception:  # noqa: BLE001  (no secrets file)
        return {}


SEC = _secrets()
DB_URL = (SEC.get("DATABASE_URL") or os.environ.get("DATABASE_URL") or "sqlite:///rating.db").strip()
# usernames are matched case-insensitively and without surrounding spaces
# (mobile keyboards often capitalise the first letter)
USERS = {str(k).strip().lower(): {kk: (vv.strip() if isinstance(vv, str) else vv)
                                  for kk, vv in dict(v).items()}
         for k, v in SEC.get("users", {}).items()}


def _startup_report():
    """Printed once to the Streamlit Cloud log (Manage app → logs). No secrets are printed."""
    print(f"[rating-app] secrets keys: {sorted(SEC.keys())}", flush=True)
    print(f"[rating-app] users loaded: {len(USERS)}", flush=True)
    for name, info in USERS.items():
        prob = hash_problem(info.get("password_hash"))
        print(f"[rating-app]  - {name}: role={info.get('role')!r} rater={info.get('rater')!r} "
              f"hash={'OK' if not prob else 'BAD: ' + prob}", flush=True)


if "_reported" not in st.session_state:
    _startup_report()
    st.session_state["_reported"] = True


@st.cache_resource
def _cached_engine(url: str):
    return db.get_engine(url)


def engine(url: str):
    # the cached engine outlives code reloads; make sure new tables exist after a redeploy
    return db.ensure_schema(_cached_engine(url))


def login():
    st.title("📝 BDD Vignette Rating")
    if not USERS:
        st.error("ยังไม่ได้ตั้งค่าผู้ใช้ใน secrets (ดู README)")
        st.stop()
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("เข้าสู่ระบบ", type="primary"):
            name = u.strip().lower()
            info = USERS.get(name)
            if info is None:
                st.error(f"ไม่พบ username นี้ (ตั้งค่าไว้ {len(USERS)} บัญชี) "
                         "ตรวจตัวสะกด หรือชื่อหัวข้อ [users.xxx] ใน Secrets")
            elif hash_problem(info.get("password_hash")):
                st.error("password_hash ของบัญชีนี้ใน Secrets รูปแบบไม่ถูกต้อง: "
                         f"{hash_problem(info.get('password_hash'))}")
            elif not verify(p, info["password_hash"]):
                st.error("Password ไม่ถูกต้อง")
            else:
                st.session_state.user = {"username": name, **info}
                try:
                    with db.Session(engine(DB_URL)) as s:
                        db.log(s, name, "login")
                        s.commit()
                except Exception as e:  # noqa: BLE001
                    st.session_state.pop("user", None)
                    st.error(f"Password ถูกต้อง แต่เชื่อมต่อฐานข้อมูลไม่ได้: {type(e).__name__} "
                             "ตรวจ DATABASE_URL ใน Secrets (ดูรายละเอียดใน logs)")
                    print(f"[rating-app] DB error: {e!r}", flush=True)
                    st.stop()
                st.rerun()
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
