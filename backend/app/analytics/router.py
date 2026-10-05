import csv
import io
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.analytics.schemas import Filters
from app.analytics.service import report
from app.auth.dependencies import DB, csrf, require_roles, throttle
from app.auth.models import Role, User
from app.auth.service import AuthError

router = APIRouter(
    prefix="/api/v1/analytics", tags=["Analytics reports"], dependencies=[Depends(csrf)]
)
Reporter = Annotated[User, Depends(require_roles(Role.MERCHANT, Role.ADMIN, Role.SUPER_ADMIN))]


def cell(value: object) -> object:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@router.get("/report")
def metrics(
    request: Request, actor: Reporter, filters: Annotated[Filters, Query()]
) -> dict[str, object]:
    with Session(
        request.app.state.engine.execution_options(isolation_level="REPEATABLE READ")
    ) as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        return report(db, actor, filters, datetime.now(UTC))


@router.get("/export")
def export(
    request: Request,
    actor: Reporter,
    db: DB,
    filters: Annotated[Filters, Query()],
) -> Response:
    kind = filters.kind
    if kind == "revenue" and actor.role != Role.SUPER_ADMIN:
        raise AuthError("FORBIDDEN_ROLE", "Only superadmin can export platform payments.", 403)
    throttle(request, db, "analytics-export", str(actor.id), 20)
    with Session(
        request.app.state.engine.execution_options(isolation_level="REPEATABLE READ")
    ) as snapshot:
        snapshot.execute(text("SET TRANSACTION READ ONLY"))
        data = report(snapshot, actor, filters, datetime.now(UTC), export=kind)
    rows = data[kind]["items"] if kind in {"campaigns", "merchants"} else data[kind]
    columns = {
        "daily": ["date", "claims", "redemptions", "engaged_shoppers"],
        "campaigns": [
            "id",
            "title",
            "status",
            "claims",
            "redemptions",
            "cohort_redeemed",
            "cohort_rate",
        ],
        "merchants": ["id", "business_name", "status", "claims", "redemptions"],
        "events": ["kind", "count"],
        "revenue": ["provider", "currency", "gross_minor", "refund_minor", "net_minor", "payments"],
    }[kind]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["start_date", "end_date", "as_of", "timezone", *columns])
    for row in rows:
        writer.writerow(
            [
                data["start_date"],
                data["end_date"],
                data["as_of"].isoformat(),
                data["timezone"],
                *[cell(row.get(c, "")) for c in columns],
            ]
        )
    filename = f"nearperk-{kind}-{filters.start_date}-{filters.end_date}.csv"
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
