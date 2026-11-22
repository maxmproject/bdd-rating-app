"""Login path tests using Streamlit's AppTest (no browser)."""
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from auth import hash_problem, make_hash, verify  # noqa: E402

H = make_hash("secret1")


def test_verify_tolerates_whitespace():
    assert verify("secret1", "  " + H + "\n")
    assert not verify("wrong", H)
    assert hash_problem(H) == "" and hash_problem(" " + H) == ""
    assert hash_problem("pbkdf2_sha256$200000$abc") != ""
    assert hash_problem("") != ""


def _app(tmp_path, users):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.secrets["DATABASE_URL"] = f"  sqlite:///{tmp_path/'t.db'}  "
    at.secrets["users"] = users
    return at.run()


def _login(at, u, p):
    at.text_input[0].input(u)
    at.text_input[1].input(p)
    at.button[0].click()
    return at.run()


@pytest.fixture
def users():
    return {"Witkanit": {"name": "PI", "role": "pi", "password_hash": " " + H + " "},
            "klampu": {"name": "A", "role": "rater", "rater": "A", "password_hash": H}}


def test_login_case_and_space_insensitive(tmp_path, users):
    at = _login(_app(tmp_path, users), "  witKANIT ", "secret1")
    assert not at.exception
    assert at.session_state["user"]["role"] == "pi"


def test_login_messages(tmp_path, users):
    at = _login(_app(tmp_path, users), "nobody", "secret1")
    assert "ไม่พบ username" in at.error[0].value
    at = _login(_app(tmp_path, users), "klampu", "bad")
    assert at.error[0].value == "Password ไม่ถูกต้อง"
    bad = dict(users, klampu=dict(users["klampu"], password_hash="pbkdf2_sha256$x"))
    at = _login(_app(tmp_path, bad), "klampu", "secret1")
    assert "รูปแบบไม่ถูกต้อง" in at.error[0].value


def test_rater_login_reaches_form(tmp_path, users):
    at = _login(_app(tmp_path, users), "klampu", "secret1")
    assert not at.exception
    assert at.session_state["user"]["rater"] == "A"


def test_test_account_sees_only_its_10(tmp_path):
    import db
    from config import TEST_AREAS
    areas = [a for v in TEST_AREAS.values() for a in v]
    rows = [(f"V-{i:03d}", "x", "หลัก", c, "", a) for i, (a, c) in enumerate(
        ((a, c) for a in areas for c in ("BDD-positive", "BDD-negative") for _ in range(4)), 1)]
    import pandas as pd
    eng = db.get_engine(f"sqlite:///{tmp_path/'t.db'}")
    db.upsert_vignettes(eng, pd.DataFrame(rows, columns=["vid", "text", "set_role", "cls",
                                                         "stratum_code", "area"]), "pi")
    users = {"test1": {"name": "t", "role": "rater", "rater": "T1", "password_hash": H}}
    at = _login(_app(tmp_path, users), "test1", "secret1")
    assert not at.exception
    assert at.sidebar.metric[0].value == "0 / 10"
