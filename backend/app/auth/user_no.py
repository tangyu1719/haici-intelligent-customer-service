"""对外用户编号：SHA-256 哈希映射为 10 位数字，非自增、不可推测。"""

from __future__ import annotations

import hashlib
import secrets
import time

from sqlalchemy.orm import Session

from app.config import settings
from app.models import User

MAX_RETRY = 5


def _hash_to_user_no(raw: bytes) -> str:
    digest = hashlib.sha256(raw).digest()
    n = int.from_bytes(digest[:8], byteorder="big") % 9_000_000_000
    return str(1_000_000_000 + n)


def generate_user_no(db: Session) -> str:
    secret = (settings.USER_NO_HASH_SECRET or settings.SECRET_KEY or "haici").encode()
    for _ in range(MAX_RETRY):
        raw = secrets.token_bytes(16) + secret + str(time.time_ns()).encode() + secrets.token_bytes(8)
        candidate = _hash_to_user_no(raw)
        if not db.query(User).filter(User.user_no == candidate).first():
            return candidate
    raise RuntimeError("无法生成唯一 user_no")


def default_sms_nickname(user_no: str) -> str:
    return f"小鱼儿_{user_no}"
