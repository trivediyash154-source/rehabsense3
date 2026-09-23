"""The authenticated user's own profile."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbDep
from app.schemas.user import UserPublic, UserUpdate

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserPublic)
def me(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)


@router.patch("/me", response_model=UserPublic)
def update_me(payload: UserUpdate, user: CurrentUser, db: DbDep) -> UserPublic:
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return UserPublic.model_validate(user)
