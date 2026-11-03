from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import User

PERSONAL_USER_ID = "00000000-0000-4000-8000-000000000001"


def local_address(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host or "").is_loopback
    except ValueError:
        return False


def local_request(request: Request) -> bool:
    if not request.client or not local_address(request.client.host):
        return False
    if not local_address(request.url.hostname):
        return False
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    for value in (request.headers.get("origin"), request.headers.get("x-forwarded-host")):
        if value:
            try:
                host = urlsplit(value if "://" in value else "//" + value).hostname
            except ValueError:
                return False
            if not local_address(host):
                return False
    return True


def personal_user(db: Session) -> User:
    user = db.get(User, PERSONAL_USER_ID)
    if user is None:
        # 固定主键让并发首次访问得到同一身份，不接管已有账号。
        db.execute(
            insert(User)
            .values(
                id=PERSONAL_USER_ID,
                email="personal@learnflow.invalid",
                name="本地用户",
                password_hash="!personal",
            )
            .on_conflict_do_nothing(index_elements=[User.id])
        )
        db.commit()
        user = db.get(User, PERSONAL_USER_ID)
    return user
