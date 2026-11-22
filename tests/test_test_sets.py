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


def test_ensure_assignment_and_rater_filter(tmp_path):
    eng = db.get_engine(f"sqlite:///{tmp_path/'t.db'}")
    pool = _pool(3)
    df = pool.assign(text="x", set_role="หลัก", stratum_code="", cls=pool.cls)
    db.upsert_vignettes(eng, df[["vid", "text", "set_role", "cls", "stratum_code", "area"]], "pi")
    t1 = db.ensure_test_assignment(eng, "T1")
    t2 = db.get_assignment(eng, "T2")
    assert len(t1) == len(t2) == TEST_N and set(t1).isdisjoint(t2)
    db.set_assignment(eng, "T1", t1[:3], "pi")
    assert db.ensure_test_assignment(eng, "T1") == t1[:3]          # PI edit is kept


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
