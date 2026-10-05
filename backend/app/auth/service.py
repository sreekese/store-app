import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.audit import SecurityEvent
from app.auth.models import AuthSession, RefreshToken, User
from app.auth.schemas import AuthOutput, LoginInput, RegisterInput, UserOutput
from app.auth.security import DUMMY_HASH, access_token, hash_password, token_hash, verify_password
from app.core.config import Settings


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 401):
        self.code, self.message, self.status = code, message, status


def denied() -> AuthError:
    return AuthError(
        "AUTH_INVALID_CREDENTIALS", "Email or password is incorrect for this workspace."
    )


def register(db: Session, data: RegisterInput) -> User:
    user = User(
        email=str(data.email),
        display_name=data.display_name.strip(),
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AuthError(
            "REGISTRATION_FAILED", "Unable to create this account. Try signing in.", 409
        ) from None
    db.refresh(user)
    return user


def issue(
    db: Session, user: User, settings: Settings, family: AuthSession | None = None
) -> tuple[AuthOutput, str]:
    if family is None:
        family = AuthSession(
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
        db.add(family)
        db.flush()
    raw = secrets.token_urlsafe(48)
    db.add(RefreshToken(token_hash=token_hash(raw), session_id=family.id))
    result = AuthOutput(
        access_token=access_token(user, family, settings),
        expires_in=settings.access_token_seconds,
        user=UserOutput.model_validate(user),
    )
    db.commit()
    return result, raw


def login(db: Session, data: LoginInput, settings: Settings) -> tuple[AuthOutput, str]:
    user = db.scalar(select(User).where(User.email == str(data.email)))
    valid = verify_password(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid or not user.is_active or user.role != data.workspace:
        db.add(SecurityEvent(actor_id=user.id if user else None, kind="LOGIN_FAILED"))
        db.commit()
        raise denied()
    db.add(SecurityEvent(actor_id=user.id, kind="LOGIN_SUCCEEDED"))
    return issue(db, user, settings)


def locked_family(db: Session, raw: str) -> tuple[AuthSession, RefreshToken]:
    digest = token_hash(raw)
    family_id = db.scalar(select(RefreshToken.session_id).where(RefreshToken.token_hash == digest))
    if family_id is None:
        raise AuthError("AUTH_SESSION_EXPIRED", "Please sign in again.")
    family = db.scalar(select(AuthSession).where(AuthSession.id == family_id).with_for_update())
    token = db.get(RefreshToken, digest)
    if family is None or token is None:
        raise AuthError("AUTH_SESSION_EXPIRED", "Please sign in again.")
    return family, token


def refresh(db: Session, raw: str, settings: Settings) -> tuple[AuthOutput, str]:
    family, token = locked_family(db, raw)
    now = datetime.now(UTC)
    if token.used_at is not None:
        family.revoked_at = now
        db.add(SecurityEvent(actor_id=family.user_id, kind="REFRESH_REPLAY_REVOKED"))
        db.commit()  # Replay revocation must survive the error response.
        raise AuthError("AUTH_SESSION_EXPIRED", "Please sign in again.")
    user = db.get(User, family.user_id)
    if family.revoked_at or family.expires_at <= now or not user or not user.is_active:
        raise AuthError("AUTH_SESSION_EXPIRED", "Please sign in again.")
    db.add(SecurityEvent(actor_id=user.id, kind="REFRESH_ROTATED"))
    token.used_at = now
    return issue(db, user, settings, family)


def revoke(db: Session, raw: str) -> None:
    try:
        family, _ = locked_family(db, raw)
    except AuthError:
        return
    if family.revoked_at is None:
        db.add(SecurityEvent(actor_id=family.user_id, kind="LOGOUT_REVOKED"))
    family.revoked_at = datetime.now(UTC)
    db.commit()


def current_user(db: Session, user_id: UUID, session_id: UUID) -> User:
    family = db.get(AuthSession, session_id)
    user = db.get(User, user_id)
    if (
        not family
        or family.user_id != user_id
        or family.revoked_at
        or family.expires_at <= datetime.now(UTC)
        or not user
        or not user.is_active
    ):
        raise AuthError("AUTH_SESSION_EXPIRED", "Please sign in again.")
    # Current role/status is read from DB, never trusted from JWT/browser claims.
    return user
