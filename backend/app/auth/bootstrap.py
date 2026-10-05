"""Explicit local demo provisioning or interactive administrator creation."""

import argparse
import getpass
import json
import secrets

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.core.config import Settings
from app.core.database import make_engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--email")
    args = parser.parse_args()
    settings = Settings()
    if args.demo and settings.app_env != "development":
        parser.error("Demo accounts are allowed only in development")
    engine = make_engine(settings.database_url)
    accounts: list[dict[str, str]] = []
    with Session(engine) as db, db.begin():
        if args.demo:
            for role, alias in [
                (Role.USER, "shopper"),
                (Role.MERCHANT, "merchant"),
                (Role.MERCHANT_STAFF, "staff"),
                (Role.ADMIN, "admin"),
                (Role.SUPER_ADMIN, "superadmin"),
            ]:
                email = f"{alias}@nearperk.example.com"
                if db.scalar(select(User.id).where(User.email == email)):
                    continue  # Never reset existing credentials implicitly.
                password = secrets.token_urlsafe(18)
                db.add(
                    User(
                        email=email,
                        display_name=f"Demo {alias}",
                        role=role,
                        password_hash=hash_password(password),
                    )
                )
                accounts.append({"role": role, "email": email, "password": password})
        else:
            if not args.email:
                parser.error("Provide --email to create a superadmin, or --demo for local accounts")
            email = str(TypeAdapter(EmailStr).validate_python(args.email)).casefold()
            password = getpass.getpass("New superadmin password (12–128 characters): ")
            if not 12 <= len(password) <= 128 or not password.strip():
                parser.error("Password must contain 12–128 characters")
            if password != getpass.getpass("Confirm password: "):
                parser.error("Passwords do not match")
            if db.scalar(select(User.id).where(User.email == email)):
                parser.error("Account already exists; no changes made")
            db.add(
                User(
                    email=email,
                    display_name="Platform administrator",
                    role=Role.SUPER_ADMIN,
                    password_hash=hash_password(password),
                )
            )
    engine.dispose()
    if args.demo:
        print(json.dumps(accounts))  # Redirect into ignored local documentation.
    else:
        print("Superadmin created. No password stored in output.")


if __name__ == "__main__":
    main()
