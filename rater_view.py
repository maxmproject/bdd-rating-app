"""Rater page: blind, independent labelling of vignettes (DSM-5-TR A–D)."""
from __future__ import annotations

import hashlib

import numpy as np
import streamlit as st

import db
from config import CATS, CRITERIA, INSIGHT, ORDER_SEED, TEST_RATERS


def rater_order(vids: list[str], rater: str) -> list[str]:
    """Deterministic, rater-specific shuffle (reduces order effects, stable across sessions)."""
    seed = int(hashlib.sha256(f"{ORDER_SEED}-{rater}".encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    v = sorted(vids)
    return [v[i] for i in rng.permutation(len(v))]


def render(eng, user: dict):
    rater = user["rater"]
    vdf = db.vignettes_for_rater(eng)
    if vdf.empty:
        st.info("ยังไม่มี vignette ให้ประเมิน กรุณารอ PI นำเข้าข้อมูล")
        return
    if rater in TEST_RATERS:          # test accounts see only their assigned subset
        assigned = set(db.ensure_test_assignment(eng, rater))
        vdf = vdf[vdf.vid.isin(assigned)]
        if vdf.empty:
            st.info("PI ยังไม่ได้กำหนดชุด vignette สำหรับบัญชีทดสอบนี้")
            return
    texts = dict(zip(vdf.vid, vdf.text))
    order = rater_order(list(texts), rater)
    ratings = db.get_ratings(eng, rater)
    done = [v for v in order if v in ratings]
    locked = db.is_locked(eng, rater)

    # ---- sidebar: progress + navigation ----
    ss = st.session_state
    ss.setdefault("pos", next((i for i, v in enumerate(order) if v not in ratings), 0))
    ss.pos = min(ss.pos, len(order) - 1)

    with st.sidebar:
        st.metric("ความคืบหน้า", f"{len(done)} / {len(order)}")
        st.progress(len(done) / len(order))
        labels = [f"{i+1:>3}. {v} {'✓' if v in ratings else '·'}" for i, v in enumerate(order)]
        pick = st.selectbox("ไปที่เรื่อง", range(len(order)), index=ss.pos,
                            format_func=lambda i: labels[i], key=f"jump_{ss.pos}")
        if pick != ss.pos:
            ss.pos = pick
            st.rerun()
        if st.button("ไปเรื่องที่ยังไม่ได้ประเมิน", width="stretch"):
            nxt = next((i for i, v in enumerate(order) if v not in ratings), None)
            if nxt is not None:
                ss.pos = nxt
                st.rerun()
        st.divider()
        _lock_box(eng, user, rater, locked, len(done), len(order))

    if locked:
        st.success("ส่งผลครบและ lock แล้ว ขอบคุณครับ/ค่ะ หากต้องแก้ไขกรุณาติดต่อ PI")
        return

    vid = order[ss.pos]
    old = ratings.get(vid)
    st.subheader(f"เรื่องที่ {ss.pos+1} / {len(order)} · รหัส {vid}")
    with st.container(border=True):
        st.markdown(f"<div style='font-size:1.1rem;line-height:1.8;white-space:pre-wrap'>"
                    f"{_esc(texts[vid])}</div>", unsafe_allow_html=True)
    if old:
        st.caption(f"บันทึกแล้วเมื่อ {old.updated_at:%Y-%m-%d %H:%M} UTC · แก้ไขได้จนกว่าจะ lock")

    st.markdown("**เกณฑ์ DSM-5-TR** (ติ๊ก ☑ เมื่อ vignette มีข้อมูลสนับสนุนว่าผ่านข้อนั้น)")
    crit = {}
    for k, (short, full) in CRITERIA.items():
        crit[k] = st.checkbox(f"**{short}** — {full}",
                              value=bool(getattr(old, f"crit_{k}", False)) if old else False,
                              key=f"{vid}_{k}")

    c1, c2 = st.columns([1, 1])
    with c1:
        label = st.radio("Label", CATS, horizontal=True, key=f"{vid}_label",
                         index=CATS.index(old.label) if old else None)
    with c2:
        conf = st.radio("Confidence (1 = ไม่มั่นใจ, 5 = มั่นใจมาก)", [1, 2, 3, 4, 5],
                        horizontal=True, key=f"{vid}_conf",
                        index=(old.confidence - 1) if old else None)
    insight = ""
    if label == "BDD":
        insight = st.radio("Insight", INSIGHT, horizontal=True, key=f"{vid}_ins",
                           index=INSIGHT.index(old.insight) if old and old.insight in INSIGHT else None)
    note = st.text_area("หมายเหตุ (ถ้ามี)", value=old.note if old else "", key=f"{vid}_note",
                        height=80)

    # consistency between criteria and label
    rule = "BDD" if all(crit.values()) else "Non-BDD"
    confirm_needed = label in ("BDD", "Non-BDD") and label != rule
    confirmed = True
    if confirm_needed:
        st.warning(f"Label ที่เลือก ({label}) ไม่ตรงกับเกณฑ์ที่ติ๊ก "
                   f"(BDD ต้องผ่าน A–D ทั้งหมด) กรุณาตรวจอีกครั้ง")
        confirmed = st.checkbox("ยืนยัน label นี้ (โปรดระบุเหตุผลในหมายเหตุ)", key=f"{vid}_confirm")

    errors = []
    if label is None:
        errors.append("เลือก Label")
    if conf is None:
        errors.append("เลือก Confidence")
    if label == "BDD" and not insight:
        errors.append("เลือก Insight")
    if confirm_needed and (not confirmed or not note.strip()):
        errors.append("ยืนยัน label ที่ไม่ตรงเกณฑ์และใส่เหตุผลในหมายเหตุ")

    b1, b2, b3 = st.columns([1, 2, 1])
    if b1.button("◀ ก่อนหน้า", disabled=ss.pos == 0, width="stretch"):
        ss.pos -= 1
        st.rerun()
    if b2.button("บันทึก แล้วไปเรื่องถัดไป ▶", type="primary", width="stretch"):
        if errors:
            st.error("ยังบันทึกไม่ได้: " + ", ".join(errors))
        else:
            data = {f"crit_{k}": v for k, v in crit.items()}
            data.update(label=label, insight=insight if label == "BDD" else "",
                        confidence=int(conf), note=note.strip())
            db.save_rating(eng, rater, vid, data, user["username"])
            ss.pos = min(ss.pos + 1, len(order) - 1)
            st.toast(f"บันทึก {vid} แล้ว")
            st.rerun()
    if b3.button("ข้าม ▶", disabled=ss.pos >= len(order) - 1, width="stretch"):
        ss.pos += 1
        st.rerun()


def _lock_box(eng, user, rater, locked, n_done, n_total):
    if locked:
        st.info("🔒 lock แล้ว")
        return
    st.markdown("**ส่งผลทั้งหมด**")
    if n_done < n_total:
        st.caption(f"ประเมินให้ครบก่อน (เหลือ {n_total - n_done} เรื่อง)")
        return
    ok = st.checkbox("ตรวจทานแล้ว ต้องการส่งและ lock ผล (แก้ไขต่อไม่ได้)")
    if st.button("ส่งผลและ lock", disabled=not ok, type="primary", width="stretch"):
        db.set_lock(eng, rater, True, user["username"])
        st.rerun()


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
