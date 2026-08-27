"""
auth.py -- Accounts and request authentication.

Passwords are hashed with PBKDF2-HMAC-SHA256 from the standard library, so the
service has no native-extension dependency to build on Windows. Sessions are
stateless JWTs signed with ``SECRET_KEY``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

PBKDF2_ROUNDS = 240_000


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def password_problem(password: str) -> Optional[str]:
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if password.lower() in {"password", "12345678", "qwertyui"}:
        return "That password is too common."
    return None


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_token(user_id: int) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"},
                             separators=(",", ":")).encode())
    payload = _b64(json.dumps({
        "sub": str(user_id),
        "iat": int(time.time()),
        "exp": int(time.time()) + settings.token_hours * 3600,
    }, separators=(",", ":")).encode())
    body = f"{header}.{payload}"
    signature = hmac.new(settings.secret_key.encode(), body.encode(),
                         hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def read_token(token: str) -> Optional[int]:
    try:
        header, payload, signature = token.split(".")
    except ValueError:
        return None
    expected = hmac.new(settings.secret_key.encode(), f"{header}.{payload}".encode(),
                        hashlib.sha256).digest()
    if not hmac.compare_digest(_unb64(signature), expected):
        return None
    try:
        claims = json.loads(_unb64(payload))
        if int(claims.get("exp", 0)) < time.time():
            return None
        return int(claims["sub"])
    except (ValueError, KeyError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
def _bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get("cf_token")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _bearer(request)
    user_id = read_token(token) if token else None
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account unavailable.")
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    token = _bearer(request)
    user_id = read_token(token) if token else None
    return db.get(User, user_id) if user_id else None


def register(db: Session, email: str, password: str) -> Tuple[Optional[User], str]:
    """Create an account. Returns (user, error)."""
    email = (email or "").strip().lower()
    if "@" not in email or len(email) < 5:
        return None, "Enter a valid email address."
    problem = password_problem(password or "")
    if problem:
        return None, problem
    if db.query(User).filter(User.email == email).count():
        return None, "An account with that email already exists."

    # Start every account on a working configuration rather than an empty one,
    # so the Publish button does something sensible on day one.
    from .niches import starter_settings

    user = User(email=email, password_hash=hash_password(password),
                settings=starter_settings())
    db.add(user)
    db.flush()
    return user, ""
