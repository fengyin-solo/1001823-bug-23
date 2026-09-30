"""管网档案接口：维护档案记录，覆盖提交归档、确认归档、作废档案与归属变更。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.archive import ArchiveService

router = APIRouter(prefix="/api/archive", tags=["管网档案"])

service = ArchiveService()

LIST_FIELDS = ["档案编号", "关联管段", "档案类别", "资料名称", "存放位置", "归档人员", "归档日期", "档案状态"]
STATUSES = ["待归档", "已归档", "待补充", "已作废"]


class ActionPayload(BaseModel):
    """动作请求：兼容 {values:{action}} 与页面直接提交 {action} 两种写法。"""

    action: str | None = None
    values: dict[str, Any] = {}
    remark: str | None = None


def _resolve_payload(body: ActionPayload) -> tuple[str, dict[str, Any]]:
    values = dict(body.values or {})
    action = str(body.action or values.get("action") or "").strip()
    return action, values


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按档案编号检索"),
    status: str | None = Query(default=None, description="待归档、已归档、待补充、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按档案编号与状态过滤管网档案列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def archive_stats() -> dict[str, int]:
    """档案页统计卡：与列表同源同口径，刷新后概览与列表条数一致。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出管网档案清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "archive", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条档案记录明细（含归档历史）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"档案记录 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条档案记录，缺字段时说明原因；同档案编号后到覆盖、不重复堆积。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="档案记录已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """变更档案归属或资料字段并落库；历史归档记录保留在变更前的归属下。"""
    entry, message = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, body: ActionPayload) -> ActionResult:
    """对单条档案执行提交归档 / 确认归档 / 作废档案。

    失败时返回 ok=False 与具体原因（HTTP 仍是 200，业务结果以 ok 为准），
    并保留已暂存内容，前端可从失败的那一步接着走。
    """
    action, values = _resolve_payload(body)
    entry, message, ok = service.run_action(entry_id, action, values)
    return ActionResult(ok=ok, message=message, entry=entry)
