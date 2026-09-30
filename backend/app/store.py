"""数据仓库：默认落一份 JSON 文件，保证重启后业务数据还在。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
- 首次启动（或数据文件损坏）时用 SEED_ROWS 播种并落盘；
- 写操作走 commit()，先写临时文件再 os.replace 原子替换，避免写一半损坏；
- 数据文件不可写时自动降级为纯内存模式并记录在 self.readonly，业务不中断。
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from app.seed import SEED_ROWS

# 允许用环境变量指定数据文件位置，方便测试隔离 / 容器挂卷。
DATA_PATH = os.environ.get(
    "APP_DATA_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.json"),
)
DATA_VERSION = 1


class Store:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or DATA_PATH
        self.readonly = False
        self._tables = self._load()

    # ---- 持久化 -----------------------------------------------------------
    def _seed_tables(self) -> dict[str, list[dict[str, Any]]]:
        return {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                tables = payload.get("tables")
                if payload.get("version") == DATA_VERSION and isinstance(tables, dict):
                    return tables
            except (json.JSONDecodeError, OSError):
                pass  # 文件损坏或不可读：回退到种子数据，避免服务起不来
        tables = self._seed_tables()
        self.commit(tables)
        return tables

    def commit(self, tables: dict[str, list[dict[str, Any]]] | None = None) -> bool:
        """把当前内存数据落盘；返回是否真的写成功（只读模式返回 False）。"""
        if tables is not None:
            self._tables = tables
        if self.readonly:
            return False
        try:
            directory = os.path.dirname(self.path) or "."
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".data-", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({"version": DATA_VERSION, "tables": self._tables}, fh, ensure_ascii=False)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return True
        except OSError:
            # 落盘失败不阻断当前请求，只标记为只读；内存里的变更对本进程仍然有效。
            self.readonly = True
            return False

    # ---- 查询 -------------------------------------------------------------
    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
