"""菜单与角色种子数据。"""

from sqlalchemy.orm import Session

from app.models import RbacRole, RbacUserRole, SysMenu, SysRoleMenu, User

MENU_SEED = [
    # id, parent, type, name, path, component, permission, sort
    (1, 0, "M", "智能客服", "", "", None, 1),
    (2, 1, "C", "智能对话", "/chat", "ChatView", "chat:view", 1),
    (3, 1, "C", "会话历史", "/sessions", "SessionListView", "session:view", 2),
    (4, 2, "F", "发送消息", "", "", "chat:send", 1),
    (5, 2, "F", "消息反馈", "", "", "chat:feedback", 2),
    (6, 3, "F", "查看详情", "", "", "session:detail", 1),
    (10, 0, "M", "知识库", "", "", None, 2),
    (11, 10, "C", "文档管理", "/knowledge", "KnowledgeView", "kb:view", 1),
    (14, 10, "C", "多模态文档", "/multimodal", "MultimodalView", None, 2),
    (12, 11, "F", "上传文档", "", "", "kb:upload", 1),
    (13, 11, "F", "删除文档", "", "", "kb:delete", 2),
    (20, 0, "M", "个人中心", "", "", None, 3),
    (21, 20, "C", "基本资料", "/profile", "ProfileView", "profile:view", 1),
    (22, 20, "C", "回答反馈记录", "/profile/feedback", "ProfileFeedbackView", "profile:feedback:view", 2),
    (100, 0, "M", "日志管理", "", "", None, 98),
    (101, 100, "C", "操作日志", "/admin/logs/operation", "LogOperationView", "system:log:operation", 1),
    (102, 100, "C", "异常日志", "/admin/logs/error", "LogErrorView", "system:log:error", 2),
    (103, 100, "C", "API调用日志", "/admin/logs/api-call", "LogApiCallView", "system:log:api", 3),
    (104, 100, "C", "定时任务日志", "/admin/logs/schedule", "LogScheduleView", "system:log:schedule", 4),
    (110, 0, "M", "运维评测", "", "", None, 90),
    (111, 110, "C", "EVAL评测", "/admin/eval", "EvalDashboardView", "system:eval:view", 1),
    (112, 110, "C", "用户反馈", "/admin/feedback", "FeedbackAdminView", "system:feedback:view", 2),
]

VIEWER_MENU_IDS = {1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14, 20, 21, 22}
ADMIN_MENU_IDS = {m[0] for m in MENU_SEED}


def ensure_roles(db: Session) -> None:
    for code, name in (("admin", "管理员"), ("viewer", "普通用户")):
        row = db.query(RbacRole).filter(RbacRole.code == code).first()
        if not row:
            db.add(RbacRole(code=code, name=name, status=1))
        elif row.status != 1:
            row.status = 1
    db.commit()


def sync_log_menu_group(db: Session) -> None:
    """已有库：确保四类日志挂在「日志管理」父菜单下。"""
    parent = db.query(SysMenu).filter(SysMenu.id == 100).first()
    if not parent:
        parent = SysMenu(
            id=100,
            parent_id=0,
            menu_type="M",
            name="日志管理",
            path="",
            component="",
            permission=None,
            sort_order=99,
            platform="haici",
        )
        db.add(parent)
    else:
        parent.name = "日志管理"
        parent.menu_type = "M"
        parent.parent_id = 0
    log_children = [
        (101, "操作日志", "/admin/logs/operation", "LogOperationView", "system:log:operation", 1),
        (102, "异常日志", "/admin/logs/error", "LogErrorView", "system:log:error", 2),
        (103, "API调用日志", "/admin/logs/api-call", "LogApiCallView", "system:log:api", 3),
        (104, "定时任务日志", "/admin/logs/schedule", "LogScheduleView", "system:log:schedule", 4),
    ]
    for mid, name, path, comp, perm, sort in log_children:
        row = db.query(SysMenu).filter(SysMenu.id == mid).first()
        if not row:
            db.add(
                SysMenu(
                    id=mid,
                    parent_id=100,
                    menu_type="C",
                    name=name,
                    path=path,
                    component=comp,
                    permission=perm,
                    sort_order=sort,
                    platform="haici",
                )
            )
        else:
            row.parent_id = 100
            row.menu_type = "C"
            row.name = name
            row.path = path
            row.component = comp
            row.permission = perm
            row.sort_order = sort
    db.commit()


