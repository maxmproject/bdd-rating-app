"""Minimal password login using hashes stored in st.secrets (no extra deps).

secrets.toml:
[users.rater_a]
name = "จิตแพทย์ A"
role = "rater"        # rater | pi
rater = "A"
password_hash = "pbkdf2_sha256$200000$<salt>$<hash>"   # from make_hash.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

ITER = 200_000


def make_hash(password: str, iterations: int = ITER) -> str:
    salt = base64.b64encode(os.urandom(16)).decode()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(dk).decode()}"


def hash_problem(stored) -> str:
    """'' if the stored hash looks well-formed, else a short reason (never reveals the hash)."""
    if not isinstance(stored, str) or not stored.strip():
        return "ไม่มี password_hash"
    s = stored.strip()
    parts = s.split("$")
    if len(parts) != 4:
        return f"ต้องมี 4 ส่วนคั่นด้วย $ (พบ {len(parts)})"
    if parts[0] != "pbkdf2_sha256":
        return "ต้องขึ้นต้นด้วย pbkdf2_sha256"
    if not parts[1].isdigit():
        return "จำนวนรอบ (iterations) ไม่ใช่ตัวเลข"
    try:
        if len(base64.b64decode(parts[3], validate=True)) != 32:
            return "ความยาว hash ไม่ใช่ 32 bytes"
    except Exception:  # noqa: BLE001
        return "ส่วน hash ไม่ใช่ base64"
    return ""


def verify(password: str, stored: str) -> bool:
    try:
        stored = stored.strip()   # tolerate spaces/newlines pasted into secrets
        algo, it, salt, h = stored.split("$")
        assert algo == "pbkdf2_sha256"
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(it))
        return hmac.compare_digest(base64.b64encode(dk).decode(), h)
    except Exception:
        return False
