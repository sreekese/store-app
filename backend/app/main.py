import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse, Response

from app.advertisements.router import router as advertisements_router
from app.analytics.events import router as analytics_events
from app.analytics.router import router as analytics_router
from app.auth.router import router as auth_router
from app.auth.router import workspaces
from app.auth.service import AuthError
from app.billing.router import router as billing_router
from app.billing.router import webhooks as billing_webhooks
from app.core.config import Settings
from app.core.database import make_engine
from app.core.readiness import database_ready
from app.core.security import SecurityBoundary
from app.coupons.router import public as public_coupons
from app.coupons.router import router as coupons_router
from app.coupons.wallet import router as wallet_router
from app.daily.discovery import router as daily_router
from app.dashboards.router import router as dashboard_router
from app.locations.router import router as locations_router
from app.notifications.router import router as notifications_router
from app.offers.public import router as public_offers
from app.offers.router import public_categories
from app.offers.router import router as offers_router
from app.profiles.router import router as profiles_router
from app.redemptions.router import router as redemption_router
from app.trust.router import router as trust_router

logger = logging.getLogger("nearperk.requests")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


class Health(BaseModel):
    status: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    development = settings.app_env in {"development", "test"}
    app = FastAPI(
        title="Nearperk API",
        version="0.17.0",
        lifespan=lifespan,
        docs_url="/docs" if development else None,
        redoc_url="/redoc" if development else None,
        openapi_url="/openapi.json" if development else None,
    )
    app.state.engine = engine
    app.state.settings = settings
    app.include_router(analytics_router)
    app.include_router(analytics_events)
    app.include_router(billing_router)
    app.include_router(billing_webhooks)
    app.include_router(advertisements_router)
    app.include_router(auth_router)
    app.include_router(workspaces)
    app.include_router(profiles_router)
    app.include_router(locations_router)
    app.include_router(offers_router)
    app.include_router(public_categories)
    app.include_router(public_offers)
    app.include_router(coupons_router)
    app.include_router(wallet_router)
    app.include_router(redemption_router)
    app.include_router(dashboard_router)
    app.include_router(daily_router)
    app.include_router(notifications_router)
    app.include_router(trust_router)
    app.include_router(public_coupons)

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, exc: AuthError) -> JSONResponse:
        response = JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": request.state.request_id,
                }
            },
        )
        response.headers["Cache-Control"] = "no-store"
        if exc.status == 429:
            response.headers["Retry-After"] = "900"
        if exc.status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        if request.url.path == "/api/v1/auth/refresh" and exc.status == 401:
            response.delete_cookie(
                "nearperk_refresh",
                path="/api/v1/auth",
                httponly=True,
                secure=settings.cookie_secure,
                samesite="lax",
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's default error body can echo submitted passwords. Never return input values.
        if request.url.path.startswith("/api/v1/advertisements"):
            message = (
                "Check sponsor, copy, HTTPS creative, destination, schedule, and current revision."
            )
        elif request.url.path.startswith("/api/v1/analytics"):
            message = "Check report dates, business, event target and pagination fields."
        elif request.url.path.startswith("/api/v1/billing"):
            message = (
                "Check plan, currency, integer price, period, revision and billing request fields."
            )
        elif request.url.path.startswith(
            ("/api/v1/merchant/staff", "/api/v1/merchant/invitations", "/api/v1/staff/invitations")
        ):
            message = (
                "Check the email, active branches, invitation fields, "
                "page offset, and current staff revision."
            )
        elif request.url.path.startswith("/api/v1/trust"):
            message = "Check your rating, report target, branch, message, and current revision."
        elif request.url.path.startswith("/api/v1/daily"):
            message = (
                "Check the date, timezone, allowance, coordinates, radius, and current revision."
            )
        elif request.url.path.startswith("/api/v1/dashboards"):
            message = "Choose a 7, 30, or 90 day chart period."
        elif request.url.path.startswith("/api/v1/merchant/stores"):
            message = (
                "Check the branch fields. Supply both coordinates, a valid timezone, "
                "and all seven non-overlapping weekdays when publishing hours."
            )
        elif "/redemptions" in request.url.path:
            message = (
                "Check the branch, coupon code, purchase amount, confirmation, and request key."
            )
        elif "/shopper/wallet" in request.url.path:
            message = "Check the coupon reference, status filter, and page limits."
        elif "/campaigns" in request.url.path:
            message = (
                "Check campaign quantity, participating branches, dates, revision, and request key."
            )
        elif "/offers" in request.url.path:
            message = (
                "Check the offer fields, timezone-aware dates, and discount rules. "
                "Percentage must be greater than zero and at most 100; "
                "flat discounts cannot exceed the minimum purchase."
            )
        elif request.url.path.startswith("/api/v1/locations"):
            message = "Check the coordinates, radius, place name, and page limits."
        else:
            message = (
                "Check your required fields and input formats. "
                "Passwords must be 12–128 characters when registering."
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": message,
                    "request_id": request.state.request_id,
                }
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key", "X-CSRF-Protection"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/v1/") and request.url.path != "/api/v1/status":
            response.headers["Cache-Control"] = "no-store"
        logger.info(
            json.dumps(
                {"request_id": request_id, "method": request.method, "status": response.status_code}
            )
        )
        return response

    @app.get("/health", response_model=Health, tags=["Operations"])
    def health() -> Health:
        """Liveness is independent of database availability."""
        return Health(status="ok")

    @app.get(
        "/ready",
        response_model=Health,
        responses={503: {"description": "Not ready"}},
        tags=["Operations"],
    )
    def ready(request: Request) -> Health | JSONResponse:
        if database_ready(engine):
            return Health(status="ready")
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "SERVICE_NOT_READY",
                    "message": "Service is temporarily unavailable.",
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.get("/api/v1/status", tags=["Platform"])
    def status() -> dict[str, str | int]:
        """Public release metadata, with no operational secrets."""
        return {
            "name": "Nearperk",
            "version": "0.17.0",
            "sprint": 16,
            "stage": "security-hardening",
        }

    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts, www_redirect=False
    )
    app.add_middleware(SecurityBoundary, settings=settings)
    return app


app = create_app()