def sync_knowledge_multimodal_menu(db: Session) -> None:
    """已有库：确保「多模态文档」菜单挂在知识库下。"""
    parent = db.query(SysMenu).filter(SysMenu.id == 10).first()
    if not parent:
        return
    row = db.query(SysMenu).filter(SysMenu.id == 14).first()
    if not row:
        db.add(
            SysMenu(
                id=14,
                parent_id=10,
                menu_type="C",
                name="多模态文档",
                path="/multimodal",
                component="MultimodalView",
                permission=None,
                sort_order=2,
                platform="haici",
            )
        )
    else:
        row.parent_id = 10
        row.menu_type = "C"
        row.name = "多模态文档"
        row.path = "/multimodal"
        row.component = "MultimodalView"
        row.permission = None
        row.sort_order = 2
    viewer = db.query(RbacRole).filter(RbacRole.code == "viewer").first()
    if viewer:
        exists = (
            db.query(SysRoleMenu)
            .filter(SysRoleMenu.role_id == viewer.id, SysRoleMenu.menu_id == 14)
            .first()
        )
        if not exists:
            db.add(SysRoleMenu(role_id=viewer.id, menu_id=14))
    db.commit()


def sync_ops_eval_menu(db: Session) -> None:
    """已有库：运维评测父菜单 + EVAL/用户反馈二级菜单。"""
    parent = db.query(SysMenu).filter(SysMenu.id == 110).first()
    if not parent:
        db.add(
            SysMenu(
                id=110,
                parent_id=0,
                menu_type="M",
                name="运维评测",
                path="",
                component="",
                permission=None,
                sort_order=90,
                platform="haici",
            )
        )
    else:
        parent.name = "运维评测"
        parent.menu_type = "M"
        parent.parent_id = 0
        parent.sort_order = 90

    # 先处理旧 105，避免 permission 唯一约束与新建 112 冲突
    old = db.query(SysMenu).filter(SysMenu.id == 105).first()
    if old:
        old.permission = None
        db.flush()

    children = [
        (111, "EVAL评测", "/admin/eval", "EvalDashboardView", "system:eval:view", 1),
        (112, "用户反馈", "/admin/feedback", "FeedbackAdminView", "system:feedback:view", 2),
    ]
    for mid, name, path, comp, perm, sort in children:
        row = db.query(SysMenu).filter(SysMenu.id == mid).first()
        if not row:
            db.add(
                SysMenu(
                    id=mid,
                    parent_id=110,
                    menu_type="C",
                    name=name,
                    path=path,
                    component=comp,
                    permission=perm,
                    sort_order=sort,
                    platform="haici",
                )
            )
        else:
            row.parent_id = 110
            row.name = name
            row.path = path
            row.component = comp
            row.permission = perm
            row.sort_order = sort

    if old:
        for rm in db.query(SysRoleMenu).filter(SysRoleMenu.menu_id == 105).all():
            dup = (
                db.query(SysRoleMenu)
                .filter(SysRoleMenu.role_id == rm.role_id, SysRoleMenu.menu_id == 112)
                .first()
            )
            if dup:
                db.delete(rm)
            else:
                rm.menu_id = 112
        db.delete(old)
        db.flush()

    admin = db.query(RbacRole).filter(RbacRole.code == "admin").first()
    if admin:
        for mid in (110, 111, 112):
            exists = db.query(SysRoleMenu).filter(SysRoleMenu.role_id == admin.id, SysRoleMenu.menu_id == mid).first()
            if not exists:
                db.add(SysRoleMenu(role_id=admin.id, menu_id=mid))
    db.commit()


def sync_agent_settings_menu(db: Session) -> None:
    """已有库：Agent设置父菜单 + Agent配置/Agent网关二级菜单。"""
    parent = db.query(SysMenu).filter(SysMenu.id == 120).first()
    if not parent:
        db.add(
            SysMenu(
                id=120,
                parent_id=0,
                menu_type="M",
                name="Agent设置",
                path="",
                component="",
                permission=None,
                sort_order=80,
                platform="haici",
            )
        )
    else:
        parent.menu_type = "M"
        parent.name = "Agent设置"
        parent.path = ""
        parent.component = ""
        parent.permission = None
        parent.sort_order = 80

    children = [
        (121, "Agent配置", "/admin/agent-config", "AgentConfigView", "system:agent:config", 1),
        (122, "Agent网关", "/admin/agent-gateway", "AgentGatewayView", "system:agent:gateway", 2),
    ]
    for mid, name, path, comp, perm, sort in children:
        row = db.query(SysMenu).filter(SysMenu.id == mid).first()
        if not row:
            db.add(
                SysMenu(
                    id=mid,
                    parent_id=120,
                    menu_type="C",
                    name=name,
                    path=path,
                    component=comp,
                    permission=perm,
                    sort_order=sort,
                    platform="haici",
                )
            )
        else:
            row.parent_id = 120
            row.name = name
            row.path = path
            row.component = comp
            row.permission = perm
            row.sort_order = sort

    for role_code in ("admin",):
        role = db.query(RbacRole).filter(RbacRole.code == role_code).first()
        if not role:
            continue
        for mid in (120, 121, 122):
            exists = db.query(SysRoleMenu).filter(SysRoleMenu.role_id == role.id, SysRoleMenu.menu_id == mid).first()
            if not exists:
                db.add(SysRoleMenu(role_id=role.id, menu_id=mid))
    db.commit()


