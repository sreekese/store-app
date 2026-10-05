import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.auth.models import AuthSession, User
from app.core.config import Settings

password_hasher = PasswordHash.recommended()
# Equal password-verification work for nonexistent accounts.
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hasher.verify(password, hashed)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def access_token(user: User, session: AuthSession, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(session.id),
            "type": "access",
            "iss": "nearperk",
            "aud": "nearperk-web",
            "iat": now,
            "exp": now + timedelta(seconds=settings.access_token_seconds),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )


def decode_access(token: str, settings: Settings) -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=["HS256"],
        issuer="nearperk",
        audience="nearperk-web",
        options={"require": ["sub", "sid", "type", "iss", "aud", "iat", "exp"]},
    )
    if claims["type"] != "access":
        raise jwt.InvalidTokenError("Wrong token type")
    return claims
