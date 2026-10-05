import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import DB, csrf, require_roles, throttle
from app.auth.models import Role, User
from app.auth.router import peer
from app.auth.schemas import UserOutput
from app.auth.security import hash_password, token_hash, verify_password
from app.auth.service import AuthError
from app.profiles.models import (
    AuditEvent,
    Invitation,
    Merchant,
    Profile,
    StaffAccess,
    StaffAssignment,
    Store,
)
from app.profiles.schemas import (
    AcceptInput,
    AssignmentUpdate,
    InvitationOutput,
    InviteInput,
    InviteToken,
    MerchantInput,
    MerchantOutput,
    ProfileInput,
    ProfileOutput,
    ReviewInput,
    StaffOutput,
    StoreInput,
    StoreOutput,
    StoreUpdate,
)

router = APIRouter(
    prefix="/api/v1", tags=["Profiles and merchant access"], dependencies=[Depends(csrf)]
)
Shopper = Annotated[User, Depends(require_roles(Role.USER))]
Owner = Annotated[User, Depends(require_roles(Role.MERCHANT))]
Staff = Annotated[User, Depends(require_roles(Role.MERCHANT_STAFF))]
Reviewer = Annotated[User, Depends(require_roles(Role.ADMIN, Role.SUPER_ADMIN))]


def fail(message: str, status: int = 409) -> NoReturn:
    raise AuthError("PROFILE_REQUEST_DENIED", message, status)


def owned(db: DB, owner: User) -> Merchant:
    # All merchant mutations take this lock before touching invitations/assignments.
    merchant = db.scalar(select(Merchant).where(Merchant.owner_id == owner.id).with_for_update())
    if merchant is None:
        raise AuthError("BUSINESS_REQUIRED", "Complete your business profile first.", 404)
    return merchant


def verified(merchant: Merchant) -> None:
    if merchant.status != "VERIFIED":
        fail("The business must be verified before managing staff access.")


def audit(db: DB, actor: User, merchant: Merchant, action: str, **detail: object) -> None:
    db.add(AuditEvent(actor_id=actor.id, merchant_id=merchant.id, action=action, detail=detail))


def stores_for(db: DB, merchant: Merchant, ids: list[UUID]) -> list[Store]:
    stores = list(
        db.scalars(
            select(Store).where(
                Store.merchant_id == merchant.id, Store.id.in_(ids), Store.status == "ACTIVE"
            )
        )
    )
    if len(stores) != len(ids):
        fail("Select active stores belonging to your business.", 403)
    return stores


@router.get("/profile", response_model=ProfileOutput)
def profile(db: DB, user: Shopper) -> ProfileOutput:
    item = db.get(Profile, user.id)
    values = (
        {
            field: getattr(item, field)
            for field in ProfileInput.model_fields
            if field != "display_name"
        }
        if item
        else {}
    )
    return ProfileOutput(display_name=user.display_name, email=user.email, **values)


@router.put("/profile", response_model=ProfileOutput)
def save_profile(data: ProfileInput, db: DB, user: Shopper) -> ProfileOutput:
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    item = db.get(Profile, user.id)
    if item is None:
        item = Profile(user_id=user.id)
        db.add(item)
    user.display_name = data.display_name
    for field, value in data.model_dump(exclude={"display_name"}).items():
        setattr(item, field, value)
    db.commit()
    return ProfileOutput(email=user.email, **data.model_dump())


@router.get("/merchant/profile", response_model=MerchantOutput | None)
def merchant_profile(db: DB, user: Owner) -> Merchant | None:
    return db.scalar(select(Merchant).where(Merchant.owner_id == user.id))


@router.put("/merchant/profile", response_model=MerchantOutput)
def save_merchant(data: MerchantInput, db: DB, user: Owner) -> Merchant:
    # Serialize first creation as well as subsequent submissions.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    merchant = db.scalar(select(Merchant).where(Merchant.owner_id == user.id).with_for_update())
    if merchant is None:
        merchant = Merchant(owner_id=user.id, **data.model_dump())
        db.add(merchant)
        db.flush()
    else:
        if merchant.status == "SUSPENDED":
            fail("This business is suspended. Contact platform support.")
        for field, value in data.model_dump().items():
            setattr(merchant, field, value)
        merchant.status = "PENDING"
        merchant.review_note = ""
        merchant.revision += 1
        merchant.updated_at = datetime.now(UTC)
    audit(db, user, merchant, "PROFILE_SUBMITTED", revision=merchant.revision)
    db.commit()
    db.refresh(merchant)
    return merchant


