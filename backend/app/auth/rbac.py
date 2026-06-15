"""角色与菜单权限（API 鉴权走 Casbin）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.casbin_enforcer import enforce_api as casbin_enforce_api
from app.models import RbacRole, RbacUserRole, SysMenu, SysRoleMenu


def get_user_roles(db: Session, user_id: int) -> list[str]:
    rows = (
        db.query(RbacRole.code)
        .join(RbacUserRole, RbacUserRole.role_id == RbacRole.id)
        .filter(RbacUserRole.user_id == user_id, RbacRole.status == 1)
        .all()
    )
    codes = [r[0] for r in rows]
    return codes or ["viewer"]


def assign_role(db: Session, user_id: int, role_code: str) -> None:
    role = db.query(RbacRole).filter(RbacRole.code == role_code).first()
    if not role:
        return
    exists = (
        db.query(RbacUserRole)
        .filter(RbacUserRole.user_id == user_id, RbacUserRole.role_id == role.id)
        .first()
    )
    if not exists:
        db.add(RbacUserRole(user_id=user_id, role_id=role.id))
        db.commit()


def set_user_roles(db: Session, user_id: int, role_codes: list[str]) -> list[str]:
    """替换用户角色，至少保留 viewer。"""
    wanted = {c.strip() for c in role_codes if c and c.strip()}
    if not wanted:
        wanted = {"viewer"}
    roles = db.query(RbacRole).filter(RbacRole.code.in_(wanted), RbacRole.status == 1).all()
    if not roles:
        fallback = db.query(RbacRole).filter(RbacRole.code == "viewer").first()
        roles = [fallback] if fallback else []
    db.query(RbacUserRole).filter(RbacUserRole.user_id == user_id).delete()
    for role in roles:
        db.add(RbacUserRole(user_id=user_id, role_id=role.id))
    db.commit()
    return [r.code for r in roles]


def list_all_roles(db: Session) -> list[dict]:
    rows = db.query(RbacRole).filter(RbacRole.status == 1).order_by(RbacRole.id).all()
    return [{"id": r.id, "code": r.code, "name": r.name} for r in rows]


def user_has_permission(db: Session, user_id: int, permission: str) -> bool:
    roles = get_user_roles(db, user_id)
    if "admin" in roles:
        return True
    return permission in get_user_permissions(db, user_id)


def enforce_api(roles: list[str], path: str, method: str) -> bool:
    return casbin_enforce_api(roles, path, method)


def get_user_permissions(db: Session, user_id: int) -> list[str]:
    role_ids = [r[0] for r in db.query(RbacUserRole.role_id).filter(RbacUserRole.user_id == user_id).all()]
    if not role_ids:
        role_ids = [r[0] for r in db.query(RbacRole.id).filter(RbacRole.code == "viewer").all()]
    menu_ids = [m[0] for m in db.query(SysRoleMenu.menu_id).filter(SysRoleMenu.role_id.in_(role_ids)).all()]
    if not menu_ids:
        return []
    perms = (
        db.query(SysMenu.permission)
        .filter(SysMenu.id.in_(menu_ids), SysMenu.permission.isnot(None), SysMenu.status == 1)
        .all()
    )
    return sorted({p[0] for p in perms if p[0]})


def build_menu_tree(db: Session, user_id: int, platform: str = "haici") -> list[dict]:
    role_ids = [r[0] for r in db.query(RbacUserRole.role_id).filter(RbacUserRole.user_id == user_id).all()]
    if not role_ids:
        rid = db.query(RbacRole.id).filter(RbacRole.code == "viewer").scalar()
        role_ids = [rid] if rid else []
    menu_ids = {m[0] for m in db.query(SysRoleMenu.menu_id).filter(SysRoleMenu.role_id.in_(role_ids)).all()}
    menus = (
        db.query(SysMenu)
        .filter(SysMenu.platform == platform, SysMenu.status == 1, SysMenu.visible == 1, SysMenu.menu_type.in_(("M", "C")))
        .order_by(SysMenu.sort_order, SysMenu.id)
        .all()
    )
    allowed = [m for m in menus if m.id in menu_ids or "admin" in get_user_roles(db, user_id)]
    by_parent: dict[int, list[SysMenu]] = {}
    for m in allowed:
        by_parent.setdefault(m.parent_id, []).append(m)

    def _node(m: SysMenu) -> dict:
        children = [_node(c) for c in by_parent.get(m.id, [])]
        return {
            "id": m.id,
            "name": m.name,
            "path": m.path,
            "component": m.component,
            "permission": m.permission,
            "icon": m.icon,
            "menu_type": m.menu_type,
            "children": children,
        }

    return [_node(m) for m in by_parent.get(0, [])]
