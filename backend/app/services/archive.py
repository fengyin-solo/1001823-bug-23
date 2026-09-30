"""管网档案业务规则：状态流转、字段校验、幂等归档与历史留痕都收在这里。

归档是两步流程：
  提交归档：把资料名称、存放位置等落库；资料不全则暂存已填内容并置为「待补充」；
  确认归档：资料齐全才置为「已归档」，并追加一条只增不改的归档历史（含归属快照）。
所有变更都会 commit 落盘，保证页面重开、服务重启后看到的是同一份数据。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "archive"
REQUIRED_FIELDS = ["档案编号", "关联管段", "档案类别"]
# 提交归档时必须齐备的资料字段；不齐会停在「待补充」，而不是静默通过。
MATERIAL_FIELDS = ["资料名称", "存放位置"]
# 允许在登记 / 详情里维护并落库的业务字段。
EDITABLE_FIELDS = [
    "关联管段", "档案类别", "资料名称", "存放位置", "归档人员", "归档日期",
]
STATUS_PENDING = "待归档"
STATUS_ARCHIVED = "已归档"
STATUS_NEED_MORE = "待补充"
STATUS_VOID = "已作废"
STATUS_ORDER = [STATUS_PENDING, STATUS_ARCHIVED, STATUS_NEED_MORE, STATUS_VOID]
# 终态：不再计入待处理。
TERMINAL_STATUSES = {STATUS_ARCHIVED, STATUS_VOID}
ACTION_RULES = {"提交归档": STATUS_PENDING, "确认归档": STATUS_ARCHIVED, "作废档案": STATUS_VOID}


def _sync_flags(entry: dict[str, Any]) -> None:
    """让 pending / abnormal / 档案状态始终跟 status 对齐，概览和列表口径才不会打架。"""
    status = entry.get("status", STATUS_PENDING)
    entry["pending"] = status not in TERMINAL_STATUSES
    entry["abnormal"] = status == STATUS_VOID
    entry["档案状态"] = status


def _missing_material(entry: dict[str, Any]) -> list[str]:
    return [field for field in MATERIAL_FIELDS if not str(entry.get(field) or "").strip()]


class ArchiveService:
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
            rows = [row for row in rows if keyword in str(row.get("档案编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(self) -> dict[str, int]:
        """档案页三张统计卡：与列表过滤共用同一份数据、同一套口径。"""
        rows = store.rows(MODULE)
        month_prefix = date.today().strftime("%Y-%m")
        return {
            "待归档记录": sum(1 for row in rows if row.get("status") == STATUS_PENDING),
            "本月归档数": sum(
                1
                for row in rows
                if row.get("status") == STATUS_ARCHIVED
                and str(row.get("归档日期", "")).startswith(month_prefix)
            ),
            "待补充档案": sum(1 for row in rows if row.get("status") == STATUS_NEED_MORE),
            "已归档记录": sum(1 for row in rows if row.get("status") == STATUS_ARCHIVED),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)

        # 同档案编号视为同一份资料：后到的一份覆盖，而不是堆出新记录。
        existing = next(
            (row for row in rows if str(row.get("档案编号", "")).strip() == str(values["档案编号"]).strip()),
            None,
        )
        if existing is not None:
            self._apply_values(existing, values)
            store.commit()
            return existing, []

        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS:
            entry[field] = values.get(field)
        self._apply_values(entry, values)
        entry["status"] = STATUS_PENDING
        entry["submitted"] = False
        entry["history"] = []
        _sync_flags(entry)
        rows.append(entry)
        store.commit()
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """变更档案归属（关联管段）或资料字段；只改当前记录，历史快照保持原样。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"档案记录 {entry_id} 不存在"
        if entry.get("status") == STATUS_VOID:
            return None, "已作废档案不能再变更归属或资料"
        self._apply_values(entry, values)
        store.commit()
        return entry, "档案变更已保存，历史归档记录仍保留在原归属下"

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """执行动作并落盘。

        返回 (记录, 说明, 是否成功)：失败时记录也可能被返回（已暂存已填内容），
        前端据此停在失败的那一步，用户补齐后可直接续走。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"档案记录 {entry_id} 不存在", False
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于管网档案可执行范围", False

        status = entry.get("status", STATUS_PENDING)

        if action == "提交归档":
            if status == STATUS_ARCHIVED:
                return entry, "该资料已归档，不能重复提交；如需更新请在详情中做档案变更", False
            if status == STATUS_VOID:
                return entry, "档案已作废，不能再提交归档", False
            self._apply_values(entry, values or {})
            missing = _missing_material(entry)
            if missing:
                entry["submitted"] = False
                entry["status"] = STATUS_NEED_MORE
                _sync_flags(entry)
                store.commit()
                return (
                    entry,
                    f"归档停在「提交归档」：缺少资料字段 {'、'.join(missing)}，"
                    "已暂存本次填写内容，补齐后重新提交即可从这一步继续",
                    False,
                )
            entry["submitted"] = True
            entry["status"] = STATUS_PENDING
            _sync_flags(entry)
            store.commit()
            return entry, "资料已提交归档，等待确认归档", True

        if action == "确认归档":
            # 幂等：重复确认同一份资料只保留一条归档记录。
            if status == STATUS_ARCHIVED:
                return entry, "该资料已归档，重复确认不会产生新记录", True
            if status == STATUS_VOID:
                return entry, "档案已作废，不能确认归档", False
            self._apply_values(entry, values or {})
            if not entry.get("submitted"):
                store.commit()
                return (
                    entry,
                    "归档停在「确认归档」：该资料还没有成功执行「提交归档」，"
                    "请先在详情中补全资料名称与存放位置并提交，再回到确认归档",
                    False,
                )
            missing = _missing_material(entry)
            if missing or status == STATUS_NEED_MORE:
                entry["submitted"] = False
                entry["status"] = STATUS_NEED_MORE
                _sync_flags(entry)
                store.commit()
                return (
                    entry,
                    f"归档停在「确认归档」：缺少资料字段 {'、'.join(missing) or '资料尚未补充完整'}，"
                    "请补充资料名称与存放位置后先提交归档，再回到确认归档",
                    False,
                )
            entry["status"] = STATUS_ARCHIVED
            if not str(entry.get("归档日期") or "").strip():
                entry["归档日期"] = date.today().isoformat()
            _sync_flags(entry)
            self._append_history(entry, action="确认归档")
            store.commit()
            return entry, "档案已确认归档", True

        if action == "作废档案":
            if status == STATUS_VOID:
                return entry, "该档案已是作废状态，无需重复作废", True
            if status == STATUS_ARCHIVED:
                return entry, "已归档档案不允许直接作废，请走档案废止审批", False
            entry["status"] = STATUS_VOID
            _sync_flags(entry)
            store.commit()
            return entry, "档案已作废", True

        return None, f"目标状态「{ACTION_RULES[action]}」不在允许的状态序列里", False

    # ---- 内部工具 ---------------------------------------------------------
    @staticmethod
    def _apply_values(entry: dict[str, Any], values: dict[str, Any]) -> None:
        """只落业务允许的字段，action 之类的控制参数不写进数据。"""
        for field in EDITABLE_FIELDS:
            if field in values and values[field] is not None:
                entry[field] = str(values[field]).strip()

    @staticmethod
    def _append_history(entry: dict[str, Any], *, action: str) -> None:
        history = entry.setdefault("history", [])
        # 双保险：任何情况下同一档案只留一条归档记录。
        if any(item.get("action") == "确认归档" for item in history):
            return
        history.append({
            "seq": len(history) + 1,
            "action": action,
            "confirmedAt": date.today().isoformat(),
            # 归属快照：日后关联管段变更，历史仍归原处。
            "关联管段": entry.get("关联管段", ""),
            "档案类别": entry.get("档案类别", ""),
            "资料名称": entry.get("资料名称", ""),
            "存放位置": entry.get("存放位置", ""),
            "归档人员": entry.get("归档人员", ""),
            "归档日期": entry.get("归档日期", ""),
        })