@router.get("/merchant/stores", response_model=list[StoreOutput])
def merchant_stores(db: DB, user: Owner) -> list[Store]:
    merchant = owned(db, user)
    return list(
        db.scalars(
            select(Store).where(Store.merchant_id == merchant.id).order_by(Store.name, Store.id)
        )
    )


@router.post("/merchant/stores", response_model=StoreOutput, status_code=201)
def create_store(data: StoreInput, db: DB, user: Owner) -> Store:
    merchant = owned(db, user)
    if merchant.status == "SUSPENDED":
        fail("This business is suspended.")
    store = Store(merchant_id=merchant.id, **data.model_dump())
    db.add(store)
    db.flush()
    audit(db, user, merchant, "STORE_CREATED", store_id=str(store.id))
    db.commit()
    db.refresh(store)
    return store


@router.put("/merchant/stores/{store_id}", response_model=StoreOutput)
def update_store(store_id: UUID, data: StoreUpdate, db: DB, user: Owner) -> Store:
    merchant = owned(db, user)
    if merchant.status == "SUSPENDED":
        fail("This business is suspended.")
    store = db.scalar(
        select(Store)
        .where(Store.id == store_id, Store.merchant_id == merchant.id)
        .with_for_update()
    )
    if store is None:
        fail("Branch not found.", 404)
    if store.revision != data.revision:
        fail("This branch changed. Reload branches before saving.")
    for field, value in data.model_dump(exclude={"revision"}).items():
        setattr(store, field, value)
    store.revision += 1
    store.updated_at = datetime.now(UTC)
    audit(
        db,
        user,
        merchant,
        "STORE_UPDATED",
        store_id=str(store.id),
        revision=store.revision,
        status=store.status,
    )
    db.commit()
    db.refresh(store)
    return store


@router.get("/merchant/invitations", response_model=list[InvitationOutput])
def invitations(
    db: DB,
    user: Owner,
    offset: int = Query(0, ge=0, le=10000),
    status: Literal["PENDING", "ACCEPTED", "CANCELLED", "EXPIRED"] | None = None,
) -> list[Invitation]:
    merchant = owned(db, user)
    query = select(Invitation).where(Invitation.merchant_id == merchant.id)
    now = datetime.now(UTC)
    if status == "ACCEPTED":
        query = query.where(Invitation.accepted_at.is_not(None))
    elif status == "CANCELLED":
        query = query.where(Invitation.closed_at.is_not(None), Invitation.accepted_at.is_(None))
    elif status in {"PENDING", "EXPIRED"}:
        query = query.where(Invitation.closed_at.is_(None), Invitation.accepted_at.is_(None))
        query = query.where(
            Invitation.expires_at > now if status == "PENDING" else Invitation.expires_at <= now
        )
    return list(
        db.scalars(
            query.order_by(Invitation.expires_at.desc(), Invitation.id).offset(offset).limit(25)
        )
    )


@router.post("/merchant/invitations", status_code=201)
def invite(data: InviteInput, db: DB, user: Owner, request: Request) -> dict[str, object]:
    throttle(request, db, "staff-invite", str(user.id), 30)
    merchant = owned(db, user)
    verified(merchant)
    return issue_invitation(data, db, user, merchant)


def issue_invitation(
    data: InviteInput, db: DB, user: User, merchant: Merchant
) -> dict[str, object]:
    stores_for(db, merchant, data.store_ids)
    existing = db.scalar(select(User).where(User.email == str(data.email)))
    if existing is not None and (existing.role != Role.MERCHANT_STAFF or not existing.is_active):
        fail("This email cannot be invited as a staff account.")
    # Reissuing an invitation invalidates earlier links for this business/email.
    replaced = []
    for old in db.scalars(
        select(Invitation).where(
            Invitation.merchant_id == merchant.id,
            Invitation.email == str(data.email),
            Invitation.closed_at.is_(None),
        )
    ):
        old.closed_at = datetime.now(UTC)
        replaced.append(str(old.id))
    token = secrets.token_urlsafe(48)
    item = Invitation(
        merchant_id=merchant.id,
        email=str(data.email),
        token_hash=token_hash(token),
        store_ids=[str(i) for i in data.store_ids],
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(item)
    db.flush()
    audit(
        db,
        user,
        merchant,
        "STAFF_INVITED",
        invitation_id=str(item.id),
        store_ids=item.store_ids,
        replaced_invitation_ids=replaced,
    )
    db.commit()
    return {"invitation": InvitationOutput.model_validate(item), "token": token}


@router.post("/merchant/invitations/{invitation_id}/reissue", status_code=201)
def reissue(invitation_id: UUID, db: DB, user: Owner, request: Request) -> dict[str, object]:
    throttle(request, db, "staff-invite", str(user.id), 30)
    merchant = owned(db, user)
    verified(merchant)
    item = db.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id, Invitation.merchant_id == merchant.id
        )
    )
    if item is None:
        fail("Invitation not found.", 404)
    if item.accepted_at is not None:
        fail("This invitation was accepted. Manage the staff member's assignments instead.")
    return issue_invitation(
        InviteInput(email=item.email, store_ids=[UUID(i) for i in item.store_ids]),
        db,
        user,
        merchant,
    )


