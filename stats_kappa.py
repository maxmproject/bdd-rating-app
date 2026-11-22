"""Inter-rater agreement statistics for the BDD vignette rating app.

Pure numpy/pandas so it can be unit-tested without Streamlit.

- Cohen's kappa (unweighted) with
  * asymptotic SE under the non-null hypothesis (Fleiss, Cohen & Everitt 1969),
    Wald 95% CI
  * percentile bootstrap 95% CI (resampling vignettes)
- PABAK (prevalence- and bias-adjusted kappa) for 2-category tables
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence

import numpy as np
import pandas as pd

Z975 = 1.959963984540054


@dataclass
class KappaResult:
    n: int
    categories: list
    po: float
    pe: float
    kappa: float
    se: float
    ci_low: float
    ci_high: float
    boot_low: float
    boot_high: float
    pabak: float | None
    table: pd.DataFrame

    def as_row(self) -> dict:
        d = asdict(self)
        d.pop("table")
        d["categories"] = " / ".join(map(str, self.categories))
        return d


def confusion(a: Sequence, b: Sequence, categories: Sequence) -> np.ndarray:
    """Counts table: rows = rater A, cols = rater B."""
    idx = {c: i for i, c in enumerate(categories)}
    m = np.zeros((len(categories), len(categories)), dtype=float)
    for x, y in zip(a, b):
        m[idx[x], idx[y]] += 1
    return m


def _kappa_from_table(m: np.ndarray) -> tuple[float, float, float]:
    n = m.sum()
    if n == 0:
        return np.nan, np.nan, np.nan
    p = m / n
    po = np.trace(p)
    pe = float(p.sum(1) @ p.sum(0))
    if np.isclose(pe, 1.0):
        return po, pe, np.nan
    return po, pe, (po - pe) / (1 - pe)


def kappa_se_fce(m: np.ndarray) -> float:
    """Large-sample SE of kappa, Fleiss, Cohen & Everitt (1969), non-null."""
    n = m.sum()
    p = m / n
    r, c = p.sum(1), p.sum(0)
    po, pe, k = _kappa_from_table(m)
    if np.isnan(k):
        return np.nan
    a = np.sum(np.diag(p) * (1 - (r + c) * (1 - k)) ** 2)
    off = p.copy()
    np.fill_diagonal(off, 0)
    # term: sum_{i!=j} p_ij (p_.i + p_j.)^2  -> col-margin of row i + row-margin of col j
    b = (1 - k) ** 2 * np.sum(off * (c[:, None] + r[None, :]) ** 2)
    cc = (k - pe * (1 - k)) ** 2
    var = (a + b - cc) / (n * (1 - pe) ** 2)
    return float(np.sqrt(max(var, 0.0)))


def cohen_kappa(a: Sequence, b: Sequence, categories: Sequence,
                n_boot: int = 2000, seed: int = 20261122) -> KappaResult:
    a = list(a)
    b = list(b)
    cats = list(categories)
    m = confusion(a, b, cats)
    n = int(m.sum())
    po, pe, k = _kappa_from_table(m)
    se = kappa_se_fce(m) if n > 0 else np.nan
    lo, hi = (k - Z975 * se, k + Z975 * se) if np.isfinite(se) else (np.nan, np.nan)

    # Percentile bootstrap over vignettes
    blo = bhi = np.nan
    if n >= 2 and n_boot > 0:
        rng = np.random.default_rng(seed)
        idx = {c: i for i, c in enumerate(cats)}
        ai = np.array([idx[x] for x in a])
        bi = np.array([idx[y] for y in b])
        kk = len(cats)
        ks = np.empty(n_boot)
        for t in range(n_boot):
            s = rng.integers(0, n, n)
            mb = np.zeros((kk, kk))
            np.add.at(mb, (ai[s], bi[s]), 1)
            ks[t] = _kappa_from_table(mb)[2]
        ks = ks[np.isfinite(ks)]
        if ks.size:
            blo, bhi = np.percentile(ks, [2.5, 97.5])

    pabak = (2 * po - 1) if len(cats) == 2 and n > 0 else None
    table = pd.DataFrame(m.astype(int), index=[f"A: {c}" for c in cats],
                         columns=[f"B: {c}" for c in cats])
    clip = lambda v: float(np.clip(v, -1, 1)) if np.isfinite(v) else np.nan
    return KappaResult(n, cats, float(po), float(pe), float(k), float(se),
                       clip(lo), clip(hi), float(blo), float(bhi), pabak, table)
