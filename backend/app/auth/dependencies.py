import hashlib
import hmac
import time
from collections.abc import Callable, Iterator
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import AuthRateLimit, Role, User
from app.auth.security import decode_access
from app.auth.service import AuthError, current_user

bearer = HTTPBearer(auto_error=False)


def database(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as db:
        yield db


DB = Annotated[Session, Depends(database)]


def csrf(request: Request) -> None:
    origin = request.headers.get("origin")
    if request.headers.get("x-csrf-protection") != "1" or (
        origin is not None and origin not in request.app.state.settings.cors_origins
    ):
        raise AuthError("REQUEST_NOT_ALLOWED", "This request is not allowed.", 403)


def throttle(request: Request, db: Session, scope: str, identity: str, limit: int) -> None:
    settings = request.app.state.settings
    key = hmac.new(
        settings.jwt_secret_key.get_secret_value().encode(),
        f"{scope}:{identity}".encode(),
        hashlib.sha256,
    ).hexdigest()
    window = int(time.time()) // 900
    statement = insert(AuthRateLimit).values(key=key, window_start=window, count=1)
    count = db.scalar(
        statement.on_conflict_do_update(
            index_elements=[AuthRateLimit.key, AuthRateLimit.window_start],
            set_={"count": AuthRateLimit.count + 1},
        ).returning(AuthRateLimit.count)
    )
    # Bound stored windows; retain no raw IP/email identifiers.
    db.execute(delete(AuthRateLimit).where(AuthRateLimit.window_start < window - 1))
    db.commit()
    if count is not None and count > limit:
        raise AuthError("AUTH_RATE_LIMITED", "Too many attempts. Please try again later.", 429)


def authenticated(
    request: Request,
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise AuthError("AUTH_REQUIRED", "Please sign in.")
    try:
        claims = decode_access(credentials.credentials, request.app.state.settings)
        user_id, session_id = UUID(str(claims["sub"])), UUID(str(claims["sid"]))
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise AuthError("AUTH_INVALID_TOKEN", "Please sign in again.") from None
    user = current_user(db, user_id, session_id)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        throttle(
            request,
            db,
            "authenticated-mutation",
            str(user.id),
            request.app.state.settings.mutation_rate_limit,
        )
    return user


CurrentUser = Annotated[User, Depends(authenticated)]


def require_roles(*roles: Role) -> Callable[..., User]:
    def check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise AuthError("FORBIDDEN_ROLE", "You do not have access to this workspace.", 403)
        return user

    return check
