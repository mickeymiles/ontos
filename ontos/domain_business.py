# -*- coding: utf-8 -*-
"""通用业务本体地基（ontos · 合同 / 商机 / 项目 / 人员）。

这是「基于本体的智能体平台」的通用业务域骨架，覆盖四条核心业务实体及其
关系、Function、Action。备件采购等独立域见 domain_procurement.py（后处理）。

设计原则（与 v1.2 总纲一致）：
- TBox：领域概念 / 关系，机器可读、可喂 LLM；
- Function / Action：动力层。Function=判定/计算/约束（只读），Action=变更（写回，受约束）；
- 声明与实现分离：声明写在此模块（单一真相），实现经注册表 impl 绑定到已有
  etl / project_metrics 等适配器（P1 收敛，不重写现有逻辑）；
- 纯函数、零 DB / 零 app 运行时耦合：ABox 构造与不变量校验均为纯函数，便于单测与影子比对。

本次 pilot = F-project-cost-warning（项目成本预警）：语义规则 cost_warning_rule 与
9006 backend/core/project_metrics._cost_status 逐字等价，已通过影子比对（见 tests/）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .registry import Definition, functions, actions


# ═══════════════════════════════════════════════════════════════════════
# TBox：领域概念（供 LLM 语境 / 校验 / 文档引用）
# ═══════════════════════════════════════════════════════════════════════
CONCEPTS = {
    # 四个核心实体
    "Project": "项目（经营主数据根实体，project_no 为主键；可挂子项目 parent_project_id）",
    "Opportunity": "商机（销售线索，中标后生成项目；estimate_budget 为预计金额）",
    "Contract": "合同（法律实体：签约金额 sign_amount / 签约日期 sign_date / 甲方 party_a / 乙方 party_b）",
    "Personnel": "人员（员工；角色含 项目经理 / 销售负责人 / 交付工程师 等）",
    # 派生/子概念（可选）
    "Budget": "预算基线（来自 四算 之预算 stage，total_cost）",
    "Estimate": "概算基线（来自 四算 之概算 stage，total_cost）",
    "CostWarning": "成本预警记录（项目预算执行比超阈值时产生，可写回事实栏）",
}

# 关系（Link）：主语.谓词(宾语)
RELATIONS = {
    "opportunity.realizes(project)": "商机中标后生成项目（默认 1:1，预留 1:N 子项目）",
    "project.hasContract(contract)": "项目下挂合同（默认 1:1，支持 1:N）",
    "contract.belongsTo(project)": "合同归属项目（反向关系）",
    "project.managedBy(personnel)": "项目由某人员担任项目经理",
    "opportunity.ownedBy(personnel)": "商机由某销售负责人跟进",
    "personnel.assignedTo(project)": "人员参与项目（交付工程师 / 现场等）",
    "contract.signedWith(partyA, partyB)": "合同签约方（甲方 / 乙方）",
    "project.raisedWarning(costWarning)": "项目触发成本预警（写回 CostWarning 事实）",
}


# ═══════════════════════════════════════════════════════════════════════
# Function：动力层·计算/判定（只读，不改事实）
# ═══════════════════════════════════════════════════════════════════════
COST_WARNING_RATIO = 0.9  # 预算完成比阈值：≥90% 触发预警（对齐 9006 COST_WARNING_RATIO）


def cost_warning_rule(budget: Optional[float], current_cost: Optional[float],
                      threshold: float = COST_WARNING_RATIO) -> Tuple[str, str]:
    """项目成本预警·纯语义规则（与 9006 _cost_status 逐字等价，已影子比对）。

    入参：
      budget        : 预算（来自 四算 预算基线；None/<=0 视为缺预算）
      current_cost  : 当前成本（来自 finance_detail 累计付款，缺失按 0）
      threshold     : 预算完成比阈值（默认 0.9）
    返回：(status, note)；status ∈ {正常, 预警, 超支}
    """
    b = budget if budget is not None else None
    c = current_cost if current_cost is not None else 0.0
    if b is None or b <= 0:
        if c > 0:
            return '正常', '缺预算，暂无法判定预警（当前成本 ¥%s）' % format(round(c), ',')
        return '正常', '缺预算且无当前成本，无法比较'
    ratio = c / b if b > 0 else None
    if ratio is not None and c > b:
        return '超支', '当前成本 ¥%s 已超过预算（超支 ¥%s）' % (
            format(round(c), ','), format(round(c - b), ','))
    if ratio is not None and ratio >= threshold:
        return '预警', '预算完成比已达 %d%%，接近预算上限' % round(ratio * 100)
    return '正常', '预算执行在阈值内（预算完成比 %d%%）' % (round(ratio * 100) if ratio is not None else 0)


def project_cost_warning(estimate: Optional[float] = None, budget: Optional[float] = None,
                         current_cost: Optional[float] = None) -> Dict[str, Any]:
    """Function F-project-cost-warning 的实现：在 cost_warning_rule 之上补齐
    预算完成比 / 剩余成本，返回结构化结果。纯函数、无 IO。"""
    c = float(current_cost) if current_cost is not None else 0.0
    b = float(budget) if budget is not None else None
    est = float(estimate) if estimate is not None else None
    status, note = cost_warning_rule(b, c)
    ratio = round(c / b, 4) if (b is not None and b > 0) else None
    remaining = round(b - c, 2) if (b is not None and c is not None) else None
    return {
        'status': status,
        'note': note,
        'estimate': est,
        'budget': b,
        'current_cost': c,
        'budget_ratio': ratio,
        'remaining_cost': remaining,
    }


# 其余 Function（F07 毛利率 / F08 回款周期）在本域声明为语义占位，
# 实现委托到 9006 既有 etl/project_metrics（P1 收敛后填入 impl，此处先声明）。
_FUNCTION_DEFS = [
    Definition(
        id="F-project-cost-warning", name="项目成本预警", kind="function", domain="project",
        description="依据 概算/预算 与 当前成本 计算预算执行比，给出 正常/预警/超支 状态。",
        inputs=["estimate", "budget", "current_cost"],
        outputs=["status", "note", "budget_ratio", "remaining_cost"],
        invariant="budget>=0 and current_cost>=0", version="0.1", ontology_bound=True,
    ),
    Definition(
        id="F-project-margin", name="项目毛利率", kind="function", domain="financial",
        description="项目/合同毛利率（优先 签单毛利/合同额，缺省回退 综合毛利率字段）。",
        inputs=["contract_no"], outputs=["gross_rate", "sign_amount", "sign_gross_profit"],
        invariant="sign_amount>0 implies gross_rate=sign_gross_profit/sign_amount",
        version="0.1", ontology_bound=True,
    ),
    Definition(
        id="F-payment-cycle", name="回款周期", kind="function", domain="financial",
        description="合同签订到回款的天数（PLM 里程碑实际/计划 > 收付款明细最后一笔回款）。",
        inputs=["contract_no"], outputs=["cycle_days", "sign_date", "recv_date"],
        invariant="cycle_days>=0", version="0.1", ontology_bound=True,
    ),
]


# ═══════════════════════════════════════════════════════════════════════
# Action：动力层·变更（写回，受约束 + 不变量 + 审计 + S1–S5）
# ═══════════════════════════════════════════════════════════════════════
ACTIONS_PROJ = {
    "createProject": {
        "定义": "立一个经营项目（生成 project_no，写入主数据）。",
        "条件": ["project_no 已给定且唯一", "商机号或合同号至少其一存在（可后置关联）"],
        "效果": "新增 Project(active)；写审计。",
        "不变量": ["project_no 全局唯一"],
        "幂等": True,
    },
    "linkContractToProject": {
        "定义": "将合同关联到项目（默认 1:1，支持 1:N 子项目）。",
        "条件": ["项目已立", "合同已存在或可同步新建"],
        "效果": "建立 project.hasContract(contract) 关系；回写 contract_no。",
        "不变量": ["同一合同只挂一个主项目（子项目另行挂接）"],
        "幂等": True,
    },
    "assignPersonnelToProject": {
        "定义": "将人员指派到项目（项目经理 / 销售负责人 / 交付工程师）。",
        "条件": ["项目已立", "人员已存在或可同步建档"],
        "效果": "建立 personnel.assignedTo(project) 关系；若是项目经理则置 managedBy。",
        "不变量": ["同一项目仅一名项目经理"],
        "幂等": True,
    },
    "raiseProjectCostWarning": {
        "定义": "当项目成本预警状态为 预警/超支 时，写一条 CostWarning 事实（供看板/智能体消费）。",
        "条件": ["项目已立", "成本预警状态 ∈ {预警, 超支}"],
        "效果": "新增 CostWarning(project, status, ratio, ts)；可触发通知。",
        "不变量": ["仅在状态非 正常 时写预警", "同一项目同状态不重复写（按周期去重）"],
        "幂等": True,
    },
}


# ═══════════════════════════════════════════════════════════════════════
# 全局不变量（跨动作，恒定成立——语义护栏 / 红线）
# ═══════════════════════════════════════════════════════════════════════
INVARIANTS = [
    {"id": "project-contract-1to1-default", "desc": "项目-合同默认 1:1；1:N 须经子项目显式挂接"},
    {"id": "no-physical-delete", "desc": "红线：事实（项目/合同/商机/人员）不得物理删除或覆盖，仅可置状态/打标"},
    {"id": "cost-warning-only-with-budget", "desc": "成本预警只在具备有效预算时判定；缺预算不得误报超支"},
    {"id": "budget-nonnegative", "desc": "预算/概算/当前成本均非负"},
    {"id": "traceable-action", "desc": "一切变更动作须可追溯到发起方（人/数字员工）并留审计"},
]


# ═══════════════════════════════════════════════════════════════════════
# ABox：从记录构造事实三元组（纯函数，无 DB 副作用）
# ═══════════════════════════════════════════════════════════════════════
def build_project_abox(project: Dict[str, Any]) -> Dict[str, Any]:
    """将项目记录(dict)转换为语义事实表(ABox)，供校验器使用。纯函数。"""
    meta = project.get("meta") or {}
    return {
        "project_no": project.get("project_no"),
        "status": project.get("status") or "active",
        "contract_no": project.get("contract_no") or meta.get("contract_no"),
        "opportunity_no": project.get("opportunity_no") or meta.get("opportunity_no"),
        "manager": project.get("manager") or meta.get("manager"),
        "personnel": meta.get("personnel") or [],
        "budget": project.get("budget"),
        "current_cost": project.get("current_cost"),
        "warning_raised": bool(meta.get("warning_raised")),
    }


def validate_project_action(action_id: str, abox: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """校验业务动作在『当前事实(ABox)』下是否可执行：(ok, 拒绝原因)。纯函数。"""
    spec = ACTIONS_PROJ.get(action_id)
    if not spec:
        return False, ["未知动作"]
    reasons: List[str] = []
    has_proj = bool(abox.get("project_no"))
    has_budget = abox.get("budget") is not None and float(abox.get("budget") or 0) > 0
    status = abox.get("status") or ""
    closed = status.upper() in ("CLOSED", "ARCHIVED", "CANCELLED")
    facts = {
        "项目已立": has_proj,
        "合同已存在或可同步新建": bool(abox.get("contract_no")) or True,
        "人员已存在或可同步建档": bool(abox.get("manager")) or True,
        "成本预警状态 ∈ {预警, 超支}": abox.get("warning_raised") or False,
        "project_no 已给定且唯一": has_proj,
        "商机号或合同号至少其一存在（可后置关联）": bool(abox.get("opportunity_no")) or bool(abox.get("contract_no")),
        "同一项目仅一名项目经理": True,
        "同一合同只挂一个主项目（子项目另行挂接）": True,
        "同一项目同状态不重复写（按周期去重）": bool(abox.get("warning_raised")) is False or True,
    }
    for c in spec.get("条件", []):
        if facts.get(c) is False:
            reasons.append(f"前置不满足: {c}")
    if closed:
        reasons.append("项目已关闭/归档/取消，禁止变更")
    return (len(reasons) == 0), reasons


# ═══════════════════════════════════════════════════════════════════════
# 注册表引导：导入即注册声明 + pilot 实现（单一真相，平台/智能体共享）
# ═══════════════════════════════════════════════════════════════════════
def _register() -> None:
    # Function 声明（语义占位）
    for d in _FUNCTION_DEFS:
        functions.register(d)
    # pilot：F-project-cost-warning 绑定实现
    functions.register(
        Definition(
            id="F-project-cost-warning", name="项目成本预警", kind="function", domain="project",
            description="依据 概算/预算 与 当前成本 计算预算执行比，给出 正常/预警/超支 状态。",
            inputs=["estimate", "budget", "current_cost"],
            outputs=["status", "note", "budget_ratio", "remaining_cost"],
            invariant="budget>=0 and current_cost>=0", version="0.1", ontology_bound=True,
        ),
        impl=project_cost_warning,
    )
    # Action 声明
    for aid, spec in ACTIONS_PROJ.items():
        actions.register(Definition(
            id=aid, name=aid, kind="action", domain="project",
            description=spec.get("定义", ""),
            inputs=list(spec.get("条件", [])),
            invariant="; ".join(spec.get("不变量", [])) or None,
            version="0.1", ontology_bound=True,
            meta={"效果": spec.get("效果", ""), "幂等": spec.get("幂等", True)},
        ))


_register()
