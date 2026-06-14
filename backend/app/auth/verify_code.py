"""验证码：开发环境打印日志；生产可接 SMTP/短信网关。"""

from __future__ import annotations

import logging
import random
import string
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import RbacVerifyCode

logger = logging.getLogger(__name__)

CODE_TTL_MINUTES = 10


def _gen_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def send_code(db: Session, target: str, code_type: str, purpose: str) -> str:
    target = target.strip()
    code = _gen_code()
    expires = datetime.utcnow() + timedelta(minutes=CODE_TTL_MINUTES)
    db.add(
        RbacVerifyCode(
            target=target,
            code=code,
            type=code_type,
            purpose=purpose,
            expires_at=expires,
        )
    )
    db.commit()
    logger.info(
        "[登录模块-验证码|verify_code|发送|硬编执行|开发] target=%s; type=%s; purpose=%s; code=%s",
        target,
        code_type,
        purpose,
        code,
    )
    return code


def verify_code(db: Session, target: str, code_type: str, purpose: str, code: str) -> tuple[bool, str]:
    target = target.strip()
    row = (
        db.query(RbacVerifyCode)
        .filter(
            RbacVerifyCode.target == target,
            RbacVerifyCode.type == code_type,
            RbacVerifyCode.purpose == purpose,
            RbacVerifyCode.used == 0,
        )
        .order_by(RbacVerifyCode.id.desc())
        .first()
    )
    if not row:
        return False, "验证码无效或已过期"
    if row.expires_at < datetime.utcnow():
        return False, "验证码已过期"
    if row.code != code.strip():
        row.attempts += 1
        db.commit()
        return False, "验证码错误"
    row.used = 1
    db.commit()
    return True, "ok"
