"""Cross-check stats_kappa against statsmodels / scikit-learn (test-only deps)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stats_kappa import cohen_kappa, confusion  # noqa: E402

CATS = ["BDD", "Non-BDD", "ข้อมูลไม่พอ"]


def _random_pair(n=170, seed=1):
    rng = np.random.default_rng(seed)
    a = rng.choice(CATS, n, p=[0.45, 0.47, 0.08])
    b = np.where(rng.random(n) < 0.8, a, rng.choice(CATS, n))
    return list(a), list(b)


def test_point_estimate_matches_sklearn():
    from sklearn.metrics import cohen_kappa_score
    a, b = _random_pair()
    r = cohen_kappa(a, b, CATS, n_boot=0)
    assert abs(r.kappa - cohen_kappa_score(a, b, labels=CATS)) < 1e-12


def test_se_matches_statsmodels():
    from statsmodels.stats.inter_rater import cohens_kappa
    for seed in range(5):
        a, b = _random_pair(seed=seed)
        r = cohen_kappa(a, b, CATS, n_boot=0)
        sm = cohens_kappa(confusion(a, b, CATS))
        assert abs(r.kappa - sm.kappa) < 1e-12
        assert abs(r.se - sm.std_kappa) < 1e-10, (r.se, sm.std_kappa)


def test_bootstrap_brackets_estimate_and_pabak():
    a, b = _random_pair()
    a2 = ["BDD" if x == "BDD" else "Non-BDD" for x in a]
    b2 = ["BDD" if x == "BDD" else "Non-BDD" for x in b]
    r = cohen_kappa(a2, b2, ["BDD", "Non-BDD"], n_boot=500)
    assert r.boot_low < r.kappa < r.boot_high
    assert abs(r.pabak - (2 * r.po - 1)) < 1e-12


def test_perfect_agreement():
    a = ["BDD"] * 5 + ["Non-BDD"] * 5
    r = cohen_kappa(a, a, ["BDD", "Non-BDD"], n_boot=100)
    assert r.kappa == 1.0 and r.po == 1.0
