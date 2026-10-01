"""各业务模块的状态口径：列表展示字段、待处理/异常判定都以这里为准。

之前概览看板读的是行内的 ``pending`` / ``abnormal`` 标志，而这两个标志在种子数据里
和 ``status`` 对不上（已归档的行也可能 pending=True），导致概览条数和列表条数不一致。
统一改成由状态推导，标志只作冗余存储，不再作为统计依据。
"""
from __future__ import annotations

# 每个模块：状态字段列名（列表里展示状态的那一列）、各状态顺序、终态、异常态
STATUS_RULES: dict[str, dict[str, object]] = {
    "pipe": {
        "status_field": "管段状态",
        "order": ["待移交", "正常运行", "重点观测", "封闭施工"],
        "terminal": ["封闭施工"],
        "abnormal": ["重点观测"],
    },
    "manhole": {
        "status_field": "检查井状态",
        "order": ["待清掏", "正常使用", "井盖缺失"],
        "terminal": ["井盖缺失"],
        "abnormal": ["井盖缺失"],
    },
    "valve": {
        "status_field": "阀门状态",
        "order": ["待启闭", "操作正常", "启闭卡涩"],
        "terminal": ["启闭卡涩"],
        "abnormal": ["启闭卡涩"],
    },
    "pumpstation": {
        "status_field": "泵站状态",
        "order": ["待接管", "运行正常", "减量运行"],
        "terminal": ["减量运行"],
        "abnormal": ["减量运行"],
    },
    "patrol": {
        "status_field": "巡查状态",
        "order": ["待派发", "巡查中", "已提交"],
        "terminal": ["已提交"],
        "abnormal": [],
    },
    "defect": {
        "status_field": "缺陷状态",
        "order": ["待定级", "已定级", "处置中"],
        "terminal": ["处置中"],
        "abnormal": [],
    },
    "cctv": {
        "status_field": "检测状态",
        "order": ["待检测", "检测中", "已出具"],
        "terminal": ["已出具"],
        "abnormal": [],
    },
    "repair": {
        "status_field": "修复状态",
        "order": ["待开工", "施工中", "待验收"],
        "terminal": ["待验收"],
        "abnormal": [],
    },
    "pressure": {
        "status_field": "监测状态",
        "order": ["待采集", "采集正常", "压力越限"],
        "terminal": ["压力越限"],
        "abnormal": ["压力越限"],
    },
    "flow": {
        "status_field": "监测状态",
        "order": ["待采集", "采集正常", "流量异常"],
        "terminal": ["流量异常"],
        "abnormal": ["流量异常"],
    },
    "leak": {
        "status_field": "排查状态",
        "order": ["待排查", "排查中", "已处置"],
        "terminal": ["已处置"],
        "abnormal": [],
    },
    "dredge": {
        "status_field": "清淤状态",
        "order": ["待安排", "清淤中", "已完成"],
        "terminal": ["已完成"],
        "abnormal": [],
    },
    "material": {
        "status_field": "材料状态",
        "order": ["正常可用", "临近不足", "已冻结"],
        "terminal": ["已冻结"],
        "abnormal": ["临近不足"],
    },
    "equip": {
        "status_field": "机械状态",
        "order": ["待保养", "可用", "保养中"],
        "terminal": ["保养中"],
        "abnormal": [],
    },
    "traffic": {
        "status_field": "许可状态",
        "order": ["待审批", "已批准", "施工中"],
        "terminal": ["施工中"],
        "abnormal": [],
    },
    "complaint": {
        "status_field": "诉求状态",
        "order": ["待受理", "办理中", "已回复"],
        "terminal": ["已回复"],
        "abnormal": [],
    },
    "fund": {
        "status_field": "资金状态",
        "order": ["待审批", "已批复", "执行中"],
        "terminal": ["执行中"],
        "abnormal": [],
    },
    "archive": {
        "status_field": "档案状态",
        "order": ["待归档", "待补充", "待确认", "已归档", "已作废"],
        "terminal": ["已归档", "已作废"],
        "abnormal": ["已作废"],
    },
}

# 档案状态：提交归档后需要档案管理员二次确认才算归档完成
ARCHIVE_STATUS = ["待归档", "待补充", "待确认", "已归档", "已作废"]
ARCHIVE_TERMINAL = ["已归档", "已作废"]
ARCHIVE_ABNORMAL = ["已作废"]


def is_pending(module: str, status: str | None) -> bool:
    """不在终态里的记录都算待处理；未知模块退化为“非空状态即待处理”。"""
    rules = STATUS_RULES.get(module)
    if rules is None:
        return bool(status)
    return status not in set(rules["terminal"])  # type: ignore[arg-type]


def is_abnormal(module: str, status: str | None) -> bool:
    rules = STATUS_RULES.get(module)
    if rules is None:
        return False
    return status in set(rules["abnormal"])  # type: ignore[arg-type]


def status_field(module: str) -> str | None:
    rules = STATUS_RULES.get(module)
    return rules["status_field"] if rules else None  # type: ignore[return-value]
