"""Merge ratings, compute agreement and final labels; build Excel export."""
from __future__ import annotations

import io
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import db
from config import APP_DATE, APP_VERSION, CATS, CATS2, TARGET_PER_CLASS
from stats_kappa import cohen_kappa

NOTE_COL = "ความเห็นของผู้ประเมิน (หมายเหตุ)"
RATER_COLS = ["vid", "crit_a", "crit_b", "crit_c", "crit_d", "label", "insight",
              "confidence", "note", "created_at", "updated_at", "n_edits"]


def load_all(eng) -> dict[str, pd.DataFrame]:
    return {
        "vig": db.table(eng, db.Vignette),
        "bp": db.table(eng, db.Blueprint),
        "rat": db.table(eng, db.Rating),
        "status": db.table(eng, db.RaterStatus),
        "cons": db.table(eng, db.Consensus),
        "audit": db.table(eng, db.Audit),
    }


def merged(d: dict, pair: tuple[str, str] = ("A", "B")) -> pd.DataFrame:
    """One row per active vignette: ratings of `pair` (columns suffixed _A/_B), agreement,
    consensus, final label. Consensus/include are only joined for the real pair (A, B);
    a test pair (T1, T2) gets an empty consensus so test data can never leak into results."""
    vig = d["vig"][d["vig"].active] if not d["vig"].empty else d["vig"]
    m = vig[["vid", "set_role", "text"]].merge(d["bp"], on="vid", how="left")
    for col, r in zip(("A", "B"), pair):
        rr = d["rat"][d["rat"].rater == r][RATER_COLS] if not d["rat"].empty \
            else pd.DataFrame(columns=RATER_COLS)
        rr = rr.rename(columns={c: f"{c}_{col}" for c in RATER_COLS if c != "vid"})
        m = m.merge(rr, on="vid", how="left")
    real = tuple(pair) == ("A", "B")
    cons = d["cons"].rename(columns={"label": "cons_label", "note": "cons_note",
                                     "updated_at": "cons_at"}) if (real and not d["cons"].empty) \
        else pd.DataFrame(columns=["vid", "cons_label", "cons_note", "include", "cons_at"])
    m = m.merge(cons, on="vid", how="left")
    m["include"] = m["include"].fillna(False).astype(bool)
    m["cons_label"] = m["cons_label"].fillna("")
    m["cons_note"] = m["cons_note"].fillna("")

    both = m.label_A.notna() & m.label_B.notna()
    m["both_rated"] = both
    m["agree"] = np.where(both, (m.label_A == m.label_B).astype(float), np.nan)
    # needs consensus: disagreement, or both agree on "ข้อมูลไม่พอ"
    m["needs_consensus"] = both & ((m.label_A != m.label_B) | (m.label_A == "ข้อมูลไม่พอ"))

    def final(row):
        if not row.both_rated:
            return "รอประเมิน"
        if not row.needs_consensus:
            return row.label_A
        return row.cons_label if row.cons_label in CATS2 else "รอ consensus"

    m["final_label"] = m.apply(final, axis=1)
    bp_lab = m.cls.map({"BDD-positive": "BDD", "BDD-negative": "Non-BDD"})
    ok = m.final_label.isin(CATS2) & bp_lab.notna()
    m["blueprint_match"] = np.where(ok, (m.final_label == bp_lab).astype(float), np.nan)
    return m.sort_values("vid").reset_index(drop=True)


def agreement(m: pd.DataFrame, n_boot: int = 2000) -> tuple[pd.DataFrame, dict]:
    """Rows: 3-cat κ, 2-cat κ, per-criterion κ (exploratory)."""
    b = m[m.both_rated]
    out, tables = [], {}
    if len(b) == 0:
        return pd.DataFrame(), {}
    r3 = cohen_kappa(b.label_A, b.label_B, CATS, n_boot)
    out.append({"analysis": "Label 3 หมวด (primary)", **r3.as_row()})
    tables["Label 3 หมวด"] = r3.table
    b2 = b[b.label_A.isin(CATS2) & b.label_B.isin(CATS2)]
    if len(b2):
        r2 = cohen_kappa(b2.label_A, b2.label_B, CATS2, n_boot)
        out.append({"analysis": "Label 2 หมวด (ตัด ข้อมูลไม่พอ)", **r2.as_row()})
        tables["Label 2 หมวด"] = r2.table
    for k in "abcd":
        ca = b[f"crit_{k}_A"].map({True: "☑", False: "☐"})
        cb = b[f"crit_{k}_B"].map({True: "☑", False: "☐"})
        rk = cohen_kappa(ca, cb, ["☑", "☐"], n_boot)
        out.append({"analysis": f"Criterion {k.upper()} (exploratory)", **rk.as_row()})
    df = pd.DataFrame(out)
    return df, tables


