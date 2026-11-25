"""PI page: import vignettes, monitor progress, agreement, consensus, export."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import analysis
import db
from config import BP_COLS, CATS2, CRITERIA, RATERS, TARGET_PER_CLASS, TEST_RATERS


def render(eng, user: dict):
    tabs = st.tabs(["1 · นำเข้า vignette", "2 · ความคืบหน้า", "3 · Agreement (κ)",
                    "4 · Consensus และชุด 150", "5 · Export"])
    with tabs[0]:
        _import_tab(eng, user)
    d = analysis.load_all(eng)
    m = analysis.merged(d) if not d["vig"].empty else pd.DataFrame()
    with tabs[1]:
        _progress_tab(eng, user, d, m)
    with tabs[2]:
        _agreement_tab(d, m)
    with tabs[3]:
        _consensus_tab(eng, user, m)
    with tabs[4]:
        _export_tab(eng)


# ---------------------------------------------------------------- 1 import
def parse_blueprint(file) -> pd.DataFrame:
    raw = pd.read_excel(file, sheet_name="Blueprint", dtype=str)
    missing = [c for c in BP_COLS.values() if c not in raw.columns]
    if missing:
        raise ValueError(f"ชีต Blueprint ไม่มีคอลัมน์: {missing}")
    df = raw[list(BP_COLS.values())].rename(columns={v: k for k, v in BP_COLS.items()})
    df = df.fillna("")
    df["text"] = df.text.str.strip()
    df["vid"] = df.vid.str.strip()
    return df[(df.vid != "") & (df.text != "")].reset_index(drop=True)


def _import_tab(eng, user):
    st.markdown("อัปโหลดไฟล์ `BDD_vignette_templates_*.xlsx` (อ่านชีต **Blueprint**; "
                "นำเข้าเฉพาะแถวที่มีข้อความ vignette) · อัปโหลดซ้ำได้เมื่อแก้ข้อความ")
    f = st.file_uploader("ไฟล์ Excel", type=["xlsx"])
    if f:
        try:
            df = parse_blueprint(f)
        except Exception as e:  # noqa: BLE001
            st.error(f"อ่านไฟล์ไม่ได้: {e}")
            return
        st.write(f"พบ vignette ที่มีข้อความ **{len(df)}** เรื่อง")
        st.dataframe(df.groupby(["cls", "set_role"]).size().rename("n").reset_index(),
                     hide_index=True)
        if st.button("นำเข้า / อัปเดต", type="primary"):
            res = db.upsert_vignettes(eng, df, user["username"])
            st.success(f"เพิ่ม {res['added']} · อัปเดตข้อความ {res['updated']}")
            if res["changed_rated"]:
                st.session_state["changed_rated"] = res["changed_rated"]

    changed = st.session_state.get("changed_rated")
    if changed:
        st.warning(f"เรื่องที่แก้ข้อความหลังจากมีผู้ประเมินแล้ว: {', '.join(changed)}")
        reason = st.text_input("เหตุผล (บันทึกใน audit log)", key="reset_reason")
        if st.button("ให้ประเมินเรื่องเหล่านี้ใหม่ (ลบผลเดิม เก็บสำเนาใน audit log)"):
            n = db.reset_ratings(eng, changed, user["username"], reason)
            st.session_state.pop("changed_rated")
            st.success(f"ลบผลเดิม {n} รายการ ผู้ประเมินต้องประเมินเรื่องเหล่านี้ใหม่ "
                       "(ถ้า lock แล้ว ให้ปลด lock ในแท็บความคืบหน้า)")

    vig = db.table(eng, db.Vignette)
    if not vig.empty:
        with st.expander(f"ซ่อน/แสดง vignette ({int(vig.active.sum())} active จาก {len(vig)})"):
            off = st.multiselect("vignette ที่ไม่ให้ผู้ประเมินเห็น (inactive)",
                                 vig.vid.tolist(), default=vig[~vig.active].vid.tolist())
            if st.button("บันทึกสถานะ active"):
                db.set_active(eng, vig.vid.tolist(), True, user["username"])
                if off:
                    db.set_active(eng, off, False, user["username"])
                st.rerun()


# ---------------------------------------------------------------- 2 progress
def _progress_tab(eng, user, d, m):
    if m.empty:
        st.info("ยังไม่มี vignette")
        return
    locks = dict(zip(d["status"].rater, d["status"].locked)) if not d["status"].empty else {}
    cols = st.columns(len(RATERS))
    for c, r in zip(cols, RATERS):
        n = int(m[f"label_{r}"].notna().sum())
        c.metric(f"Rater {r}", f"{n} / {len(m)}")
        c.caption("🔒 lock แล้ว" if locks.get(r) else "ยังไม่ lock")
        c.progress(n / len(m))
        if locks.get(r):
            reason = c.text_input("เหตุผลที่ปลด lock", key=f"unlock_reason_{r}")
            if c.button(f"ปลด lock Rater {r}", disabled=not reason.strip(), key=f"unlock_{r}"):
                db.set_lock(eng, r, False, user["username"], reason)
                st.rerun()
    st.caption("PI เห็นจำนวนได้ แต่ผู้ประเมินแต่ละคนเห็นเฉพาะผลของตนเอง")

    # ---- test accounts (kept out of κ / consensus / export) ----
    st.divider()
    st.markdown("**🧪 บัญชีทดสอบ** (ไม่นำไปรวมกับข้อมูลจริง)")
    rat = d["rat"]
    sets = {r: db.ensure_test_assignment(eng, r) for r in TEST_RATERS}
    tcols = st.columns(len(TEST_RATERS) + 1)
    for c, r in zip(tcols, TEST_RATERS):
        n = int(((rat.rater == r) & rat.vid.isin(sets[r])).sum()) if not rat.empty else 0
        c.metric(f"Test {r}", f"{n} / {len(sets[r])}")
        c.caption("🔒 lock แล้ว" if locks.get(r) else "ยังไม่ lock")
    with tcols[-1]:
        ok = st.checkbox("ยืนยันล้างผลของบัญชีทดสอบทั้งหมด", key="confirm_clear_test")
        if st.button("ล้างข้อมูลทดสอบ", disabled=not ok):
            n = db.clear_ratings_of(eng, TEST_RATERS, user["username"])
            st.success(f"ลบผลทดสอบ {n} รายการ และปลด lock แล้ว (สำเนาอยู่ใน audit log)")
            st.rerun()
    _test_sets_editor(eng, user, m, sets)


def _test_sets_editor(eng, user, m, sets):
    shared = sets[TEST_RATERS[0]]
    with st.expander(f"ชุด vignette ของบัญชีทดสอบ (ใช้ชุดเดียวกันทุกบัญชี · {len(shared)} เรื่อง)"):
        bp = m.set_index("vid")
        v = [x for x in shared if x in bp.index]
        if v:
            t = bp.loc[v, ["area", "cls"]].reset_index()
            st.dataframe(t.groupby(["area", "cls"]).size().rename("n").reset_index(),
                         hide_index=True)
        new = st.multiselect("แก้ชุด (มีผลกับทุกบัญชีทดสอบ)", m.vid.tolist(), default=v,
                             key="set_shared")
        if st.button("บันทึกชุด", key="save_set_shared", disabled=sorted(new) == v):
            db.set_shared_assignment(eng, new, user["username"])
            st.rerun()
        seed = st.number_input("seed สำหรับสุ่มชุดใหม่", value=20261122, step=1)
        if st.button("สุ่มชุดใหม่ (20 เรื่อง ครบทุก domain, BDD+ 10 : BDD− 10)"):
            from test_sets import shared_default
            db.set_shared_assignment(eng, shared_default(db.test_pool(eng), int(seed)),
                                     user["username"])
            st.rerun()


# ---------------------------------------------------------------- 3 agreement
def _fmt(x, nd=3):
    return "" if x is None or pd.isna(x) else f"{x:.{nd}f}"


def _agreement_tab(d, m):
    mode = st.radio("ชุดข้อมูล", ["ใช้จริง (A vs B)", "🧪 ทดสอบ (T1 vs T2)"], horizontal=True)
    if mode.startswith("🧪"):
        if m.empty:
            st.info("ยังไม่มี vignette")
            return
        m = analysis.merged(d, tuple(TEST_RATERS))
        st.caption("ผลจากบัญชีทดสอบ ใช้ตรวจว่าระบบทำงานถูกต้องเท่านั้น ไม่รวมใน export ข้อมูลจริง")
    if m.empty or not m.both_rated.any():
        st.info("ยังไม่มีเรื่องที่ประเมินครบทั้งสองคน")
        return
    if not (m.label_A.notna().all() and m.label_B.notna().all()):
        st.warning("ผลระหว่างทาง: ยังประเมินไม่ครบทุกเรื่อง")
    n_boot = st.select_slider("จำนวนรอบ bootstrap", [500, 1000, 2000, 5000], value=2000)
    agr, tables = _cached_agreement(m, n_boot)
    show = pd.DataFrame({
        "การวิเคราะห์": agr.analysis,
        "n": agr.n,
        "po": agr.po.map(_fmt),
        "pe": agr.pe.map(_fmt),
        "κ": agr.kappa.map(_fmt),
        "95% CI (Wald)": [f"{_fmt(a)} – {_fmt(b)}" for a, b in zip(agr.ci_low, agr.ci_high)],
        "95% CI (bootstrap)": [f"{_fmt(a)} – {_fmt(b)}" for a, b in zip(agr.boot_low, agr.boot_high)],
        "PABAK": agr.pabak.map(_fmt),
    })
    st.dataframe(show, hide_index=True, width="stretch")
    st.caption("Primary = κ ของ label 3 หมวดตาม protocol · Wald CI ใช้ asymptotic SE ของ "
               "Fleiss–Cohen–Everitt (1969) · bootstrap = percentile, resample ระดับ vignette, "
               "seed 20261122 · κ รายเกณฑ์เป็น exploratory")
    cols = st.columns(len(tables))
    for c, (name, t) in zip(cols, tables.items()):
        c.markdown(f"**{name}**")
        c.dataframe(t)


@st.cache_data(show_spinner="กำลังคำนวณ bootstrap...")
def _cached_agreement(m: pd.DataFrame, n_boot: int):
    return analysis.agreement(m, n_boot)


# ---------------------------------------------------------------- 4 consensus
def _rating_md(row, r):
    if pd.isna(row[f"label_{r}"]):
        return "_ยังไม่ประเมิน_"
    tick = lambda v: "☑" if v else "☐"
    crit = " ".join(f"{k.upper()}{tick(row[f'crit_{k}_{r}'])}" for k in CRITERIA)
    ins = f" · insight: {row[f'insight_{r}']}" if row[f"insight_{r}"] else ""
    note = f"\n\n> {row[f'note_{r}']}" if row[f"note_{r}"] else ""
    return (f"**{row[f'label_{r}']}** · {crit}{ins} · confidence {int(row[f'confidence_{r}'])}"
            f"{note}")


def _consensus_tab(eng, user, m):
    if m.empty:
        st.info("ยังไม่มี vignette")
        return
    need = m[m.needs_consensus]
    done = need[need.cons_label.isin(CATS2)]
    st.markdown(f"**เรื่องที่ต้องตัดสิน:** {len(need)} (ตัดสินแล้ว {len(done)}) · "
                "รวมเรื่องที่ทั้งสองคนเห็นต่าง และเรื่องที่ตอบ 'ข้อมูลไม่พอ'")
    only_open = st.toggle("แสดงเฉพาะที่ยังไม่ได้ตัดสิน", value=True)
    show = need[~need.cons_label.isin(CATS2)] if only_open else need
    for _, row in show.iterrows():
        with st.expander(f"{row.vid} · A: {row.label_A} | B: {row.label_B}"
                         f"{' · ✓ ' + row.cons_label if row.cons_label else ''}"):
            st.markdown(f"<div style='white-space:pre-wrap'>{row.text}</div>",
                        unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            c1.markdown("**Rater A**  \n" + _rating_md(row, "A"))
            c2.markdown("**Rater B**  \n" + _rating_md(row, "B"))
            with st.form(f"cons_{row.vid}"):
                opts = ["", "BDD", "Non-BDD", "ส่งกลับแก้ vignette"]
                lab = st.selectbox("Consensus label", opts,
                                   index=opts.index(row.cons_label) if row.cons_label in opts else 0)
                note = st.text_area("หมายเหตุการตัดสิน", value=row.cons_note)
                if st.form_submit_button("บันทึก"):
                    db.save_consensus(eng, row.vid, user["username"], label=lab, note=note)
                    st.rerun()

    st.divider()
    st.markdown("### Final label และการเลือกเข้าชุดทดสอบ")
    inc = m[m.include]
    c = st.columns(4)
    c[0].metric("Final BDD ในชุด", f"{int((inc.final_label == 'BDD').sum())} / {TARGET_PER_CLASS}")
    c[1].metric("Final Non-BDD ในชุด",
                f"{int((inc.final_label == 'Non-BDD').sum())} / {TARGET_PER_CLASS}")
    c[2].metric("รอ consensus / รอประเมิน",
                int(m.final_label.isin(["รอ consensus", "รอประเมิน"]).sum()))
    c[3].metric("Final ไม่ตรง blueprint", int((m.blueprint_match == 0).sum()))

    if st.button("เลือกอัตโนมัติ: เรื่อง 'หลัก' ที่ final label ตรง blueprint"):
        for _, r in m.iterrows():
            want = bool(r.set_role == "หลัก" and r.blueprint_match == 1)
            if want != r.include:
                db.save_consensus(eng, r.vid, user["username"], include=want,
                                  label=r.cons_label, note=r.cons_note)
        st.rerun()

    view = m[["vid", "set_role", "cls", "stratum_code", "label_A", "label_B", "final_label",
              "blueprint_match", "include"]].copy()
    view["blueprint_match"] = view.blueprint_match.map({1: "✓", 0: "✗"}).fillna("")
    ed = st.data_editor(
        view, hide_index=True, width="stretch", key="include_editor",
        disabled=[c for c in view.columns if c != "include"],
        column_config={"include": st.column_config.CheckboxColumn("รวมในชุด 150"),
                       "vid": "ID", "set_role": "หลัก/สำรอง", "cls": "Class (blueprint)",
                       "stratum_code": "Stratum", "label_A": "A", "label_B": "B",
                       "final_label": "Final", "blueprint_match": "ตรง blueprint"})
    changed = ed[ed.include != view.include]
    if len(changed) and st.button(f"บันทึกการเลือก ({len(changed)} เรื่อง)", type="primary"):
        bad = changed[changed.include & ~m.set_index("vid").loc[changed.vid, "final_label"]
                      .isin(CATS2).values]
        if len(bad):
            st.error(f"เลือกได้เฉพาะเรื่องที่มี final label แล้ว: {', '.join(bad.vid)}")
        else:
            mm = m.set_index("vid")
            for _, r in changed.iterrows():
                db.save_consensus(eng, r.vid, user["username"], include=bool(r.include),
                                  label=mm.at[r.vid, "cons_label"], note=mm.at[r.vid, "cons_note"])
            st.rerun()


# ---------------------------------------------------------------- 5 export
def _export_tab(eng):
    st.markdown("ไฟล์ Excel: Summary, Agreement, Rater_A, Rater_B, Kappa (คอลัมน์เดียวกับ template), "
                "Blueprint_check, Audit_log")
    if st.button("สร้างไฟล์ Excel"):
        data = analysis.build_export(eng)
        st.download_button("ดาวน์โหลด", data,
                           file_name=f"BDD_rating_export_{datetime.now():%Y%m%d_%H%M}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()
    st.markdown("**🧪 แบบประเมินของบัญชีทดสอบ (test1, test2)** · แยกไฟล์จากข้อมูลจริง: "
                "Summary, Test_T1, Test_T2, Compare")
    if st.button("สร้างไฟล์ Excel ของบัญชีทดสอบ"):
        data = analysis.build_test_export(eng)
        st.download_button("ดาวน์โหลด (บัญชีทดสอบ)", data,
                           file_name=f"BDD_rating_TEST_{datetime.now():%Y%m%d_%H%M}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
