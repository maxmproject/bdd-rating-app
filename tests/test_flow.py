"""End-to-end backend flow on a temp SQLite DB (no Streamlit runtime)."""
import io
import os
import sys
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analysis  # noqa: E402
import db  # noqa: E402
from rater_view import rater_order  # noqa: E402


@pytest.fixture
def eng(tmp_path):
    """SQLite by default; set TEST_DB_URL to run against a throw-away Postgres."""
    url = os.environ.get("TEST_DB_URL")
    if url:
        e = db.get_engine(url)
        db.Base.metadata.drop_all(e)
        db.Base.metadata.create_all(e)
        return e
    return db.get_engine(f"sqlite:///{tmp_path/'t.db'}")


def _vigs(n=20):
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "vid": [f"V-{i:03d}" for i in range(1, n + 1)],
        "text": [f"ข้อความ {i}" for i in range(1, n + 1)],
        "set_role": ["หลัก"] * (n - 2) + ["สำรอง"] * 2,
        "cls": rng.choice(["BDD-positive", "BDD-negative"], n),
        "stratum_code": "X", "area": "จมูก"})


def test_full_flow(eng):
    v = _vigs()
    assert db.upsert_vignettes(eng, v, "pi")["added"] == 20
    rater_cols = set(db.vignettes_for_rater(eng).columns)
    assert rater_cols == {"vid", "text"}          # blinding: no class/stratum
    assert rater_order(v.vid.tolist(), "A") != rater_order(v.vid.tolist(), "B")
    assert rater_order(v.vid.tolist(), "A") == rater_order(v.vid.tolist(), "A")

    truth = dict(zip(v.vid, v.cls.map({"BDD-positive": "BDD", "BDD-negative": "Non-BDD"})))
    for r, flip in (("A", {"V-003"}), ("B", {"V-005", "V-007"})):
        for vid, lab in truth.items():
            if vid in flip:
                lab = "ข้อมูลไม่พอ" if vid == "V-007" else ("Non-BDD" if lab == "BDD" else "BDD")
            allc = lab == "BDD"
            db.save_rating(eng, r, vid, dict(crit_a=allc, crit_b=allc, crit_c=allc, crit_d=True,
                                             label=lab, insight="poor" if allc else "",
                                             confidence=4, note=""), r)
    db.set_lock(eng, "A", True, "A")
    with pytest.raises(PermissionError):
        db.save_rating(eng, "A", "V-001", dict(crit_a=False, crit_b=False, crit_c=False,
                                               crit_d=True, label="Non-BDD", insight="",
                                               confidence=3, note=""), "A")
    m = analysis.merged(analysis.load_all(eng))
    assert set(m[m.needs_consensus].vid) == {"V-003", "V-005", "V-007"}
    agr, _ = analysis.agreement(m, 200)
    assert agr.loc[0, "n"] == 20 and abs(agr.loc[0, "po"] - 17 / 20) < 1e-12

    db.save_consensus(eng, "V-003", "pi", label=truth["V-003"], note="ok")
    m = analysis.merged(analysis.load_all(eng))
    assert m.set_index("vid").at["V-003", "final_label"] == truth["V-003"]
    assert (m.final_label == "รอ consensus").sum() == 2

    # text edited after rating -> flagged, reset keeps audit
    v2 = v.copy(); v2.loc[0, "text"] = "แก้ไขแล้ว"
    res = db.upsert_vignettes(eng, v2, "pi")
    assert res["changed_rated"] == ["V-001"]
    assert db.reset_ratings(eng, ["V-001"], "pi", "edit") == 2

    x = analysis.build_export(eng, 100)
    wb = openpyxl.load_workbook(io.BytesIO(x))
    assert {"Summary", "Agreement", "Rater_A", "Rater_B", "Kappa",
            "Blueprint_check", "Audit_log"} <= set(wb.sheetnames)


def test_test_accounts_isolated(eng):
    v = _vigs(6)
    db.upsert_vignettes(eng, v, "pi")
    rate = dict(crit_a=True, crit_b=True, crit_c=True, crit_d=True, label="BDD",
                insight="poor", confidence=3, note="")
    for r in ("A", "T1", "T2"):
        for vid in v.vid[:3]:
            db.save_rating(eng, r, vid, rate, r)
    db.save_consensus(eng, "V-001", "pi", label="Non-BDD", include=True)
    d = analysis.load_all(eng)
    real = analysis.merged(d)
    assert real.label_A.notna().sum() == 3 and real.label_B.isna().all()   # T1/T2 not in real
    test = analysis.merged(d, ("T1", "T2"))
    assert test.both_rated.sum() == 3
    assert (test.cons_label == "").all() and not test.include.any()     # no consensus leak
    x = analysis.build_export(eng, 50)
    wb = openpyxl.load_workbook(io.BytesIO(x))
    assert wb["Rater_B"].cell(2, 7).value is None                         # Rater_B empty
    db.set_lock(eng, "T1", True, "T1")
    assert db.clear_ratings_of(eng, ["T1", "T2"], "pi") == 6
    assert not db.is_locked(eng, "T1") and db.get_ratings(eng, "A")