def _rater_sheet(m: pd.DataFrame, r: str) -> pd.DataFrame:
    s = m[["vid", "text"] + [f"{c}_{r}" for c in RATER_COLS if c != "vid"]].copy()
    tick = {True: "☑", False: "☐"}
    for k in "abcd":
        s[f"crit_{k}_{r}"] = s[f"crit_{k}_{r}"].map(tick)
    s.columns = ["ID", "Vignette", "A", "B", "C", "D", "Label",
                 "Insight (ถ้า BDD)", "Confidence 1–5", NOTE_COL, "บันทึกครั้งแรก (UTC)",
                 "แก้ไขล่าสุด (UTC)", "จำนวนครั้งที่แก้"]
    return s


def _naive(df: pd.DataFrame) -> pd.DataFrame:
    """Excel cannot store tz-aware datetimes."""
    df = df.copy()
    for c in df.columns:
        if isinstance(df[c].dtype, pd.DatetimeTZDtype):
            df[c] = df[c].dt.tz_convert("UTC").dt.tz_localize(None)
        elif df[c].dtype == object:
            df[c] = df[c].map(lambda x: x.replace(tzinfo=None) if isinstance(x, datetime) else x)
    return df


def build_export(eng, n_boot: int = 2000) -> bytes:
    d = load_all(eng)
    m = merged(d)
    agr, tables = agreement(m, n_boot)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    inc = m[m.include]
    locks = dict(zip(d["status"].rater, d["status"].locked)) if not d["status"].empty else {}
    summary = pd.DataFrame([
        ["โปรแกรม", f"BDD vignette rating app {APP_VERSION} ({APP_DATE})"],
        ["Export เมื่อ", ts],
        ["Vignette active", len(m)],
        ["ประเมินครบทั้งสองคน", int(m.both_rated.sum())],
        ["Lock: Rater A / B", " / ".join("☑" if locks.get(r) else "☐" for r in ("A", "B"))],
        ["รอ consensus", int((m.final_label == "รอ consensus").sum())],
        ["Final BDD (รวมในชุดทดสอบ)", int((inc.final_label == "BDD").sum())],
        ["Final Non-BDD (รวมในชุดทดสอบ)", int((inc.final_label == "Non-BDD").sum())],
        ["เป้าหมายต่อ class", TARGET_PER_CLASS],
        ["Final ไม่ตรง blueprint", int((m.blueprint_match == 0).sum())],
        ["หมายเหตุ CI", "Wald CI ใช้ asymptotic SE (Fleiss–Cohen–Everitt 1969); bootstrap = percentile, "
                        f"{n_boot} รอบ, seed 20261122"],
    ], columns=["รายการ", "ค่า"])

    kappa = m[["vid", "label_A", "label_B", "agree", "cons_label", "final_label",
               "include", "cons_note"]].copy()
    kappa["agree"] = kappa["agree"].astype("Int64")
    kappa["include"] = kappa["include"].map({True: "☑", False: "☐"})
    kappa.columns = ["ID", "Rater A label", "Rater B label", "ตรงกัน (1/0)",
                     "Consensus label (ถ้าต่าง)", "Final label", "รวมในชุด 150 (☑/☐)",
                     "หมายเหตุการตัดสิน"]
    bpc = m[["vid", "set_role", "cls", "stratum_code", "area", "final_label",
             "blueprint_match"]].copy()
    bpc["blueprint_match"] = bpc["blueprint_match"].astype("Int64")
    bpc.columns = ["ID", "หลัก/สำรอง", "Class (blueprint)", "Stratum code", "บริเวณ",
                   "Final label", "ตรง blueprint (1/0)"]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        if not agr.empty:
            agr.to_excel(xw, sheet_name="Agreement", index=False)
            row = len(agr) + 3
            for name, t in tables.items():
                pd.DataFrame([[name]]).to_excel(xw, sheet_name="Agreement", startrow=row, index=False, header=False)
                t.to_excel(xw, sheet_name="Agreement", startrow=row + 1)
                row += len(t) + 4
        _naive(_rater_sheet(m, "A")).to_excel(xw, sheet_name="Rater_A", index=False)
        _naive(_rater_sheet(m, "B")).to_excel(xw, sheet_name="Rater_B", index=False)
        kappa.to_excel(xw, sheet_name="Kappa", index=False)
        bpc.to_excel(xw, sheet_name="Blueprint_check", index=False)
        _naive(d["audit"]).to_excel(xw, sheet_name="Audit_log", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = min(60, max(10, max(len(str(c.value or "")) for c in col[:50]) + 2))
                ws.column_dimensions[col[0].column_letter].width = width
            ws.oddFooter.left.text = f"BDD rating export {APP_VERSION} · {ts}"
    return buf.getvalue()


def build_test_export(eng) -> bytes:
    """Excel of the test accounts' rating forms only (never mixed with real data).

    One sheet per test account (incl. the rater's own comment column) + Compare
    (label and comment of every test account side by side).
    """
    from config import TEST_RATERS
    d = load_all(eng)
    shared = db.ensure_test_assignment(eng)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sheets, n_done = {}, {}
    cmp_ = None
    for r in TEST_RATERS:
        # merged() with pair (r, r) puts this rater's columns in *_A
        m = merged(d, (r, r))
        m = m[m.vid.isin(shared)].reset_index(drop=True)
        sheets[r] = _rater_sheet(m, "A")
        n_done[r] = int(m.label_A.notna().sum())
        if cmp_ is None:
            cmp_ = m[["vid", "area", "cls"]].copy()
            cmp_.columns = ["ID", "บริเวณ", "Class (blueprint)"]
        cmp_[f"{r} label"] = m.label_A.values
        cmp_[f"{r} ความเห็น"] = m.note_A.fillna("").values
    labs = cmp_[[f"{r} label" for r in TEST_RATERS]]
    n_rated = labs.notna().sum(axis=1)
    cmp_["จำนวนบัญชีที่ประเมิน"] = n_rated
    # all raters who rated gave the same label (needs >= 2 ratings)
    same = labs.apply(lambda row: row.dropna().nunique() == 1, axis=1)
    cmp_["ตรงกันทุกบัญชีที่ประเมิน (1/0)"] = pd.Series(
        np.where(n_rated >= 2, same.astype(float), np.nan)).astype("Int64")
    bp_lab = cmp_["Class (blueprint)"].map({"BDD-positive": "BDD", "BDD-negative": "Non-BDD"})
    for r in TEST_RATERS:
        ok = cmp_[f"{r} label"].notna() & bp_lab.notna()
        cmp_.insert(cmp_.columns.get_loc(f"{r} ความเห็น") + 1, f"{r} ตรง blueprint (1/0)",
                    pd.Series(np.where(ok, (cmp_[f"{r} label"] == bp_lab).astype(float),
                                       np.nan)).astype("Int64"))
    summary = pd.DataFrame(
        [["ไฟล์", f"แบบประเมินบัญชีทดสอบ ({', '.join(TEST_RATERS)}) · ไม่ใช่ข้อมูลวิจัย"],
         ["โปรแกรม", f"BDD vignette rating app {APP_VERSION} ({APP_DATE})"],
         ["Export เมื่อ", ts],
         ["จำนวน vignette ในชุดทดสอบ (ชุดเดียวกันทุกบัญชี)", len(cmp_)]]
        + [[f"ประเมินแล้ว {r}", n_done[r]] for r in TEST_RATERS]
        + [["ประเมินครบทุกบัญชี", int((n_rated == len(TEST_RATERS)).sum())],
           ["label ตรงกันทุกบัญชี (เฉพาะเรื่องที่ประเมินครบทุกบัญชี)",
            int((same & (n_rated == len(TEST_RATERS))).sum())],
           ["คอลัมน์ความเห็น", f"ชีต Test_*: \"{NOTE_COL}\" · ชีต Compare: \"<บัญชี> ความเห็น\""]],
        columns=["รายการ", "ค่า"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        for r in TEST_RATERS:
            _naive(sheets[r]).to_excel(xw, sheet_name=f"Test_{r}", index=False)
        cmp_.to_excel(xw, sheet_name="Compare", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = min(60, max(10, max(len(str(c.value or "")) for c in col[:50]) + 2))
                ws.column_dimensions[col[0].column_letter].width = width
            ws.oddFooter.left.text = f"BDD rating TEST export {APP_VERSION} · {ts}"
    return buf.getvalue()
