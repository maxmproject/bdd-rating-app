"""Default vignette subsets for test accounts (T1/T2).

Since V1.3 both test accounts share ONE set (shared_default = union of the two
per-domain sets below, 20 vignettes).

Each test rater gets TEST_N vignettes from its own concern areas (domains), so the two
sets never overlap and cover different domains; within each set BDD+/BDD- are balanced
and spread round-robin across that rater's areas. Deterministic (seed)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import TEST_AREAS, TEST_N

CLS = ["BDD-positive", "BDD-negative"]


def default_sets(pool: pd.DataFrame, seed: int = 20261122,
                 areas: dict | None = None, n: int = TEST_N) -> dict[str, list[str]]:
    """pool columns: vid, area, cls (active vignettes with blueprint info)."""
    areas = areas or TEST_AREAS
    rng = np.random.default_rng(seed)
    out = {}
    for rater, wanted in areas.items():
        sub = pool[pool.area.isin(wanted)]
        picks: list[str] = []
        for k, cls in enumerate(CLS):
            need = n // 2 + (n % 2 if k == 0 else 0)
            # one shuffled queue per area, then take round-robin across areas
            queues = [list(rng.permutation(sub[(sub.area == a) & (sub.cls == cls)].vid.to_numpy()))
                      for a in wanted]
            while need and any(queues):
                for q in queues:
                    if q and need:
                        picks.append(str(q.pop()))
                        need -= 1
        out[rater] = sorted(picks)
    return out


def shared_default(pool: pd.DataFrame, seed: int = 20261122) -> list[str]:
    """One set for *all* test accounts: union of the per-domain sets above
    (10 + 10 = 20 vignettes covering every domain, 10 BDD+ : 10 BDD-)."""
    return sorted(v for vids in default_sets(pool, seed).values() for v in vids)
