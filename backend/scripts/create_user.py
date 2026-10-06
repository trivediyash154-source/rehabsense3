"""Create a user with a given role (admin/technician accounts cannot self-register).

    cd backend && python -m scripts.create_user --email ops@example.com --role ADMIN --name "Ops"

The password is read from the REHABSENSE_NEW_PASSWORD environment variable or
prompted for; it is never accepted on the command line (shell history).
"""

from __future__ import annotations

import argparse
import getpass
import os

from sqlalchemy import select

from app.core.security import hash_password
from app.db.database import SessionLocal
from app.db.models.audit import AuditAction
from app.db.models.user import Role, User
from app.services import audit_service


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--role", required=True, choices=[r.value for r in Role])
    args = ap.parse_args()
    password = os.environ.get("REHABSENSE_NEW_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < 12:
        raise SystemExit("password must be at least 12 characters")
    db = SessionLocal()
    try:
        if db.execute(select(User).where(User.email == args.email.lower())).scalar_one_or_none():
            raise SystemExit(f"{args.email} already exists")
        user = User(email=args.email.lower(), name=args.name, role=Role(args.role),
                    password_hash=hash_password(password))
        db.add(user)
        db.flush()
        audit_service.record(db, action=AuditAction.USER_REGISTERED, entity_type="user",
                             entity_id=user.id, role=args.role, via="create_user")
        db.commit()
        print(f"created {args.role} {args.email} (id {user.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
