"""运维日志只读 API（admin）：分页 + 筛选 + 排序。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import SysLogApiCall, SysLogError, SysLogOperation, SysLogSchedule, User
from app.services.list_query import (
    ListQuery,
    apply_date_range,
    apply_id_filter,
    apply_keyword,
    apply_like,
    apply_sort,
    list_query_params,
    page_result,
    paginate,
)

router = APIRouter(prefix="/admin/logs", tags=["运维日志"])


class LogPage(BaseModel):
    total: int
    page: int
    size: int
    items: list[dict]


def _row_to_dict(row: Any) -> dict:
    d = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def _query_logs(model, db: Session, qry: ListQuery, *, keyword_cols: list, sort_map: dict, date_col, name_col=None, extra_filters: dict | None = None) -> LogPage:
    q = db.query(model)
    q = apply_id_filter(q, model.log_id, qry)
    if qry.name and name_col is not None:
        q = apply_like(q, name_col, qry.name)
    q = apply_keyword(q, qry, keyword_cols)
    q = apply_date_range(q, date_col, qry)
    if extra_filters:
        for key, val in extra_filters.items():
            if val is not None and val != "":
                col = getattr(model, key, None)
                if col is not None:
                    q = q.filter(col == val)
    q = apply_sort(q, model, qry, sort_map, model.log_id)
    rows, total = paginate(q, qry)
    return LogPage(**page_result([_row_to_dict(r) for r in rows], total, qry))


@router.get("/operation", response_model=LogPage)
def list_operation_logs(
    qry: ListQuery = Depends(list_query_params),
    module: str = Query("", description="模块名"),
    user_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    extra = {"module": module.strip() or None, "user_id": user_id}
    return _query_logs(
        SysLogOperation,
        db,
        qry,
        keyword_cols=[SysLogOperation.url, SysLogOperation.module, SysLogOperation.trace_id, SysLogOperation.operate_no],
        sort_map={"log_id": SysLogOperation.log_id, "created_at": SysLogOperation.created_at},
        date_col=SysLogOperation.created_at,
        name_col=SysLogOperation.module,
        extra_filters=extra,
    )


@router.get("/error", response_model=LogPage)
def list_error_logs(
    qry: ListQuery = Depends(list_query_params),
    module: str = Query("", description="模块名"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    extra = {"module": module.strip() or None}
    return _query_logs(
        SysLogError,
        db,
        qry,
        keyword_cols=[SysLogError.url, SysLogError.module, SysLogError.trace_id, SysLogError.error_message],
        sort_map={"log_id": SysLogError.log_id, "created_at": SysLogError.created_at},
        date_col=SysLogError.created_at,
        name_col=SysLogError.module,
        extra_filters=extra,
    )


@router.get("/api-call", response_model=LogPage)
def list_api_call_logs(
    qry: ListQuery = Depends(list_query_params),
    api_type: str = Query("", description="API 类型"),
    success: int | None = Query(None, ge=0, le=1),
    user_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    extra = {"api_type": api_type.strip() or None, "success": success, "user_id": user_id}
    return _query_logs(
        SysLogApiCall,
        db,
        qry,
        keyword_cols=[SysLogApiCall.target_url, SysLogApiCall.api_type, SysLogApiCall.trace_id, SysLogApiCall.error_message],
        sort_map={"log_id": SysLogApiCall.log_id, "created_at": SysLogApiCall.created_at},
        date_col=SysLogApiCall.created_at,
        name_col=SysLogApiCall.api_type,
        extra_filters=extra,
    )


@router.get("/schedule", response_model=LogPage)
def list_schedule_logs(
    qry: ListQuery = Depends(list_query_params),
    job_name: str = Query("", description="任务名"),
    execute_state: int | None = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    extra = {"job_name": job_name.strip() or None, "execute_state": execute_state}
    return _query_logs(
        SysLogSchedule,
        db,
        qry,
        keyword_cols=[SysLogSchedule.job_name, SysLogSchedule.job_group, SysLogSchedule.job_desc, SysLogSchedule.error_msg],
        sort_map={"log_id": SysLogSchedule.log_id, "created_at": SysLogSchedule.created_at, "start_time": SysLogSchedule.start_time},
        date_col=SysLogSchedule.created_at,
        name_col=SysLogSchedule.job_name,
        extra_filters=extra,
    )