@router.delete("/merchant/invitations/{invitation_id}", status_code=204)
def cancel_invite(invitation_id: UUID, db: DB, user: Owner) -> None:
    merchant = owned(db, user)
    item = db.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id, Invitation.merchant_id == merchant.id
        )
    )
    if item is None:
        fail("Invitation not found.", 404)
    if item.closed_at is None:
        item.closed_at = datetime.now(UTC)
        audit(db, user, merchant, "INVITATION_CANCELLED", invitation_id=str(item.id))
        db.commit()


def active_invite(db: DB, token: str) -> tuple[Invitation, Merchant]:
    digest = token_hash(token)
    merchant_id = db.scalar(select(Invitation.merchant_id).where(Invitation.token_hash == digest))
    merchant = db.scalar(select(Merchant).where(Merchant.id == merchant_id).with_for_update())
    item = db.scalar(select(Invitation).where(Invitation.token_hash == digest).with_for_update())
    if (
        item is None
        or merchant is None
        or item.closed_at is not None
        or item.expires_at <= datetime.now(UTC)
    ):
        raise AuthError(
            "INVITATION_INVALID", "This invitation is invalid, expired, or already used.", 410
        )
    verified(merchant)
    stores_for(db, merchant, [UUID(i) for i in item.store_ids])
    return item, merchant


@router.post("/staff/invitations/preview")
def preview(data: InviteToken, db: DB, request: Request) -> dict[str, object]:
    throttle(request, db, "invite-preview", peer(request), 60)
    item, merchant = active_invite(db, data.token)
    stores = stores_for(db, merchant, [UUID(i) for i in item.store_ids])
    return {
        "email": item.email,
        "business_name": merchant.business_name,
        "stores": [s.name for s in stores],
        "expires_at": item.expires_at,
    }


