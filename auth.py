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


def verify(password: str, stored: str) -> bool:
    try:
        algo, it, salt, h = stored.split("$")
        assert algo == "pbkdf2_sha256"
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(it))
        return hmac.compare_digest(base64.b64encode(dk).decode(), h)
    except Exception:
        return False
