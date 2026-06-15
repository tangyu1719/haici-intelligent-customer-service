"""权限管理 API — 菜单权限+按钮权限(接口权限)+知识库权限+角色分配"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import RbacRole, RbacUserRole, SysMenu, SysRoleMenu, User

router = APIRouter(prefix="/admin/permission", tags=["权限管理"])

# ── 权限模块定义（业务视角） ──────────────────────────────

PERMISSION_MODULES: dict[str, dict] = {
    "chat": {
        "label": "智能客服",
        "icon": "fa-comments",
        "description": "AI对话交互",
        "perms": {
            "chat:view": "查看智能对话页面",
            "chat:send": "发送消息/提问",
            "chat:feedback": "对回答进行反馈(点赞/踩)",
        },
    },
    "session": {
        "label": "会话管理",
        "icon": "fa-clock",
        "description": "对话会话记录",
        "perms": {
            "session:view": "查看会话列表",
            "session:detail": "查看会话详情与消息历史",
        },
    },
    "kb": {
        "label": "知识库管理",
        "icon": "fa-database",
        "description": "知识库文档+向量",
        "perms": {
            "kb:view": "查看知识库文档列表",
            "kb:upload": "上传文档到知识库",
            "kb:delete": "删除知识库文档",
        },
    },
    "profile": {
        "label": "个人中心",
        "icon": "fa-user",
        "description": "个人信息与反馈记录",
        "perms": {
            "profile:view": "查看基本资料",
            "profile:feedback:view": "查看个人反馈记录",
        },
    },
    "system:log": {
        "label": "日志管理",
        "icon": "fa-list-alt",
        "description": "系统运维日志(只读)",
        "perms": {
            "system:log:operation": "查看操作日志",
            "system:log:error": "查看异常日志",
            "system:log:api": "查看API调用日志",
            "system:log:schedule": "查看定时任务日志",
        },
    },
    "system:eval": {
        "label": "运维评测",
        "icon": "fa-chart-bar",
        "description": "EVAL评测+用户反馈",
        "perms": {
            "system:eval:view": "查看EVAL评测看板",
        },
    },
    "system:feedback": {
        "label": "用户反馈管理",
        "icon": "fa-star",
        "description": "管理员查看全量反馈",
        "perms": {
            "system:feedback:view": "查看用户反馈列表与分析",
        },
    },
    "system:agent": {
        "label": "Agent设置",
        "icon": "fa-robot",
        "description": "Agent配置+网关+安全+缓存+熔断",
        "perms": {
            "system:agent:config": "查看/编辑Agent配置",
            "system:agent:gateway": "管理网关节点与路由",
            "system:agent:security": "管理安全合规(PII/敏感词)",
            "system:agent:cache": "管理缓存统计与清除",
            "system:agent:circuit": "查看熔断监控",
        },
    },
    "system:rbac": {
        "label": "权限管理",
        "icon": "fa-shield-alt",
        "description": "角色与权限分配",
        "perms": {
            "system:rbac:users": "查看/管理用户角色权限",
        },
    },
}


# ── 响应模型 ──

class PermItem(BaseModel):
    key: str
    label: str
    description: str = ""


class ModulePerms(BaseModel):
    module_key: str
    label: str
    icon: str
    description: str
    perms: list[PermItem]


class RoleItem(BaseModel):
    id: int
    code: str
    name: str


class RolePermMatrix(BaseModel):
    role: RoleItem
    permissions: list[str]


# ── API ──

@router.get("/modules")
def list_permission_modules(_user=Depends(get_current_user)):
    """按业务模块列出所有权限（业务描述而非技术接口名）"""
    modules: list[dict] = []
    for key, mod in PERMISSION_MODULES.items():
        perms = [
            {"key": pk, "label": pl, "description": pl}
            for pk, pl in mod["perms"].items()
        ]
        modules.append({
            "module_key": key,
            "label": mod["label"],
            "icon": mod["icon"],
            "description": mod["description"],
            "perms": perms,
        })
    return {"ok": True, "modules": modules}


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    """列出所有角色"""
    roles = db.query(RbacRole).filter(RbacRole.status == 1).all()
    return {
        "ok": True,
        "roles": [
            {"id": r.id, "code": r.code, "name": r.name}
            for r in roles
        ],
    }


@router.get("/matrix")
def get_permission_matrix(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    """获取角色-权限矩阵"""
    roles = db.query(RbacRole).filter(RbacRole.status == 1).all()
    all_menu_ids = {m.id for m in db.query(SysMenu).filter(SysMenu.permission.isnot(None), SysMenu.permission != "").all()}

    matrix: list[dict] = []
    for role in roles:
        role_menu_ids = {
            rm.menu_id
            for rm in db.query(SysRoleMenu).filter(SysRoleMenu.role_id == role.id).all()
        }
        menu_perms = {
            m.permission
            for m in db.query(SysMenu)
            .filter(SysMenu.id.in_(role_menu_ids & all_menu_ids))
            .all()
            if m.permission
        }
        matrix.append({
            "role": {"id": role.id, "code": role.code, "name": role.name},
            "permissions": sorted(menu_perms),
        })
    return {"ok": True, "matrix": matrix}


@router.get("/users")
def list_users_with_roles(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """列出用户及其角色（简要）"""
    users = db.query(User).filter(User.status == 1).order_by(User.id).limit(100).all()
    items: list[dict] = []
    for u in users:
        role_rows = (
            db.query(RbacRole.code, RbacRole.name)
            .join(RbacUserRole, RbacUserRole.role_id == RbacRole.id)
            .filter(RbacUserRole.user_id == u.id, RbacRole.status == 1)
            .all()
        )
        items.append({
            "user_id": u.id,
            "user_no": u.user_no or "",
            "username": u.username or "",
            "nickname": u.nickname or "",
            "email": u.email or "",
            "roles": [{"code": r[0], "name": r[1]} for r in role_rows],
        })
    return {"ok": True, "users": items}


@router.post("/assign")
def assign_role_to_user(
    user_id: int = Query(..., ge=1),
    role_code: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """为用户分配角色"""
    from app.auth.rbac import assign_role
    assign_role(db, user_id, role_code)
    return {"ok": True, "user_id": user_id, "role_code": role_code}
