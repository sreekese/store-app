from ipaddress import ip_address
from socket import getaddrinfo
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.auth import service
from app.auth.dependencies import DB, CurrentUser, csrf, require_roles, throttle
from app.auth.models import Role, User
from app.auth.schemas import AuthOutput, LoginInput, RegisterInput, UserOutput

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
workspaces = APIRouter(prefix="/api/v1/workspaces", tags=["Workspaces"])
COOKIE = "nearperk_refresh"


def set_cookie(response: Response, raw: str, request: Request) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        COOKIE,
        raw,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
        max_age=settings.refresh_token_days * 86400,
    )
    response.headers["Cache-Control"] = "no-store"


def peer(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    trusted = request.app.state.settings.trusted_proxy_host
    forwarded = request.headers.get("x-real-ip")
    if trusted and forwarded:
        try:
            addresses = {info[4][0] for info in getaddrinfo(trusted, None)}
            if host in addresses:
                return str(ip_address(forwarded))
        except (OSError, ValueError):
            pass  # Fail closed: use the direct peer, not untrusted header content.
    return host


@router.post("/register", response_model=UserOutput, status_code=201, dependencies=[Depends(csrf)])
def register(data: RegisterInput, request: Request, response: Response, db: DB) -> UserOutput:
    throttle(request, db, "register", peer(request), request.app.state.settings.register_rate_limit)
    response.headers["Cache-Control"] = "no-store"
    return UserOutput.model_validate(service.register(db, data))


@router.post("/login", response_model=AuthOutput, dependencies=[Depends(csrf)])
def login(data: LoginInput, request: Request, response: Response, db: DB) -> AuthOutput:
    settings = request.app.state.settings
    throttle(request, db, "login-ip", peer(request), settings.login_ip_rate_limit)
    throttle(request, db, "login-email", str(data.email), settings.login_account_rate_limit)
    result, raw = service.login(db, data, settings)
    set_cookie(response, raw, request)
    return result


@router.post("/refresh", response_model=AuthOutput, dependencies=[Depends(csrf)])
def refresh(request: Request, response: Response, db: DB) -> AuthOutput:
    throttle(request, db, "refresh", peer(request), request.app.state.settings.refresh_rate_limit)
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise service.AuthError("AUTH_SESSION_EXPIRED", "Please sign in again.")
    result, replacement = service.refresh(db, raw, request.app.state.settings)
    set_cookie(response, replacement, request)
    return result


@router.post("/logout", status_code=204, dependencies=[Depends(csrf)])
def logout(request: Request, response: Response, db: DB) -> None:
    if raw := request.cookies.get(COOKIE):
        service.revoke(db, raw)
    response.delete_cookie(
        COOKIE,
        path="/api/v1/auth",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/me", response_model=UserOutput)
def me(user: CurrentUser, response: Response) -> UserOutput:
    response.headers["Cache-Control"] = "no-store"
    return UserOutput.model_validate(user)


@workspaces.get("/shopper", response_model=UserOutput)
def shopper(user: Annotated[User, Depends(require_roles(Role.USER))]) -> User:
    return user


@workspaces.get("/merchant", response_model=UserOutput)
def merchant(user: Annotated[User, Depends(require_roles(Role.MERCHANT))]) -> User:
    return user


@workspaces.get("/staff", response_model=UserOutput)
def staff(user: Annotated[User, Depends(require_roles(Role.MERCHANT_STAFF))]) -> User:
    return user


@workspaces.get("/admin", response_model=UserOutput)
def admin(user: Annotated[User, Depends(require_roles(Role.ADMIN, Role.SUPER_ADMIN))]) -> User:
    return user


@workspaces.get("/superadmin", response_model=UserOutput)
def superadmin(user: Annotated[User, Depends(require_roles(Role.SUPER_ADMIN))]) -> User:
    return user
