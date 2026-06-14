"""统一列表查询：分页、排序、日期/ID/名称/关键词筛选。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Callable

from fastapi import Query
from sqlalchemy import asc, desc, or_
from sqlalchemy.orm import Query as SaQuery
from sqlalchemy.sql.elements import ColumnElement


@dataclass
class ListQuery:
    page: int = 1
    size: int = 20
    sort_by: str = ""
    sort_order: str = "desc"
    keyword: str = ""
    date_from: datetime | None = None
    date_to: datetime | None = None
    id: int | None = None
    name: str = ""


def parse_datetime(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value or not str(value).strip():
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        if len(raw) == 10 and raw[4] == "-":
            d = date.fromisoformat(raw)
            return datetime.combine(d, time.max if end_of_day else time.min)
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def list_query_params(
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
    sort_by: str = Query("", description="排序字段"),
    sort_order: str = Query("desc", description="asc|desc"),
    keyword: str = Query("", description="关键词模糊查询"),
    date_from: str | None = Query(None, description="开始日期/时间"),
    date_to: str | None = Query(None, description="结束日期/时间"),
    id: int | None = Query(None, description="精确 ID"),
    name: str = Query("", description="名称模糊查询"),
) -> ListQuery:
    order = (sort_order or "desc").lower()
    if order not in ("asc", "desc"):
        order = "desc"
    return ListQuery(
        page=page,
        size=size,
        sort_by=(sort_by or "").strip(),
        sort_order=order,
        keyword=(keyword or "").strip(),
        date_from=parse_datetime(date_from, end_of_day=False),
        date_to=parse_datetime(date_to, end_of_day=True),
        id=id,
        name=(name or "").strip(),
    )


def apply_sort(q: SaQuery, model: Any, qry: ListQuery, allowed: dict[str, ColumnElement], default_col: ColumnElement) -> SaQuery:
    col = allowed.get(qry.sort_by) if qry.sort_by else None
    if col is None:
        col = default_col
    fn = asc if qry.sort_order == "asc" else desc
    return q.order_by(fn(col))


def apply_date_range(q: SaQuery, col: ColumnElement, qry: ListQuery) -> SaQuery:
    if qry.date_from:
        q = q.filter(col >= qry.date_from)
    if qry.date_to:
        q = q.filter(col <= qry.date_to)
    return q


def apply_id_filter(q: SaQuery, col: ColumnElement, qry: ListQuery) -> SaQuery:
    if qry.id is not None:
        q = q.filter(col == qry.id)
    return q


def apply_like(q: SaQuery, col: ColumnElement, text: str) -> SaQuery:
    t = (text or "").strip()
    if not t:
        return q
    return q.filter(col.ilike(f"%{t}%"))


def apply_keyword(q: SaQuery, qry: ListQuery, cols: list[ColumnElement]) -> SaQuery:
    t = (qry.keyword or "").strip()
    if not t or not cols:
        return q
    pattern = f"%{t}%"
    return q.filter(or_(*[c.ilike(pattern) for c in cols]))


def paginate(q: SaQuery, qry: ListQuery) -> tuple[list, int]:
    total = q.count()
    page = max(1, qry.page)
    size = min(max(1, qry.size), 100)
    rows = q.offset((page - 1) * size).limit(size).all()
    return rows, total


def page_result(items: list, total: int, qry: ListQuery) -> dict:
    return {
        "total": total,
        "page": max(1, qry.page),
        "size": min(max(1, qry.size), 100),
        "items": items,
    }