@router.post("/staff/invitations/accept", response_model=UserOutput)
def accept(data: AcceptInput, db: DB, request: Request) -> User:
    throttle(request, db, "invite-accept", peer(request), 20)
    throttle(request, db, "invite-token", token_hash(data.token), 10)
    item, merchant = active_invite(db, data.token)
    user = db.scalar(select(User).where(User.email == item.email).with_for_update())
    if user is not None:
        if (
            user.role != Role.MERCHANT_STAFF
            or not user.is_active
            or not verify_password(data.password, user.password_hash)
        ):
            fail("An account already exists. Use its current staff password to accept.", 403)
    else:
        user = User(
            email=item.email,
            display_name=data.display_name,
            role=Role.MERCHANT_STAFF,
            password_hash=hash_password(data.password),
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            fail("An account was just created for this email. Try again with its password.")
    for store_id in item.store_ids:
        db.execute(
            insert(StaffAssignment)
            .values(staff_id=user.id, merchant_id=merchant.id, store_id=UUID(store_id))
            .on_conflict_do_nothing()
        )
    db.execute(
        insert(StaffAccess)
        .values(merchant_id=merchant.id, staff_id=user.id)
        .on_conflict_do_update(
            index_elements=[StaffAccess.merchant_id, StaffAccess.staff_id],
            set_={"revision": StaffAccess.revision + 1},
        )
    )
    item.closed_at = item.accepted_at = datetime.now(UTC)
    audit(
        db,
        user,
        merchant,
        "INVITATION_ACCEPTED",
        invitation_id=str(item.id),
        staff_id=str(user.id),
        store_ids=item.store_ids,
    )
    db.commit()
    db.refresh(user)
    return user


@router.get("/merchant/staff", response_model=list[StaffOutput])
def staff_list(db: DB, user: Owner, offset: int = Query(0, ge=0, le=10000)) -> list[StaffOutput]:
    merchant = owned(db, user)
    # Legacy assignment-only rows are supported; migration backfills the durable roster.
    query = (
        select(User, func.coalesce(StaffAccess.revision, 1))
        .outerjoin(
            StaffAccess,
            and_(StaffAccess.staff_id == User.id, StaffAccess.merchant_id == merchant.id),
        )
        .where(
            or_(
                StaffAccess.staff_id.is_not(None),
                User.id.in_(
                    select(StaffAssignment.staff_id).where(
                        StaffAssignment.merchant_id == merchant.id
                    )
                ),
            )
        )
        .order_by(User.email, User.id)
        .offset(offset)
        .limit(25)
    )
    rows = list(db.execute(query))
    branches: dict[UUID, list[UUID]] = {person.id: [] for person, _ in rows}
    for staff_id, store_id in db.execute(
        select(StaffAssignment.staff_id, StaffAssignment.store_id)
        .where(StaffAssignment.merchant_id == merchant.id, StaffAssignment.staff_id.in_(branches))
        .order_by(StaffAssignment.store_id)
    ):
        branches[staff_id].append(store_id)
    return [
        StaffOutput(
            id=person.id,
            email=person.email,
            display_name=person.display_name,
            store_ids=branches[person.id],
            revision=revision,
            account_active=person.is_active and person.role == Role.MERCHANT_STAFF,
        )
        for person, revision in rows
    ]


@router.put("/merchant/staff/{staff_id}/assignments", status_code=204)
def assignments(staff_id: UUID, data: AssignmentUpdate, db: DB, user: Owner) -> None:
    merchant = owned(db, user)
    # Revocation is allowed even during suspension or a new verification review.
    if data.store_ids:
        verified(merchant)
    stores_for(db, merchant, data.store_ids)
    before = list(
        db.scalars(
            select(StaffAssignment.store_id)
            .where(StaffAssignment.merchant_id == merchant.id, StaffAssignment.staff_id == staff_id)
            .order_by(StaffAssignment.store_id)
        )
    )
    roster = db.get(StaffAccess, (merchant.id, staff_id))
    if roster is None:
        if not before:
            fail("Staff member not found in your business. Invite them first.", 404)
        roster = StaffAccess(merchant_id=merchant.id, staff_id=staff_id, revision=1)
        db.add(roster)
    if roster.revision != data.revision:
        fail("Staff access changed. Refresh the roster before saving.")
    person = db.get(User, staff_id)
    if data.store_ids and (
        person is None or not person.is_active or person.role != Role.MERCHANT_STAFF
    ):
        fail("This staff account cannot receive access.")
    roster.revision += 1
    db.execute(
        delete(StaffAssignment).where(
            StaffAssignment.merchant_id == merchant.id, StaffAssignment.staff_id == staff_id
        )
    )
    for store_id in data.store_ids:
        db.add(StaffAssignment(staff_id=staff_id, merchant_id=merchant.id, store_id=store_id))
    # A link issued before a manual access change must not restore removed access.
    staff_email = db.scalar(select(User.email).where(User.id == staff_id))
    for invitation in db.scalars(
        select(Invitation).where(
            Invitation.merchant_id == merchant.id,
            Invitation.email == staff_email,
            Invitation.closed_at.is_(None),
        )
    ):
        invitation.closed_at = datetime.now(UTC)
    audit(
        db,
        user,
        merchant,
        "STAFF_ASSIGNMENTS_CHANGED",
        staff_id=str(staff_id),
        revision=roster.revision,
        before_store_ids=[str(i) for i in before],
        store_ids=[str(i) for i in data.store_ids],
    )
    db.commit()


@router.get("/merchant/staff-audit")
def staff_audit(
    db: DB, user: Owner, offset: int = Query(0, ge=0, le=10000)
) -> list[dict[str, object]]:
    merchant = owned(db, user)
    rows = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.merchant_id == merchant.id,
            AuditEvent.action.in_(
                [
                    "STAFF_INVITED",
                    "INVITATION_ACCEPTED",
                    "INVITATION_CANCELLED",
                    "STAFF_ASSIGNMENTS_CHANGED",
                ]
            ),
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        .offset(offset)
        .limit(25)
    )
    names = {
        str(s.id): s.name for s in db.scalars(select(Store).where(Store.merchant_id == merchant.id))
    }
    result = []
    for row in rows:
        actor = db.get(User, row.actor_id) if row.actor_id else None
        member = (
            db.get(User, UUID(str(row.detail["staff_id"]))) if row.detail.get("staff_id") else None
        )
        invitation = (
            db.get(Invitation, UUID(str(row.detail["invitation_id"])))
            if row.detail.get("invitation_id")
            else None
        )
        result.append(
            {
                "id": row.id,
                "created_at": row.created_at,
                "action": row.action,
                "actor": actor.display_name if actor else "Former account",
                "subject": member.display_name
                if member
                else invitation.email
                if invitation
                else "Staff member",
                "before_stores": [
                    names.get(str(i), "Former branch")
                    for i in cast(list[str], row.detail.get("before_store_ids", []))
                ],
                "stores": [
                    names.get(str(i), "Former branch")
                    for i in cast(list[str], row.detail.get("store_ids", []))
                ],
            }
        )
    return result


