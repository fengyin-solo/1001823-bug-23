"""数据仓库：带文件持久化的内存表。

- 首次启动从 ``SEED_ROWS`` 播种并落盘；之后每次启动优先读取数据文件，
  这样「页面确认 -> 重启进程 -> 再进系统」看到的是同一份数据，而不是回到种子数据。
- 写盘采用临时文件 + 原子替换，避免写一半时读到半截 JSON。
- ``pending`` / ``abnormal`` 以及各模块列表里的状态列统一由 ``status`` 推导，
  种子数据里标志位与状态不一致的问题在这里被纠偏，保证概览与列表口径一致。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.seed import SEED_ROWS
from app.status_rules import is_abnormal, is_pending, status_field

_DATA_DIR = Path(os.environ.get("PIPELINE_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
_DATA_FILE = _DATA_DIR / "store.json"


class Store:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tables: dict[str, list[dict[str, Any]]] = {}
        self._load()

    # ---------- 持久化 ----------

    def _load(self) -> None:
        if _DATA_FILE.exists():
            try:
                with _DATA_FILE.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    self._tables = {
                        name: [dict(row) for row in rows]
                        for name, rows in data.items()
                        if isinstance(rows, list)
                    }
            except (json.JSONDecodeError, OSError):
                # 数据文件损坏时退回种子数据，不让服务起不来
                self._tables = self._seed_tables()
        else:
            self._tables = self._seed_tables()
        for module in self._tables:
            self._normalize_module(module, persist=False)
        self._save_locked()

    @staticmethod
    def _seed_tables() -> dict[str, list[dict[str, Any]]]:
        return {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}

    def save(self) -> None:
        """把当前数据落盘；写盘失败抛异常由调用方决定如何提示。"""
        with self._lock:
            self._save_locked()

    def _save_locked(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _DATA_FILE.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self._tables, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, _DATA_FILE)

    # ---------- 口径统一 ----------

    def _normalize_row(self, module: str, row: dict[str, Any]) -> None:
        rules_field = status_field(module)
        status = row.get("status")
        if rules_field is not None:
            # 列表的状态列直接呈现真实状态，不再保留种子里的占位写法
            row[rules_field] = status
        row["pending"] = is_pending(module, status)
        row["abnormal"] = is_abnormal(module, status)

    def _normalize_module(self, module: str, persist: bool = True) -> None:
        for row in self._tables.get(module, []):
            self._normalize_row(module, row)
        if persist:
            self.save()

    def normalize(self, module: str, row: dict[str, Any]) -> dict[str, Any]:
        """业务层改完 status 后调用：同步状态列与统计标志并落盘。"""
        with self._lock:
            self._normalize_row(module, row)
            self._save_locked()
        return row

    # ---------- 表访问 ----------

    def module_names(self) -> list[str]:
        with self._lock:
            return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            for row in self.rows(module):
                if int(row.get("id", 0)) == entry_id:
                    return row
        return None

    def find_by_key(self, module: str, key_field: str, key_value: str) -> dict[str, Any] | None:
        """按业务编号（如档案编号）查找，用于重复归档时定位既有记录。"""
        with self._lock:
            for row in self.rows(module):
                if str(row.get(key_field) or "").strip() == key_value:
                    return row
        return None

    def next_id(self, module: str) -> int:
        with self._lock:
            return max((int(row.get("id", 0)) for row in self.rows(module)), default=0) + 1

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        with self._lock:
            for name in self.module_names():
                rows = self.rows(name)
                modules.append({
                    "name": name,
                    "created": len(rows),
                    "pending": sum(1 for row in rows if is_pending(name, row.get("status"))),
                    "abnormal": sum(1 for row in rows if is_abnormal(name, row.get("status"))),
                })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
