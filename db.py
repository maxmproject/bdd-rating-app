"""Storage layer (SQLAlchemy 2.x).

DATABASE_URL comes from st.secrets / env:
  - local test:  sqlite:///rating.db   (default)
  - production:  postgresql+psycopg2://user:pass@host:5432/db  (Supabase / Neon free tier)
Streamlit Community Cloud has an ephemeral disk, so SQLite there LOSES DATA on restart.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import (Boolean, DateTime, Integer, String, Text, create_engine,
                        select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Vignette(Base):
    """What raters see: ID + text only (no class/stratum)."""
    __tablename__ = "vignettes"
    vid: Mapped[str] = mapped_column(String(20), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    set_role: Mapped[str] = mapped_column(String(20), default="หลัก")  # หลัก/สำรอง
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Blueprint(Base):
    """PI-only design info; never queried by rater views."""
    __tablename__ = "blueprint"
    vid: Mapped[str] = mapped_column(String(20), primary_key=True)
    cls: Mapped[str] = mapped_column(String(20), default="")
    stratum_code: Mapped[str] = mapped_column(String(20), default="")
    area: Mapped[str] = mapped_column(String(80), default="")


class Rating(Base):
    __tablename__ = "ratings"
    rater: Mapped[str] = mapped_column(String(10), primary_key=True)   # "A" / "B"
    vid: Mapped[str] = mapped_column(String(20), primary_key=True)
    crit_a: Mapped[bool] = mapped_column(Boolean, default=False)
    crit_b: Mapped[bool] = mapped_column(Boolean, default=False)
    crit_c: Mapped[bool] = mapped_column(Boolean, default=False)
    crit_d: Mapped[bool] = mapped_column(Boolean, default=False)
    label: Mapped[str] = mapped_column(String(20))
    insight: Mapped[str] = mapped_column(String(30), default="")
    confidence: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    n_edits: Mapped[int] = mapped_column(Integer, default=0)


class RaterStatus(Base):
    __tablename__ = "rater_status"
    rater: Mapped[str] = mapped_column(String(10), primary_key=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Consensus(Base):
    __tablename__ = "consensus"
    vid: Mapped[str] = mapped_column(String(20), primary_key=True)
    label: Mapped[str] = mapped_column(String(20), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    include: Mapped[bool] = mapped_column(Boolean, default=False)   # รวมในชุด 150
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TestAssignment(Base):
    """Which vignettes a test account (T1/T2) sees. Real raters always see all active ones."""
    __tablename__ = "test_assignment"
    rater: Mapped[str] = mapped_column(String(10), primary_key=True)
    vid: Mapped[str] = mapped_column(String(20), primary_key=True)


class Audit(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="")


_ENGINES: dict[str, object] = {}


def get_engine(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL") or "sqlite:///rating.db"
    if url not in _ENGINES:
        eng = create_engine(url, pool_pre_ping=True, future=True)
        Base.metadata.create_all(eng)
        _ENGINES[url] = eng
    return _ENGINES[url]


def log(s: Session, user: str, action: str, detail: dict | str = ""):
    if isinstance(detail, dict):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    s.add(Audit(user=user, action=action, detail=detail))


# ---------- vignettes ----------
def upsert_vignettes(eng, df: pd.DataFrame, user: str) -> dict:
    """df columns: vid, text, set_role, cls, stratum_code, area.
    Returns counts and list of vids whose text changed after being rated."""
    added = updated = 0
    changed_rated = []
    with Session(eng) as s:
        rated = set(s.scalars(select(Rating.vid)).all())
        for r in df.itertuples(index=False):
            v = s.get(Vignette, r.vid)
            if v is None:
                s.add(Vignette(vid=r.vid, text=r.text, set_role=r.set_role))
                added += 1
            else:
                if v.text != r.text:
                    if r.vid in rated:
                        changed_rated.append(r.vid)
                    v.text = r.text
                    v.updated_at = now()
                    updated += 1
                v.set_role = r.set_role
                v.active = True
            bp = s.get(Blueprint, r.vid) or Blueprint(vid=r.vid)
            bp.cls, bp.stratum_code, bp.area = r.cls, r.stratum_code, r.area
            s.merge(bp)
        log(s, user, "import_vignettes",
            {"added": added, "updated": updated, "changed_after_rating": changed_rated})
        s.commit()
    return {"added": added, "updated": updated, "changed_rated": changed_rated}


def set_active(eng, vids: list[str], active: bool, user: str):
    with Session(eng) as s:
        for vid in vids:
            v = s.get(Vignette, vid)
            if v:
                v.active = active
        log(s, user, "set_active", {"vids": vids, "active": active})
        s.commit()


def vignettes_for_rater(eng) -> pd.DataFrame:
    """Only fields a rater may see."""
    with Session(eng) as s:
        rows = s.execute(select(Vignette.vid, Vignette.text)
                         .where(Vignette.active.is_(True))
                         .order_by(Vignette.vid)).all()
    return pd.DataFrame(rows, columns=["vid", "text"])


def table(eng, model) -> pd.DataFrame:
    with Session(eng) as s:
        objs = s.scalars(select(model)).all()
        cols = [c.name for c in model.__table__.columns]
        return pd.DataFrame([{c: getattr(o, c) for c in cols} for o in objs], columns=cols)


# ---------- ratings ----------
def get_ratings(eng, rater: str) -> dict[str, Rating]:
    with Session(eng) as s:
        objs = s.scalars(select(Rating).where(Rating.rater == rater)).all()
        s.expunge_all()
        return {o.vid: o for o in objs}


def save_rating(eng, rater: str, vid: str, data: dict, user: str):
    with Session(eng) as s:
        st_ = s.get(RaterStatus, rater)
        if st_ and st_.locked:
            raise PermissionError("ผลของผู้ประเมินนี้ถูก lock แล้ว")
        r = s.get(Rating, (rater, vid))
        if r is None:
            r = Rating(rater=rater, vid=vid, **data)
            s.add(r)
            log(s, user, "rate", {"vid": vid, **data})
        else:
            for k, v in data.items():
                setattr(r, k, v)
            r.updated_at = now()
            r.n_edits = (r.n_edits or 0) + 1
            log(s, user, "edit_rating", {"vid": vid, **data})
        s.commit()


def is_locked(eng, rater: str) -> bool:
    with Session(eng) as s:
        st_ = s.get(RaterStatus, rater)
        return bool(st_ and st_.locked)


def set_lock(eng, rater: str, locked: bool, user: str, reason: str = ""):
    with Session(eng) as s:
        st_ = s.get(RaterStatus, rater) or RaterStatus(rater=rater)
        st_.locked = locked
        st_.locked_at = now() if locked else None
        s.merge(st_)
        log(s, user, "lock" if locked else "unlock", {"rater": rater, "reason": reason})
        s.commit()


# ---------- consensus ----------
def save_consensus(eng, vid: str, user: str, **fields):
    with Session(eng) as s:
        c = s.get(Consensus, vid) or Consensus(vid=vid)
        for k, v in fields.items():
            setattr(c, k, v)
        c.updated_at = now()
        s.merge(c)
        log(s, user, "consensus", {"vid": vid, **fields})
        s.commit()


def reset_ratings(eng, vids: list[str], user: str, reason: str = ""):
    """Delete ratings for given vignettes (both raters) so they are re-rated.
    Old values are preserved in the audit log."""
    with Session(eng) as s:
        objs = s.scalars(select(Rating).where(Rating.vid.in_(vids))).all()
        old = [{c.name: getattr(o, c.name) for c in Rating.__table__.columns} for o in objs]
        for o in objs:
            s.delete(o)
        log(s, user, "reset_ratings", {"vids": vids, "reason": reason, "old": old})
        s.commit()
    return len(old)


def clear_ratings_of(eng, raters: list[str], user: str):
    """Delete all ratings + lock of the given (test) raters. Copies kept in audit log."""
    with Session(eng) as s:
        objs = s.scalars(select(Rating).where(Rating.rater.in_(raters))).all()
        old = [{c.name: getattr(o, c.name) for c in Rating.__table__.columns} for o in objs]
        for o in objs:
            s.delete(o)
        for r in raters:
            st_ = s.get(RaterStatus, r)
            if st_:
                st_.locked, st_.locked_at = False, None
        log(s, user, "clear_test_data", {"raters": raters, "old": old})
        s.commit()
    return len(old)


def get_assignment(eng, rater: str) -> list[str]:
    with Session(eng) as s:
        return sorted(s.scalars(select(TestAssignment.vid)
                                .where(TestAssignment.rater == rater)).all())


def set_assignment(eng, rater: str, vids: list[str], user: str):
    with Session(eng) as s:
        for o in s.scalars(select(TestAssignment).where(TestAssignment.rater == rater)).all():
            s.delete(o)
        s.flush()
        for v in sorted(set(vids)):
            s.add(TestAssignment(rater=rater, vid=v))
        log(s, user, "set_test_assignment", {"rater": rater, "vids": sorted(set(vids))})
        s.commit()


def test_pool(eng) -> "pd.DataFrame":
    """Active vignettes with area/class, for building test subsets (PI side only)."""
    with Session(eng) as s:
        rows = s.execute(select(Vignette.vid, Blueprint.area, Blueprint.cls)
                         .join(Blueprint, Blueprint.vid == Vignette.vid)
                         .where(Vignette.active.is_(True))).all()
    return pd.DataFrame(rows, columns=["vid", "area", "cls"])


def ensure_test_assignment(eng, rater: str) -> list[str]:
    """Return the test rater's set, creating the default (different domains) if missing."""
    cur = get_assignment(eng, rater)
    if cur:
        return cur
    from test_sets import default_sets  # local import: avoid cycle
    pool = test_pool(eng)
    if pool.empty:
        return []
    sets = default_sets(pool)
    for r, vids in sets.items():
        if not get_assignment(eng, r):
            set_assignment(eng, r, vids, "system")
    return get_assignment(eng, rater)
