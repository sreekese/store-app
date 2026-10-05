from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import DB, authenticated, csrf, require_roles
from app.auth.models import Role, User
from app.coupons.models import Campaign, CouponClaim
from app.locations.router import visible
from app.offers.public import Browse, public_query
from app.offers.service import record
from app.profiles.models import Store
from app.redemptions.models import Redemption
from app.trust.models import CaseAction, Review, SupportCase
from app.trust.schemas import (
    CaseStatus,
    Moderate,
    ReportInput,
    Respond,
    ReviewInput,
    ReviewStatus,
    Transition,
)
from app.trust.service import (
    action,
    case_output,
    cases,
    fail,
    get_case,
    report_context,
    review_output,
)

router = APIRouter(
    prefix="/api/v1/trust", tags=["Reviews and support"], dependencies=[Depends(csrf)]
)
Actor = Annotated[User, Depends(authenticated)]
Shopper = Annotated[User, Depends(require_roles(Role.USER))]
Admin = Annotated[User, Depends(require_roles(Role.ADMIN, Role.SUPER_ADMIN))]
Offset = Annotated[int, Query(ge=0, le=10000)]


def page(items: list[dict[str, Any]], offset: int) -> dict[str, Any]:
    return {
        "items": items[:20],
        "next_offset": offset + 20 if len(items) > 20 and offset + 20 <= 10000 else None,
    }


