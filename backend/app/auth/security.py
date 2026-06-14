import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models import RbacRefreshToken, User

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not plain or not hashed:
        return False
    import bcrypt

    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user: User, roles: list[str]) -> str:
    expire = _now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.id),
        "user_no": user.user_no or "",
        "roles": roles,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_refresh_token(db: Session, user_id: int, *, commit: bool = True) -> str:
    raw = secrets.token_urlsafe(48)
    token_hash = _hash_refresh(raw)
    expires = _now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(
        RbacRefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires.replace(tzinfo=None),
        )
    )
    if commit:
        db.commit()
    return raw


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[int, str] | None:
    h = _hash_refresh(raw_token)
    row = (
        db.query(RbacRefreshToken)
        .filter(RbacRefreshToken.token_hash == h, RbacRefreshToken.revoked == 0)
        .order_by(RbacRefreshToken.id.desc())
        .first()
    )
    if not row:
        return None
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < _now():
        row.revoked = 1
        db.commit()
        return None
    row.revoked = 1
    row.last_used_at = _now().replace(tzinfo=None)
    new_refresh = issue_refresh_token(db, row.user_id, commit=False)
    db.commit()
    return row.user_id, new_refresh


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    h = _hash_refresh(raw_token)
    row = db.query(RbacRefreshToken).filter(RbacRefreshToken.token_hash == h, RbacRefreshToken.revoked == 0).first()
    if row:
        row.revoked = 1
        db.commit()


def unusable_password_hash() -> str:
    return hash_password(secrets.token_urlsafe(32))
