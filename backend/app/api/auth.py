from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, select

from app.core.auth import (
    COOKIE_NAME,
    DB,
    DUMMY_HASH,
    CurrentUser,
    create_session,
    hash_token,
    password_hasher,
)
from app.models import User, UserSession
from app.schemas import Credentials, Register, UserOut

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register(payload: Register, response: Response, db: DB):
    if db.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(409, "这个邮箱已经注册，可以直接登录")
    user = User(
        email=payload.email, name=payload.name, password_hash=password_hasher.hash(payload.password)
    )
    db.add(user)
    db.flush()
    create_session(db, user.id, response)
    return user


@router.post("/auth/login", response_model=UserOut)
def login(payload: Credentials, response: Response, db: DB):
    user = db.scalar(select(User).where(User.email == payload.email))
    valid = password_hasher.verify(payload.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, "邮箱或密码不正确")
    create_session(db, user.id, response)
    return user


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DB):
    if token := request.cookies.get(COOKIE_NAME):
        db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
