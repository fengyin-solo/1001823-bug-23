"""管网档案业务规则：登记、提交归档、确认归档、作废的完整状态机。

状态序列：待归档 -> 待补充(资料不全时的中间态) -> 待确认 -> 已归档
另设终态：已作废

设计要点（对应用户反馈）：
- 提交归档只是「提交」，确认归档才是真正归档完成；两步不再颠倒。
- 资料名称、存放位置随提交动作一并落库，重开页面、重启服务都还在。
- 同一档案编号重复登记/归档只保留一条记录：后到的一份覆盖既有字段，不堆积新行；
  已经处于待确认/已归档的记录再次操作走幂等分支，不重复写归档记录。
- 每次流转都把当时的字段快照存进 history；关联管段（归属）变更只影响之后的快照，
  历史快照按值保存，永远停留在它原来归属的那一段。
- 每一步失败都给出原因，状态停在失败时的那一步，补齐后可原地继续。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "archive"
BUSINESS_KEY = "档案编号"
REQUIRED_FIELDS = ["档案编号", "关联管段", "档案类别"]
# 登记之后、提交归档时必须补齐的归档要素
SUBMIT_REQUIRED_FIELDS = ["资料名称", "存放位置"]
# 后到的一份允许覆盖的字段
EDITABLE_FIELDS = ["关联管段", "档案类别", "资料名称", "存放位置", "归档人员"]
SNAPSHOT_FIELDS = ["档案编号", "关联管段", "档案类别", "资料名称", "存放位置", "归档人员", "归档日期"]

STATUS_PENDING = "待归档"
STATUS_NEED_MORE = "待补充"
STATUS_SUBMITTED = "待确认"
STATUS_ARCHIVED = "已归档"
STATUS_VOID = "已作废"
STATUS_ORDER = [STATUS_PENDING, STATUS_NEED_MORE, STATUS_SUBMITTED, STATUS_ARCHIVED, STATUS_VOID]

SUBMIT_FROM = {STATUS_PENDING, STATUS_NEED_MORE}
CONFIRM_FROM = {STATUS_SUBMITTED}
VOID_FROM = {STATUS_PENDING, STATUS_NEED_MORE, STATUS_SUBMITTED}


def _today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _snapshot(entry: dict[str, Any]) -> dict[str, Any]:
    snap = {field: entry.get(field) for field in SNAPSHOT_FIELDS}
    snap["档案状态"] = entry.get("status")
    return snap


def _record(entry: dict[str, Any], action: str, changes: dict[str, list[Any]] | None = None) -> None:
    """追加一条历史。快照按值拷贝，日后归属变更不会改写这条历史。"""
    entry.setdefault("history", []).append({
        "at": _now(),
        "action": action,
        "status": entry.get("status"),
        "changes": changes or {},
        "snapshot": _snapshot(entry),
    })


def _apply_updates(entry: dict[str, Any], values: dict[str, Any]) -> dict[str, list[Any]]:
    """把提交的非空字段写进记录，返回 {字段: [旧值, 新值]} 的变更明细。"""
    changes: dict[str, list[Any]] = {}
    for field in EDITABLE_FIELDS:
        if field not in values:
            continue
        new_value = str(values.get(field) or "").strip()
        if not new_value:
            continue
        old_value = entry.get(field)
        if old_value != new_value:
            changes[field] = [old_value, new_value]
            entry[field] = new_value
    return changes


class ArchiveService:
    # ---------- 查询 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            key = keyword.strip()
            rows = [
                row for row in rows
                if key in str(row.get("档案编号", ""))
                or key in str(row.get("资料名称", ""))
                or key in str(row.get("关联管段", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(self) -> dict[str, int]:
        """概览数字与列表同源：都直接按 status 统计全量记录。"""
        rows = store.rows(MODULE)
        month_prefix = _today()[:7]
        return {
            "待归档记录": sum(1 for row in rows if row.get("status") not in {STATUS_ARCHIVED, STATUS_VOID}),
            "本月归档数": sum(
                1 for row in rows
                if row.get("status") == STATUS_ARCHIVED
                and str(row.get("归档日期") or "").startswith(month_prefix)
            ),
            "待补充档案": sum(1 for row in rows if row.get("status") == STATUS_NEED_MORE),
            "已归档记录": sum(1 for row in rows if row.get("status") == STATUS_ARCHIVED),
            "已作废记录": sum(1 for row in rows if row.get("status") == STATUS_VOID),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---------- 登记（后到覆盖，不堆积） ----------

    def create_entry(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], bool]:
        """登记或按档案编号覆盖。返回 (记录, 缺失字段, 是否覆盖了既有记录)。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False

        key_value = str(values[BUSINESS_KEY]).strip()
        existing = store.find_by_key(MODULE, BUSINESS_KEY, key_value)
        if existing is not None:
            # 同编号资料后到：覆盖可改字段，保留 id 与全部历史，只留一条记录
            changes = _apply_updates(existing, values)
            if existing.get("status") == STATUS_ARCHIVED:
                # 已归档资料又来了一份：新版本要重新确认，但旧归档历史仍在
                existing["status"] = STATUS_SUBMITTED
            elif existing.get("status") == STATUS_VOID:
                existing["status"] = STATUS_PENDING
            _record(existing, "资料更新（按档案编号覆盖）", changes)
            store.normalize(MODULE, existing)
            return existing, [], True

        entry: dict[str, Any] = {"id": store.next_id(MODULE)}
        for field in REQUIRED_FIELDS:
            entry[field] = str(values[field]).strip()
        for field in EDITABLE_FIELDS:
            value = str(values.get(field) or "").strip()
            if value:
                entry[field] = value
        entry["status"] = STATUS_PENDING
        entry["history"] = []
        store.rows(MODULE).append(entry)
        _record(entry, "登记档案")
        store.normalize(MODULE, entry)
        return entry, [], False

    # ---------- 状态流转 ----------

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"档案记录 {entry_id} 不存在，无法执行「{action}」"
        values = values or {}

        if action == "提交归档":
            return self._submit(entry, values)
        if action == "确认归档":
            return self._confirm(entry, values)
        if action == "作废档案":
            return self._void(entry, values)
        return None, f"动作「{action}」不属于管网档案可执行范围"

    def _submit(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        status = entry.get("status")
        if status == STATUS_ARCHIVED:
            # 幂等拦截：已归档资料重复提交，不产生第二条归档记录
            return entry, "资料已归档完成，无需重复提交归档"
        if status == STATUS_VOID:
            return None, "档案已作废，不能再提交归档；如需重新启用请重新登记该档案编号"
        if status == STATUS_SUBMITTED:
            # 待确认队列里重复点提交：刷新资料内容但仍只有一条待确认记录
            changes = _apply_updates(entry, values)
            if changes:
                _record(entry, "提交归档（更新待确认资料）", changes)
                store.normalize(MODULE, entry)
            return entry, "资料已提交，正在等待确认归档，请勿重复提交"

        # 待归档 / 待补充：先把这一步带来的字段全部落库
        changes = _apply_updates(entry, values)
        missing = [
            field for field in SUBMIT_REQUIRED_FIELDS
            if not str(entry.get(field) or "").strip()
        ]
        if missing:
            # 失败停在这一步：已填的内容保留，状态置为待补充，补齐后重新提交即可
            entry["status"] = STATUS_NEED_MORE
            _record(entry, "提交归档（资料不全，待补充）", changes)
            store.normalize(MODULE, entry)
            return None, (
                f"提交归档失败：{'、'.join(missing)}为归档必填项，"
                "请补充后重新提交，已填写的内容已保留"
            )

        entry["status"] = STATUS_SUBMITTED
        _record(entry, "提交归档", changes)
        store.normalize(MODULE, entry)
        return entry, "资料已提交归档，等待档案管理员确认"

    def _confirm(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        status = entry.get("status")
        if status == STATUS_ARCHIVED:
            # 重复确认同一份资料：幂等成功，只留一条归档记录
            return entry, "资料已归档确认，无需重复操作"
        if status == STATUS_VOID:
            return None, "档案已作废，不能执行确认归档"
        if status != STATUS_SUBMITTED:
            return None, f"资料当前为「{status}」状态，需先提交归档才能确认"

        operator = str(values.get("归档人员") or "").strip()
        if operator and not str(entry.get("归档人员") or "").strip():
            entry["归档人员"] = operator
        if not str(entry.get("归档日期") or "").strip():
            entry["归档日期"] = _today()
        entry["status"] = STATUS_ARCHIVED
        _record(entry, "确认归档")
        store.normalize(MODULE, entry)
        return entry, "归档确认成功，资料已正式入库"

    def _void(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        status = entry.get("status")
        if status == STATUS_VOID:
            return entry, "档案已是作废状态"
        if status == STATUS_ARCHIVED:
            return None, "资料已正式归档，不能直接作废；如需作废请先走档案撤销流程"
        entry["status"] = STATUS_VOID
        _record(entry, "作废档案")
        store.normalize(MODULE, entry)
        return entry, "档案已作废"