def accessible_stores(db: DB, user: User) -> list[Store]:
    return list(
        db.scalars(
            select(Store)
            .join(StaffAssignment, StaffAssignment.store_id == Store.id)
            .join(Merchant, Merchant.id == Store.merchant_id)
            .where(
                StaffAssignment.staff_id == user.id,
                Merchant.status == "VERIFIED",
                Store.status == "ACTIVE",
            )
            .order_by(Store.name, Store.id)
        )
    )


@router.get("/staff/stores", response_model=list[StoreOutput])
def staff_stores(db: DB, user: Staff) -> list[Store]:
    return accessible_stores(db, user)


@router.get("/staff/stores/{store_id}", response_model=StoreOutput)
def staff_store(store_id: UUID, db: DB, user: Staff) -> Store:
    for store in accessible_stores(db, user):
        if store.id == store_id:
            return store
    raise AuthError("STORE_ACCESS_DENIED", "You do not have access to this store.", 403)


@router.get("/admin/merchants", response_model=list[MerchantOutput])
def reviews(
    db: DB,
    user: Reviewer,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[
        str | None, Query(pattern="^(PENDING|UNDER_REVIEW|VERIFIED|REJECTED|SUSPENDED)$")
    ] = None,
) -> list[Merchant]:
    query = select(Merchant)
    if status:
        query = query.where(Merchant.status == status)
    return list(
        db.scalars(query.order_by(Merchant.updated_at, Merchant.id).offset(offset).limit(25))
    )


@router.put("/admin/merchants/{merchant_id}/review", response_model=MerchantOutput)
def review(merchant_id: UUID, data: ReviewInput, db: DB, user: Reviewer) -> Merchant:
    merchant = db.scalar(select(Merchant).where(Merchant.id == merchant_id).with_for_update())
    if merchant is None:
        raise AuthError("MERCHANT_NOT_FOUND", "Business not found.", 404)
    if merchant.revision != data.revision:
        fail("This profile changed. Reload it before reviewing.")
    allowed = {
        "PENDING": {"UNDER_REVIEW", "VERIFIED", "REJECTED"},
        "UNDER_REVIEW": {"VERIFIED", "REJECTED"},
        "VERIFIED": {"SUSPENDED"},
        "REJECTED": {"UNDER_REVIEW"},
        "SUSPENDED": {"UNDER_REVIEW"},
    }
    if data.status not in allowed[merchant.status]:
        fail("This verification transition is not allowed.")
    if data.status in {"REJECTED", "SUSPENDED"} and not data.note:
        fail("Provide a reason for rejection or suspension.", 422)
    previous = merchant.status
    merchant.status = data.status
    merchant.review_note = data.note
    merchant.revision += 1
    merchant.updated_at = datetime.now(UTC)
    audit(
        db,
        user,
        merchant,
        "MERCHANT_REVIEWED",
        previous=previous,
        status=data.status,
        note=data.note,
        revision=merchant.revision,
    )
    if data.status == "VERIFIED":
        from app.jobs.service import enqueue

        enqueue(
            db,
            kind="notification.merchant_approved",
            payload={"merchant_id": str(merchant.id), "revision": merchant.revision},
            key=f"merchant-approved:{merchant.id}:{merchant.revision}",
        )
    db.commit()
    db.refresh(merchant)
    return merchant


@router.get("/admin/merchants/{merchant_id}/audit")
def audit_history(merchant_id: UUID, db: DB, user: Reviewer) -> list[dict[str, object]]:
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.merchant_id == merchant_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        .limit(100)
    )
    return [
        {
            "id": event.id,
            "actor_id": event.actor_id,
            "action": event.action,
            "detail": event.detail,
            "created_at": event.created_at,
        }
        for event in events
    ]
