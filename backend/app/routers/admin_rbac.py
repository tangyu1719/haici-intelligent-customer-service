"""管理员：用户 RBAC 与配额查询。"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.rbac import get_user_roles, list_all_roles, set_user_roles
from app.config import settings
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models import DailyQuestionUsage, RbacRole, RbacUserRole, SysMenu, SysRoleMenu, User
from app.services.list_query import (
    ListQuery,
    apply_keyword,
    apply_sort,
    list_query_params,
    page_result,
    paginate,
)
from app.services.rate_limit import get_daily_quota_status, resolve_daily_limit

router = APIRouter(prefix="/admin/rbac", tags=["系统管理-RBAC"])


class RoleItem(BaseModel):
    id: int
    code: str
    name: str


class RolePageResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[RoleItem]


class UserAdminItem(BaseModel):
    id: int
    user_no: str | None
    username: str | None
    email: str | None
    phone: str | None
    nickname: str
    status: int
    roles: list[str]
    daily_questions_used: int
    daily_question_limit: int | None
    daily_questions_remaining: int | None
    daily_quota_unlimited: bool
    created_at: datetime | None


class UserPageResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[UserAdminItem]


class SetUserRolesRequest(BaseModel):
    roles: list[str] = Field(min_length=1, max_length=8)


class SetUserStatusRequest(BaseModel):
    status: int = Field(ge=0, le=1)


class QuotaSettingsResponse(BaseModel):
    daily_question_limit: int
    daily_question_limit_admin: int


def _user_roles_map(db: Session, user_ids: list[int]) -> dict[int, list[str]]:
    if not user_ids:
        return {}
    rows = (
        db.query(RbacUserRole.user_id, RbacRole.code)
        .join(RbacRole, RbacRole.id == RbacUserRole.role_id)
        .filter(RbacUserRole.user_id.in_(user_ids), RbacRole.status == 1)
        .all()
    )
    out: dict[int, list[str]] = {uid: [] for uid in user_ids}
    for uid, code in rows:
        out.setdefault(uid, []).append(code)
    for uid in user_ids:
        if not out.get(uid):
            out[uid] = ["viewer"]
    return out


def _usage_map(db: Session, user_ids: list[int]) -> dict[int, int]:
    if not user_ids:
        return {}
    today = date.today()
    rows = (
        db.query(DailyQuestionUsage.user_id, DailyQuestionUsage.question_count)
        .filter(DailyQuestionUsage.user_id.in_(user_ids), DailyQuestionUsage.usage_date == today)
        .all()
    )
    return {uid: int(cnt) for uid, cnt in rows}


def _to_admin_item(db: Session, user: User, roles: list[str], used: int) -> UserAdminItem:
    limit = resolve_daily_limit(roles)
    unlimited = limit is None
    remaining = None if unlimited else max(0, limit - used)
    return UserAdminItem(
        id=user.id,
        user_no=user.user_no,
        username=user.username,
        email=user.email,
        phone=user.phone,
        nickname=user.nickname or "",
        status=user.status,
        roles=roles,
        daily_questions_used=used,
        daily_question_limit=limit,
        daily_questions_remaining=remaining,
        daily_quota_unlimited=unlimited,
        created_at=user.created_at,
    )


@router.get("/roles", response_model=list[RoleItem])
def list_roles(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [RoleItem(**r) for r in list_all_roles(db)]


@router.get("/roles/page", response_model=RolePageResponse)
def list_roles_page(
    qry: ListQuery = Depends(list_query_params),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(RbacRole).filter(RbacRole.status == 1)
    q = apply_keyword(q, qry, [RbacRole.code, RbacRole.name])
    q = apply_sort(q, RbacRole, qry, {"id": RbacRole.id, "code": RbacRole.code}, RbacRole.id)
    rows, total = paginate(q, qry)
    items = [RoleItem(id=r.id, code=r.code, name=r.name) for r in rows]
    return RolePageResponse(**page_result(items, total, qry))


# ── 权限模块定义 ───────────────────────────────────────────

PERMISSION_MODULES: dict[str, dict] = {
    "chat": {"label": "智能客服", "icon": "fa-comments", "desc": "AI对话交互", "perms": [
        {"key": "chat:view", "label": "查看智能对话页面"},
        {"key": "chat:send", "label": "发送消息/提问"},
        {"key": "chat:feedback", "label": "对回答进行反馈(点赞/踩)"},
    ]},
    "session": {"label": "会话管理", "icon": "fa-clock", "desc": "对话会话记录", "perms": [
        {"key": "session:view", "label": "查看会话列表"},
        {"key": "session:detail", "label": "查看会话详情与消息历史"},
        {"key": "session:view:all", "label": "在「会话历史」中查看全部用户会话（可按用户筛选）"},
        {"key": "system:session:view", "label": "会话审计（运维评测菜单，含用户已删记录）"},
    ]},
    "kb": {"label": "知识库管理", "icon": "fa-database", "desc": "知识库文档+向量", "perms": [
        {"key": "kb:view", "label": "查看知识库文档列表"},
        {"key": "kb:upload", "label": "上传文档到知识库"},
        {"key": "kb:delete", "label": "删除知识库文档"},
    ]},
    "profile": {"label": "个人中心", "icon": "fa-user", "desc": "个人信息与反馈记录", "perms": [
        {"key": "profile:view", "label": "查看基本资料"},
        {"key": "profile:feedback:view", "label": "查看个人反馈记录"},
    ]},
    "system:log": {"label": "日志管理", "icon": "fa-list-alt", "desc": "系统运维日志(只读)", "perms": [
        {"key": "system:log:operation", "label": "查看操作日志"},
        {"key": "system:log:error", "label": "查看异常日志"},
        {"key": "system:log:api", "label": "查看API调用日志"},
        {"key": "system:log:schedule", "label": "查看定时任务日志"},
    ]},
    "system:eval": {"label": "运维评测", "icon": "fa-chart-bar", "desc": "EVAL评测看板", "perms": [
        {"key": "system:eval:view", "label": "查看EVAL评测看板"},
    ]},
    "system:feedback": {"label": "用户反馈管理", "icon": "fa-star", "desc": "管理员查看全量反馈", "perms": [
        {"key": "system:feedback:view", "label": "查看用户反馈列表与分析"},
    ]},
    "system:agent": {"label": "Agent设置", "icon": "fa-robot", "desc": "Agent配置+网关+安全+缓存+熔断", "perms": [
        {"key": "system:agent:config", "label": "编辑Agent Prompt配置"},
        {"key": "system:agent:gateway", "label": "管理网关节点与路由规则"},
        {"key": "system:agent:security", "label": "管理安全合规(PII/敏感词)"},
        {"key": "system:agent:cache", "label": "管理缓存统计与清除"},
        {"key": "system:agent:circuit", "label": "查看熔断监控与恢复"},
    ]},
    "system:rbac": {"label": "权限管理", "icon": "fa-shield-alt", "desc": "角色与权限分配", "perms": [
        {"key": "system:rbac:users", "label": "查看/管理用户角色"},
        {"key": "system:rbac:roles", "label": "配置角色权限（勾选模块权限）"},
    ]},
    "system:settings": {"label": "系统设置", "icon": "fa-cog", "desc": "全局运行参数", "perms": [
        {"key": "system:settings:manage", "label": "管理系统设置（会话落库间隔等）"},
    ]},
}


@router.get("/permission-modules")
def list_permission_modules(_user=Depends(get_current_user)):
    """按业务模块列出所有权限（用业务语言描述，而非技术接口名）"""
    return {"ok": True, "modules": [
        {"module_key": k, "label": v["label"], "icon": v["icon"],
         "description": v["desc"], "perms": v["perms"]}
        for k, v in PERMISSION_MODULES.items()
    ]}


@router.get("/permission-matrix")
def get_permission_matrix(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    """角色-权限矩阵：哪些角色拥有哪些权限"""
    roles = db.query(RbacRole).filter(RbacRole.status == 1).all()
    all_perms = {
        m.permission
        for m in db.query(SysMenu).filter(
            SysMenu.permission.isnot(None), SysMenu.permission != ""
        ).all()
    }
    matrix: list[dict] = []
    for role in roles:
        role_menu_ids = {
            rm.menu_id for rm in db.query(SysRoleMenu).filter(
                SysRoleMenu.role_id == role.id
            ).all()
        }
        role_perms = sorted(
            m.permission for m in db.query(SysMenu).filter(
                SysMenu.id.in_(role_menu_ids), SysMenu.permission.in_(all_perms)
            ).all() if m.permission
        )
        matrix.append({
            "role": {"id": role.id, "code": role.code, "name": role.name},
            "permissions": role_perms,
        })
    return {"ok": True, "matrix": matrix, "all_permissions": sorted(all_perms)}


@router.get("/quota-settings", response_model=QuotaSettingsResponse)
def quota_settings(_admin: User = Depends(require_admin)):
    return QuotaSettingsResponse(
        daily_question_limit=settings.DAILY_QUESTION_LIMIT,
        daily_question_limit_admin=settings.DAILY_QUESTION_LIMIT_ADMIN,
    )


@router.get("/users", response_model=UserPageResponse)
def list_users(
    qry: ListQuery = Depends(list_query_params),
    status: int | None = Query(None, ge=0, le=1),
    role: str | None = Query(None, description="按角色 code 筛选"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if status is not None:
        q = q.filter(User.status == status)
    if role:
        q = (
            q.join(RbacUserRole, RbacUserRole.user_id == User.id)
            .join(RbacRole, RbacRole.id == RbacUserRole.role_id)
            .filter(RbacRole.code == role)
        )
    q = apply_keyword(q, qry, [User.username, User.email, User.phone, User.nickname, User.user_no])
    q = apply_sort(q, User, qry, {"created_at": User.created_at, "id": User.id, "username": User.username}, User.id)
    rows, total = paginate(q, qry)
    user_ids = [u.id for u in rows]
    roles_map = _user_roles_map(db, user_ids)
    usage_map = _usage_map(db, user_ids)
    items = [_to_admin_item(db, u, roles_map.get(u.id, ["viewer"]), usage_map.get(u.id, 0)) for u in rows]
    return UserPageResponse(**page_result(items, total, qry))


@router.put("/users/{user_id}/roles", response_model=UserAdminItem)
def update_user_roles(
    user_id: int,
    body: SetUserRolesRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id and "admin" not in body.roles:
        raise HTTPException(status_code=400, detail="不能移除自己的管理员角色")
    roles = set_user_roles(db, user_id, body.roles)
    used = _usage_map(db, [user_id]).get(user_id, 0)
    return _to_admin_item(db, user, roles, used)


@router.patch("/users/{user_id}/status", response_model=UserAdminItem)
def update_user_status(
    user_id: int,
    body: SetUserStatusRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id and body.status != 1:
        raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
    user.status = body.status
    db.commit()
    db.refresh(user)
    roles = get_user_roles(db, user.id)
    used = _usage_map(db, [user_id]).get(user_id, 0)
    return _to_admin_item(db, user, roles, used)


@router.get("/users/{user_id}/quota")
def user_quota_detail(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    roles = get_user_roles(db, user.id)
    return get_daily_quota_status(db, user, roles)


class SaveRolePermissionsBody(BaseModel):
    permissions: list[str] = Field(default_factory=list)


@router.put("/roles/{role_id}/permissions")
def save_role_permissions(
    role_id: int,
    body: SaveRolePermissionsBody,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """为角色配置模块化权限"""
    role = db.get(RbacRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 清除旧权限
    db.query(SysRoleMenu).filter(SysRoleMenu.role_id == role_id).delete()

    # 根据permission值查找对应的menu_id并分配
    for perm in body.permissions:
        menu = db.query(SysMenu).filter(SysMenu.permission == perm).first()
        if menu:
            # 同时分配父菜单
            if menu.parent_id and menu.parent_id != 0:
                exists = db.query(SysRoleMenu).filter(
                    SysRoleMenu.role_id == role_id,
                    SysRoleMenu.menu_id == menu.parent_id,
                ).first()
                if not exists:
                    db.add(SysRoleMenu(role_id=role_id, menu_id=menu.parent_id))
            db.add(SysRoleMenu(role_id=role_id, menu_id=menu.id))

    db.commit()
    return {"ok": True, "role_id": role_id, "count": len(body.permissions)}
