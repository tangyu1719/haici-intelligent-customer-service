"""Casbin Enforcer：优先 pycasbin；不可用时原生匹配 casbin_rule 表。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.auth.casbin_policies import ALL_API_POLICIES
from app.database import SessionLocal, engine
from app.models import CasbinRule

logger = logging.getLogger(__name__)

_MODEL = Path(__file__).resolve().parent / "casbin_model.conf"
_enforcer = None
_use_native = False


def _key_match3(key1: str, key2: str) -> bool:
    if key2.endswith("/*"):
        return key1 == key2[:-2] or key1.startswith(key2[:-1])
    return key1 == key2


def _regex_match(value: str, pattern: str) -> bool:
    return re.match(f"^({pattern})$", value) is not None


def _load_policies(db: Session) -> list[tuple[str, str, str]]:
    rows = db.query(CasbinRule).filter(CasbinRule.ptype == "p").all()
    if rows:
        return [(r.v0, r.v1, r.v2) for r in rows]
    return list(ALL_API_POLICIES)


def _native_enforce(roles: list[str], path: str, method: str) -> bool:
    db = SessionLocal()
    try:
        policies = _load_policies(db)
    finally:
        db.close()
    act = method.upper()
    for role in roles:
        for sub, obj, act_re in policies:
            if role != sub:
                continue
            if _key_match3(path, obj) and _regex_match(act, act_re):
                return True
    return False


def _native_seed(force: bool = False) -> None:
    db = SessionLocal()
    try:
        exists = db.query(CasbinRule).filter(CasbinRule.ptype == "p").first()
        if exists and not force:
            return
        if force:
            db.query(CasbinRule).filter(CasbinRule.ptype == "p").delete()
        for role, obj, act in ALL_API_POLICIES:
            db.add(CasbinRule(ptype="p", v0=role, v1=obj, v2=act))
        db.commit()
        logger.info("[登录模块-Casbin|casbin_enforcer|原生策略种子|硬编执行|完成] count=%s", len(ALL_API_POLICIES))
    finally:
        db.close()


def _get_pycasbin_enforcer():
    import casbin
    from casbin_sqlalchemy_adapter import Adapter

    adapter = Adapter(engine)
    enforcer = casbin.Enforcer(str(_MODEL), adapter)
    enforcer.enable_auto_save(True)
    return enforcer


def get_enforcer():
    global _enforcer, _use_native
    if _enforcer is not None or _use_native:
        return _enforcer
    try:
        _enforcer = _get_pycasbin_enforcer()
        return _enforcer
    except Exception as exc:
        logger.warning("[登录模块-Casbin|casbin_enforcer|pycasbin|硬编执行|降级] err=%s", str(exc)[:120])
        _use_native = True
        return None


def seed_casbin_policies(force: bool = False) -> None:
    enforcer = get_enforcer()
    if enforcer is None:
        _native_seed(force)
        return
    policies = enforcer.get_policy()
    if policies and not force:
        # 历史库可能存了 6 列空字段，与模型 3 列不一致会导致 enforce 崩溃
        if any(len(p) > 3 for p in policies):
            force = True
    if force:
        enforcer.clear_policy()
    for role, obj, act in ALL_API_POLICIES:
        if not enforcer.has_policy(role, obj, act):
            enforcer.add_policy(role, obj, act)
    enforcer.save_policy()
    logger.info("[登录模块-Casbin|casbin_enforcer|pycasbin策略种子|硬编执行|完成] total=%s", len(enforcer.get_policy()))


def enforce_api(roles: list[str], path: str, method: str) -> bool:
    enforcer = get_enforcer()
    act = method.upper()
    if enforcer is None:
        return _native_enforce(roles, path, act)
    try:
        for role in roles:
            if enforcer.enforce(role, path, act):
                return True
        return False
    except RuntimeError as exc:
        if "invalid policy size" in str(exc):
            logger.warning(
                "[登录模块-Casbin|casbin_enforcer|enforce_api|硬编执行|降级] err=%s",
                str(exc)[:120],
            )
            return _native_enforce(roles, path, act)
        raise
