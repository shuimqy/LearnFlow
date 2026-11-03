import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import User, UserSession

DB = Annotated[Session, Depends(get_db)]
password_hasher = PasswordHash.recommended()
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(24))
COOKIE_NAME = "learnflow_session"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id: str, response: Response) -> None:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    lifetime = timedelta(days=settings.session_days)
    db.add(
        UserSession(
            token_hash=hash_token(token), user_id=user_id, expires_at=datetime.now(UTC) + lifetime
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=int(lifetime.total_seconds()),
        path="/",
    )


def get_current_user(request: Request, db: DB) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        user = db.scalar(
            select(User)
            .join(UserSession)
            .where(
                UserSession.token_hash == hash_token(token),
                UserSession.expires_at > datetime.now(UTC),
            )
        )
        if user:
            return user
    raise HTTPException(401, "请先登录")


CurrentUser = Annotated[User, Depends(get_current_user)]
