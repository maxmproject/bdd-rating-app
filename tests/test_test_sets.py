"""Test-account subsets: 10 each, disjoint, different domains, balanced classes."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db  # noqa: E402
from config import TEST_AREAS, TEST_N  # noqa: E402
from test_sets import default_sets  # noqa: E402

AREAS = [a for v in TEST_AREAS.values() for a in v]


def _pool(per=12):
    rows = [(f"V-{i:03d}", a, c) for i, (a, c) in enumerate(
        ((a, c) for a in AREAS for c in ("BDD-positive", "BDD-negative") for _ in range(per)), 1)]
    return pd.DataFrame(rows, columns=["vid", "area", "cls"])


def test_default_sets_properties():
    pool = _pool()
    sets = default_sets(pool)
    p = pool.set_index("vid")
    assert set(sets["T1"]).isdisjoint(sets["T2"])
    for r, vids in sets.items():
        assert len(vids) == TEST_N
        assert set(p.loc[vids, "area"]) <= set(TEST_AREAS[r])
        assert (p.loc[vids, "cls"] == "BDD-positive").sum() == TEST_N // 2
        assert p.loc[vids, "area"].nunique() == len(TEST_AREAS[r])   # spread over its domains
    assert default_sets(pool) == sets and default_sets(pool, seed=1) != sets


def _db_with_pool(tmp_path, per=3):
    eng = db.get_engine(f"sqlite:///{tmp_path/'t.db'}")
    pool = _pool(per)
    df = pool.assign(text="x", set_role="หลัก", stratum_code="")
    db.upsert_vignettes(eng, df[["vid", "text", "set_role", "cls", "stratum_code", "area"]], "pi")
    return eng, pool


def test_shared_set_default(tmp_path):
    eng, pool = _db_with_pool(tmp_path)
    t1 = db.ensure_test_assignment(eng, "T1")
    assert t1 == db.get_assignment(eng, "T2")                      # identical sets
    assert len(t1) == 2 * TEST_N
    p = pool.set_index("vid")
    assert (p.loc[t1, "cls"] == "BDD-positive").sum() == TEST_N
    assert set(p.loc[t1, "area"]) == set(AREAS)                      # every domain


def test_migration_from_disjoint_keeps_ratings(tmp_path):
    """Old V1.2 state: T1/T2 had different 10s and some ratings -> both get the same 20."""
    eng, pool = _db_with_pool(tmp_path)
    old = default_sets(db.test_pool(eng))
    for r, vids in old.items():
        db.set_assignment(eng, r, vids, "old")
    rate = dict(crit_a=False, crit_b=False, crit_c=False, crit_d=True, label="Non-BDD",
                insight="", confidence=3, note="")
    db.save_rating(eng, "T1", old["T1"][0], rate, "T1")
    shared = db.ensure_test_assignment(eng, "T2")
    assert shared == sorted(old["T1"] + old["T2"])
    assert db.get_assignment(eng, "T1") == db.get_assignment(eng, "T2") == shared
    assert old["T1"][0] in db.get_ratings(eng, "T1")                 # rating kept
    db.set_shared_assignment(eng, shared[:5], "pi")
    assert db.ensure_test_assignment(eng, "T1") == shared[:5]        # PI edit is kept


def test_test_export(tmp_path):
    import io
    import openpyxl
    import analysis
    eng, _ = _db_with_pool(tmp_path)
    shared = db.ensure_test_assignment(eng)
    rate = dict(crit_a=True, crit_b=True, crit_c=True, crit_d=True, label="BDD",
                insight="poor", confidence=4, note="t")
    for vid in shared[:3]:
        db.save_rating(eng, "T1", vid, rate, "T1")
        db.save_rating(eng, "T2", vid, dict(rate, label="Non-BDD", insight="", note="t2"), "T2")
    db.save_rating(eng, "A", shared[0], rate, "A")                    # real data must not leak
    wb = openpyxl.load_workbook(io.BytesIO(analysis.build_test_export(eng)))
    assert wb.sheetnames == ["Summary"] + [f"Test_T{i}" for i in range(1, 6)] + ["Compare"]
    t1 = list(wb["Test_T1"].iter_rows(values_only=True))
    assert len(t1) == 1 + len(shared)
    assert "ความเห็นของผู้ประเมิน (หมายเหตุ)" in t1[0]
    ci = t1[0].index("ความเห็นของผู้ประเมิน (หมายเหตุ)")
    assert sum(r[6] == "BDD" for r in t1[1:]) == 3
    assert sum(r[ci] == "t" for r in t1[1:]) == 3
    t3 = list(wb["Test_T3"].iter_rows(values_only=True))
    assert len(t3) == 1 + len(shared) and all(r[6] is None for r in t3[1:])
    cmp_ = list(wb["Compare"].iter_rows(values_only=True))
    h = list(cmp_[0])
    for i in range(1, 6):
        assert f"T{i} label" in h and f"T{i} ความเห็น" in h
    ag = h.index("ตรงกันทุกบัญชีที่ประเมิน (1/0)")
    assert sum(r[ag] == 0 for r in cmp_[1:]) == 3
    assert sum(r[h.index("T2 ความเห็น")] == "t2" for r in cmp_[1:]) == 3
    assert "A" not in {r[0] for r in t1}                               # sanity


def test_t3_t5_share_set(tmp_path):
    eng, _ = _db_with_pool(tmp_path)
    shared = db.ensure_test_assignment(eng)
    assert len(shared) == 20
    for r in ("T1", "T2", "T3", "T4", "T5"):
        assert db.get_assignment(eng, r) == shared


@pytest.mark.skipif(not Path("/mnt/project-files/protocol/BDD_vignettes_full_20261122_V3_claude.xlsx").exists(),
                    reason="project file not available")
def test_on_real_v3_blueprint():
    raw = pd.read_excel("/mnt/project-files/protocol/BDD_vignettes_full_20261122_V3_claude.xlsx",
                        sheet_name="Blueprint", dtype=str)
    pool = raw.rename(columns={"ID": "vid", "บริเวณที่กังวล": "area", "Class (blueprint)": "cls"})
    sets = default_sets(pool[["vid", "area", "cls"]])
    for r in sets:
        assert len(sets[r]) == TEST_N
    print(sets)
