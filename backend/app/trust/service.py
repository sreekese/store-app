from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import Select, false, select
from sqlalchemy.orm import Session

from app.auth.models import Role, User
from app.auth.service import AuthError
from app.coupons.models import CouponClaim
from app.locations.router import visible
from app.offers.public import Browse, public_query
from app.offers.service import record
from app.profiles.models import Merchant, StaffAssignment, Store
from app.redemptions.models import Redemption
from app.trust.models import CaseAction, Review, SupportCase
from app.trust.schemas import ReportInput

ADMINS = (Role.ADMIN, Role.SUPER_ADMIN)


def fail(message: str, status: int = 409) -> NoReturn:
    raise AuthError("TRUST_REQUEST_DENIED", message, status)


def cases(user: User) -> Select[tuple[SupportCase]]:
    query = select(SupportCase)
    if user.role == Role.USER:
        return query.where(SupportCase.reporter_id == user.id)
    if user.role == Role.MERCHANT:
        return query.where(
            SupportCase.merchant_id.in_(select(Merchant.id).where(Merchant.owner_id == user.id))
        )
    if user.role == Role.MERCHANT_STAFF:
        return query.where(
            SupportCase.store_id.in_(
                select(StaffAssignment.store_id).where(StaffAssignment.staff_id == user.id)
            )
        )
    if user.role in ADMINS:
        return query
    return query.where(false())


def get_case(db: Session, user: User, id: UUID, *, lock: bool = False) -> SupportCase:
    query = cases(user).where(SupportCase.id == id)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        fail("Support case not found.", 404)
    return row


def case_output(row: SupportCase, *, detail: bool = False) -> dict[str, Any]:
    result = {
        "id": row.id,
        "reference": "NP-" + str(row.id),
        "target_type": row.target_type,
        "reason": row.reason,
        "status": row.status,
        "revision": row.revision,
        "created_at": row.created_at,
        "resolved_at": row.resolved_at,
        "title": row.context["title"],
        "store_name": row.context["store_name"],
    }
    if detail:
        result.update(
            description=row.description,
            resolution=row.resolution,
            context=row.context,
            claim_id=row.claim_id,
            redemption_id=row.redemption_id,
        )
    return result


def review_output(row: Review, *, private: bool = False) -> dict[str, Any]:
    result = {
        "id": row.id,
        "rating": row.rating,
        "comment": row.comment,
        "created_at": row.created_at,
        "store_id": row.store_id,
        "offer_id": row.offer_id,
    }
    if private:
        result.update(
            status=row.status, revision=row.revision, moderation_reason=row.moderation_reason
        )
    return result


def action(db: Session, user: User, row: SupportCase, kind: str, message: str) -> None:
    db.add(
        CaseAction(
            case_id=row.id,
            actor_id=user.id,
            actor_role=user.role,
            kind=kind,
            message=message,
            status=row.status,
            revision=row.revision,
        )
    )
    record(
        db,
        user,
        row.merchant_id,
        "SUPPORT_" + kind,
        case_id=str(row.id),
        status=row.status,
        revision=row.revision,
    )


def report_context(
    db: Session, user: User, data: ReportInput
) -> tuple[Store, CouponClaim | None, Redemption | None, dict[str, Any]]:
    claim = None
    redemption = None
    store = db.get(Store, data.store_id)
    if store is None:
        fail("Report target not found.", 404)
    context: dict[str, Any] = {"store_name": store.name, "title": store.name}
    if data.reason == "STORE_REFUSED_COUPON" and data.target_type != "CLAIM":
        fail("Choose your coupon to report a refusal.", 422)
    if data.target_type == "CLAIM":
        claim = db.scalar(
            select(CouponClaim)
            .where(CouponClaim.id == data.target_id, CouponClaim.user_id == user.id)
            .with_for_update()
        )
        if (
            claim is None
            or str(store.id) not in [str(b["id"]) for b in claim.snapshot["branches"]]
            or str(store.merchant_id) != claim.snapshot["merchant_id"]
        ):
            fail("Coupon or participating branch not found.", 404)
        redemption = db.scalar(select(Redemption).where(Redemption.claim_id == claim.id))
        if redemption and redemption.store_id != store.id:
            fail("Select the branch recorded on your redemption receipt.", 422)
        context.update(
            title=claim.snapshot["offer"]["title"],
            offer=claim.snapshot["offer"],
            business_name=claim.snapshot["business_name"],
            eligibility=claim.snapshot["eligibility"],
            claimed_at=claim.claimed_at.isoformat(),
            expires_at=claim.expires_at.isoformat(),
            status_at_report=claim.status,
        )
        if redemption:
            context["receipt"] = {
                "purchase_amount": str(redemption.purchase_amount),
                "discount_amount": str(redemption.discount_amount),
                "redeemed_at": redemption.redeemed_at.isoformat(),
            }
    elif data.target_type == "OFFER":
        result = db.execute(public_query(Browse(), 5, data.target_id, store.id)).first()
        if result is None:
            fail("Offer not found.", 404)
        context["title"] = result[0].title
    else:
        if not db.execute(visible().where(Store.id == store.id)).first():
            fail("Store not found.", 404)
        if data.target_type == "STORE" and data.target_id != store.id:
            fail("Store not found.", 404)
        if data.target_type == "REVIEW":
            review = db.scalar(
                select(Review).where(
                    Review.id == data.target_id,
                    Review.store_id == store.id,
                    Review.status == "PUBLISHED",
                )
            )
            if review is None:
                fail("Review not found.", 404)
            context.update(
                title="Review of " + store.name, comment=review.comment, rating=review.rating
            )
    return store, claim, redemption, context
