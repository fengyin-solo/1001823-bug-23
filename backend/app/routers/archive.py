"""管网档案接口：登记/覆盖登记、提交归档、确认归档、作废与明细历史。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.archive import ArchiveService

router = APIRouter(prefix="/api/archive", tags=["管网档案"])

service = ArchiveService()

LIST_FIELDS = ["档案编号", "关联管段", "档案类别", "资料名称", "存放位置", "归档人员", "归档日期", "档案状态"]
STATUSES = ["待归档", "待补充", "待确认", "已归档", "已作废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按档案编号/资料名称/关联管段检索"),
    status: str | None = Query(default=None, description="待归档、待补充、待确认、已归档、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """档案列表与统计一次返回；统计与列表同源，刷新后概览数字与列表条数一致。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"不支持的档案状态：{status}")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(
        items=items,
        total=total,
        page=page,
        size=size,
        stats=service.stats(),
    )


@router.get("/stats")
def archive_stats() -> dict[str, int]:
    """单独取统计：从概览页回到列表时可直接刷新数字。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出管网档案清单：返回全量数据。需声明在 /{entry_id} 之前，否则 export 会被当成 id。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "archive", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
    """读取单条档案明细及其全部流转历史；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"档案记录 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记档案；同一档案编号后到的一份覆盖既有记录而不是新增堆积。"""
    entry, missing, overwritten = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if overwritten:
        return ActionResult(ok=True, message="检测到相同档案编号，已用后到资料覆盖既有记录", entry=entry)
    return ActionResult(ok=True, message="档案记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """执行提交归档、确认归档、作废档案。

    提交归档可携带资料名称、存放位置等字段一并落库；
    业务规则不通过（资料不全、状态不允许、重复归档等）时 ok=False，
    message 说明失败原因，数据停在失败时的那一步，可原地继续。
    """
    action = str(payload.values.get("action") or "").strip()
    values = {key: value for key, value in payload.values.items() if key != "action"}
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