@router.post("/reviews", status_code=201)
def create_review(data: ReviewInput, db: DB, user: Shopper) -> dict[str, Any]:
    redemption = db.scalar(
        select(Redemption)
        .where(Redemption.id == data.redemption_id, Redemption.user_id == user.id)
        .with_for_update()
    )
    if redemption is None:
        fail("An owned, successfully redeemed coupon is required.", 404)
    claim = db.get(CouponClaim, redemption.claim_id)
    if claim is None or claim.status != "REDEEMED":
        fail("Only successfully redeemed coupons can be reviewed.")
    campaign = db.get(Campaign, claim.campaign_id)
    if not (campaign is not None):
        raise RuntimeError("Required application state is unavailable")
    row = Review(
        redemption_id=redemption.id,
        user_id=user.id,
        merchant_id=redemption.merchant_id,
        store_id=redemption.store_id,
        offer_id=campaign.offer_id,
        rating=data.rating,
        comment=data.comment,
    )
    db.add(row)
    try:
        db.flush()
        record(db, user, row.merchant_id, "REVIEW_CREATED", review_id=str(row.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("This redemption already has a review.")
    return review_output(row, private=True)


@router.get("/reviews/mine/{redemption_id}")
def own_review(redemption_id: UUID, db: DB, user: Shopper) -> dict[str, Any]:
    redemption = db.scalar(
        select(Redemption.id).where(Redemption.id == redemption_id, Redemption.user_id == user.id)
    )
    if redemption is None:
        fail("Redemption not found.", 404)
    row = db.scalar(select(Review).where(Review.redemption_id == redemption_id))
    return {"review": review_output(row, private=True) if row else None}


@router.get("/reviews")
def public_reviews(
    db: DB, store_id: UUID, offer_id: UUID | None = None, offset: Offset = 0
) -> dict[str, Any]:
    if not db.execute(visible().where(Store.id == store_id)).first():
        fail("Store not found.", 404)
    if offer_id and not db.execute(public_query(Browse(), 5, offer_id, store_id)).first():
        fail("Offer not found.", 404)
    query = select(Review).where(Review.store_id == store_id, Review.status == "PUBLISHED")
    if offer_id:
        query = query.where(Review.offer_id == offer_id)
    ratings = query.with_only_columns(Review.rating).subquery()
    aggregate = db.execute(select(func.count(), func.avg(ratings.c.rating))).one()
    rows = list(
        db.scalars(query.order_by(Review.created_at.desc(), Review.id).offset(offset).limit(21))
    )
    return {
        **page([review_output(r) for r in rows], offset),
        "count": aggregate[0],
        "average": round(float(aggregate[1]), 1) if aggregate[1] is not None else None,
    }


@router.get("/reviews/moderation")
def review_queue(
    db: DB, user: Admin, status: ReviewStatus = "PENDING", offset: Offset = 0
) -> dict[str, Any]:
    rows = db.scalars(
        select(Review)
        .where(Review.status == status)
        .order_by(Review.created_at, Review.id)
        .offset(offset)
        .limit(21)
    )
    return page([review_output(r, private=True) for r in rows], offset)


@router.post("/reviews/{id}/moderate")
def moderate(id: UUID, data: Moderate, db: DB, user: Admin) -> dict[str, Any]:
    row = db.scalar(select(Review).where(Review.id == id).with_for_update())
    if row is None:
        fail("Review not found.", 404)
    if row.revision != data.revision or row.status == data.status:
        fail("Review changed. Refresh before moderating.")
    row.status, row.moderation_reason = data.status, data.reason
    row.revision += 1
    record(
        db,
        user,
        row.merchant_id,
        "REVIEW_MODERATED",
        review_id=str(row.id),
        status=row.status,
        reason=data.reason,
        revision=row.revision,
    )
    db.commit()
    return review_output(row, private=True)


@router.post("/cases", status_code=201)
def report(data: ReportInput, db: DB, user: Shopper) -> dict[str, Any]:
    store, claim, redemption, context = report_context(db, user, data)
    row = SupportCase(
        reporter_id=user.id,
        merchant_id=store.merchant_id,
        store_id=store.id,
        claim_id=claim.id if claim else None,
        redemption_id=redemption.id if redemption else None,
        target_type=data.target_type,
        target_id=data.target_id,
        reason=data.reason,
        description=data.description,
        context=context,
    )
    db.add(row)
    try:
        db.flush()
        action(db, user, row, "CREATED", "Case opened.")
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("You already reported this issue. Follow the existing case in Support.")
    return case_output(row, detail=True)


@router.get("/cases")
def case_list(
    db: DB, user: Actor, status: CaseStatus | None = None, offset: Offset = 0
) -> dict[str, Any]:
    query = cases(user)
    if status:
        query = query.where(SupportCase.status == status)
    rows = db.scalars(
        query.order_by(SupportCase.created_at.desc(), SupportCase.id).offset(offset).limit(21)
    )
    return page([case_output(r) for r in rows], offset)


@router.get("/cases/{id}")
def detail(id: UUID, db: DB, user: Actor) -> dict[str, Any]:
    return case_output(get_case(db, user, id), detail=True)


@router.get("/cases/{id}/history")
def history(id: UUID, db: DB, user: Actor, offset: Offset = 0) -> dict[str, Any]:
    get_case(db, user, id)
    rows = db.scalars(
        select(CaseAction)
        .where(CaseAction.case_id == id)
        .order_by(CaseAction.revision.desc())
        .offset(offset)
        .limit(21)
    )
    return page(
        [
            {
                "id": r.id,
                "actor_role": r.actor_role,
                "kind": r.kind,
                "message": r.message,
                "status": r.status,
                "created_at": r.created_at,
                "revision": r.revision,
            }
            for r in rows
        ],
        offset,
    )


@router.post("/cases/{id}/respond")
def respond(id: UUID, data: Respond, db: DB, user: Actor) -> dict[str, Any]:
    row = get_case(db, user, id, lock=True)
    if row.status == "RESOLVED" or row.revision != data.revision:
        fail("Case is resolved or changed. Refresh before responding.")
    row.revision += 1
    action(db, user, row, "RESPONSE", data.message)
    db.commit()
    return case_output(row, detail=True)


@router.post("/cases/{id}/transition")
def transition(id: UUID, data: Transition, db: DB, user: Admin) -> dict[str, Any]:
    row = get_case(db, user, id, lock=True)
    transitions = {
        "OPEN": {"UNDER_REVIEW"},
        "UNDER_REVIEW": {"AWAITING_RESPONSE", "RESOLVED"},
        "AWAITING_RESPONSE": {"UNDER_REVIEW", "RESOLVED"},
        "RESOLVED": set(),
    }
    if row.revision != data.revision or data.status not in transitions[row.status]:
        fail("Case changed or this transition is not allowed. Refresh the case.")
    row.status = data.status
    row.revision += 1
    if row.status == "RESOLVED":
        row.resolution, row.resolved_at = data.message, datetime.now(UTC)
    action(db, user, row, "TRANSITION", data.message)
    db.commit()
    return case_output(row, detail=True)