def sync_feedback_menu(db: Session) -> None:
    """兼容旧函数名 → 运维评测菜单同步。"""
    sync_ops_eval_menu(db)


def sync_profile_menu_group(db: Session) -> None:
    """已有库：个人中心父菜单 + 基本资料 / 回答反馈记录。"""
    parent = db.query(SysMenu).filter(SysMenu.id == 20).first()
    if not parent:
        db.add(
            SysMenu(
                id=20,
                parent_id=0,
                menu_type="M",
                name="个人中心",
                path="",
                component="",
                permission=None,
                sort_order=3,
                platform="haici",
            )
        )
    else:
        parent.menu_type = "M"
        parent.name = "个人中心"
        parent.path = ""
        parent.component = ""
        parent.permission = None
        parent.sort_order = 3

    children = [
        (21, "基本资料", "/profile", "ProfileView", "profile:view", 1),
        (22, "回答反馈记录", "/profile/feedback", "ProfileFeedbackView", "profile:feedback:view", 2),
    ]
    for mid, name, path, comp, perm, sort in children:
        row = db.query(SysMenu).filter(SysMenu.id == mid).first()
        if not row:
            db.add(
                SysMenu(
                    id=mid,
                    parent_id=20,
                    menu_type="C",
                    name=name,
                    path=path,
                    component=comp,
                    permission=perm,
                    sort_order=sort,
                    platform="haici",
                )
            )
        else:
            row.parent_id = 20
            row.name = name
            row.path = path
            row.component = comp
            row.permission = perm
            row.sort_order = sort

    for role_code in ("viewer", "admin"):
        role = db.query(RbacRole).filter(RbacRole.code == role_code).first()
        if not role:
            continue
        for mid in (20, 21, 22):
            exists = db.query(SysRoleMenu).filter(SysRoleMenu.role_id == role.id, SysRoleMenu.menu_id == mid).first()
            if not exists:
                db.add(SysRoleMenu(role_id=role.id, menu_id=mid))
    db.commit()


def seed_menus(db: Session) -> None:
    if db.query(SysMenu).first():
        return
    for mid, pid, mtype, name, path, comp, perm, sort in MENU_SEED:
        db.add(
            SysMenu(
                id=mid,
                parent_id=pid,
                menu_type=mtype,
                name=name,
                path=path,
                component=comp,
                permission=perm,
                sort_order=sort,
                platform="haici",
            )
        )
    db.commit()
    viewer = db.query(RbacRole).filter(RbacRole.code == "viewer").first()
    admin = db.query(RbacRole).filter(RbacRole.code == "admin").first()
    if viewer:
        for mid in VIEWER_MENU_IDS:
            db.add(SysRoleMenu(role_id=viewer.id, menu_id=mid))
    if admin:
        for mid in ADMIN_MENU_IDS:
            db.add(SysRoleMenu(role_id=admin.id, menu_id=mid))
    db.commit()


def backfill_user_no(db: Session) -> None:
    from app.auth.user_no import generate_user_no

    for user in db.query(User).filter(User.user_no.is_(None)).all():
        user.user_no = generate_user_no(db)
        if not user.nickname:
            user.nickname = f"小鱼儿_{user.user_no}"
        if user.status is None:
            user.status = 1
    db.commit()


def ensure_bootstrap_admin(db: Session) -> None:
    """开发/演示用内置管理员：用户名 admin / 密码 admin。"""
    from app.auth.security import hash_password
    from app.auth.user_no import generate_user_no

    admin_role = db.query(RbacRole).filter(RbacRole.code == "admin").first()
    user = db.query(User).filter(User.username == "admin").first()
    if not user:
        user_no = generate_user_no(db)
        user = User(
            username="admin",
            email="admin@haici.local",
            password_hash=hash_password("admin"),
            nickname="系统管理员",
            user_no=user_no,
            status=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.password_hash = hash_password("admin")
        user.status = 1
        if not user.user_no:
            user.user_no = generate_user_no(db)
        db.commit()
    if admin_role:
        exists = (
            db.query(RbacUserRole)
            .filter(RbacUserRole.user_id == user.id, RbacUserRole.role_id == admin_role.id)
            .first()
        )
        if not exists:
            db.add(RbacUserRole(user_id=user.id, role_id=admin_role.id))
            db.commit()


def ensure_admin_user(db: Session, email: str = "demo@haici.com") -> None:
    """兼容旧 demo 邮箱管理员绑定。"""
    admin_role = db.query(RbacRole).filter(RbacRole.code == "admin").first()
    user = db.query(User).filter(User.email == email).first()
    if user and admin_role:
        exists = (
            db.query(RbacUserRole)
            .filter(RbacUserRole.user_id == user.id, RbacUserRole.role_id == admin_role.id)
            .first()
        )
        if not exists:
            db.add(RbacUserRole(user_id=user.id, role_id=admin_role.id))
            db.commit()
