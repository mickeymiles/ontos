# -*- coding: utf-8 -*-
"""通用业务本体地基（ontos · 商机 / 合同 / 项目 / 人员 + 项目关联子实体）。

这是「基于本体的智能体平台」的通用业务域骨架。本文件 = **TBox（定义层）** 的
单一真相源：实体 / 属性 / 关系 / Function / Action 的声明都写在这里（纯 Python，
不落库；运行期只读导出，见 to_spec()）。ABox（真实数据行）在 9006 的 SQLite。

业务对齐结论（2026-09-03 与用户拍板）：
- 顶层实体：商机 / 合同 / 项目 / 人员 / 供应商（供应商单列，不与人员混淆）。
- 项目关联子实体：采购 Procurement / 里程碑 Milestone / 收款 Receipt / 付款 Payment
  / 成本明细 CostItem（生命周期依附项目，但有独立编号+状态+多属性）。
- 成本 = 派生度量：Project.current_cost = ΣPayment + ΣCostItem（用户确认要追明细）。
- 收款(流入/回款) 与 付款(流出) 拆为两个子实体（方向不同、来源系统不同）。
- 人员角色不另立实体，用「关系 + role 限定」表达（销售负责人/项目经理/工程师）。

设计原则（与 v1.2 总纲一致）：
- TBox 机器可读、可喂 LLM；Function/Action 为动力层（Function 只读判定，Action 写回受约束）。
- 声明与实现分离：声明本文件为真相，实现经注册表 impl 绑定（pilot 绑定本地纯函数）。
- 纯函数、零 DB / 零 app 运行时耦合。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .registry import Definition, functions, actions


# ═══════════════════════════════════════════════════════════════════════
# 结构化 TBox：实体 / 属性 / 关系（机器可读，可喂 LLM / 渲染可观测页）
# ═══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Attribute:
    name: str
    type: str                       # string | number | date | enum
    required: bool = False
    unique: bool = False
    source: str = ""               # 对应 9006 物理表字段（空=派生/待定）
    desc: str = ""


@dataclass
class Entity:
    name: str
    kind: str                                   # top(顶层) | child(子实体)
    parent: Optional[str] = None                # child 的父实体
    desc: str = ""
    attributes: List[Attribute] = field(default_factory=list)
    relations: List[str] = field(default_factory=list)   # 关系谓词 key（见 LINKS）


# 实体定义（含结构化属性 + 来源字段映射）
ENTITIES: Dict[str, Entity] = {
    "Opportunity": Entity(
        name="Opportunity", kind="top", desc="商机（销售线索，中标后生成项目）",
        attributes=[
            Attribute("opp_no", "string", True, True, "opportunity.opp_no", "商机编号"),
            Attribute("name", "string", True, False, "opportunity.name", "商机名称"),
            Attribute("customer", "string", False, False, "opportunity.customer", "客户"),
            Attribute("expected_amount", "number", False, False, "opportunity.expected_amount", "预计金额"),
            Attribute("stage", "enum", False, False, "opportunity.stage", "线索/跟进/投标/中标/丢单"),
            Attribute("win_rate", "number", False, False, "opportunity.win_rate", "赢率"),
        ],
        relations=["realizes", "ownedBy"],
    ),
    "Contract": Entity(
        name="Contract", kind="top", desc="合同（法律实体，可挂主合同+变更）",
        attributes=[
            Attribute("contract_no", "string", True, True, "contract.contract_no", "合同号"),
            Attribute("amount", "number", False, False, "contract.sign_amount", "签约金额"),
            Attribute("sign_date", "date", False, False, "contract.sign_date", "签约日期"),
            Attribute("period", "number", False, False, "contract.period", "合同周期(月)"),
            Attribute("type", "enum", False, False, "contract.type", "主合同/变更"),
        ],
        relations=["belongsTo", "hasReceipt", "hasPayment", "signedWith"],
    ),
    "Project": Entity(
        name="Project", kind="top", desc="项目（经营主数据根实体，枢纽）",
        attributes=[
            Attribute("project_no", "string", True, True, "core_project.project_no", "项目编号"),
            Attribute("name", "string", True, False, "core_project.name", "项目名称"),
            Attribute("status", "enum", False, False, "core_project.status", "进行中/已完成/关闭"),
            Attribute("budget", "number", False, False, "plm_baseline.total_cost", "预算(概算/预算基线)"),
            Attribute("current_cost", "number", False, False, "(派生)=ΣPayment+ΣCostItem", "当前成本(派生)"),
            Attribute("start_date", "date", False, False, "core_project.start_date", "开始日期"),
            Attribute("end_date", "date", False, False, "core_project.end_date", "结束日期"),
        ],
        relations=["managedBy", "hasMember", "hasProcurement", "hasMilestone", "hasCostItem", "realizes_inv"],
    ),
    "Personnel": Entity(
        name="Personnel", kind="top", desc="人员（人：销售/项目经理/工程师/客户联系人）",
        attributes=[
            Attribute("emp_no", "string", True, True, "personnel.emp_no", "工号"),
            Attribute("name", "string", True, False, "personnel.name", "姓名"),
            Attribute("title", "string", False, False, "personnel.title", "岗位"),
            Attribute("type", "enum", False, False, "personnel.type", "internal/external"),
        ],
        relations=["ownedBy_inv", "managedBy_inv", "hasMember_inv"],
    ),
    "Supplier": Entity(
        name="Supplier", kind="top", desc="供应商/往来单位（组织：供应商/客户/合作方）",
        attributes=[
            Attribute("supplier_no", "string", True, True, "supplier.supplier_no", "往来单位编号"),
            Attribute("name", "string", True, False, "supplier.name", "名称"),
            Attribute("type", "enum", False, False, "supplier.type", "supplier/client/partner"),
            Attribute("contact", "string", False, False, "supplier.contact", "联系人"),
        ],
        relations=["placedWith_inv", "signedWith_inv"],
    ),
    "Procurement": Entity(
        name="Procurement", kind="child", parent="Project", desc="采购订单（挂项目）",
        attributes=[
            Attribute("po_no", "string", True, True, "procurement.po_no", "采购单号"),
            Attribute("content", "string", False, False, "procurement.content", "采购内容"),
            Attribute("amount", "number", False, False, "procurement.amount", "金额"),
            Attribute("status", "enum", False, False, "procurement.status", "询价/审批/下单/到货/验收"),
        ],
        relations=["hasProcurement_inv", "placedWith"],
    ),
    "Milestone": Entity(
        name="Milestone", kind="child", parent="Project", desc="里程碑（挂项目）",
        attributes=[
            Attribute("ms_no", "string", True, True, "milestone.ms_no", "里程碑编号"),
            Attribute("name", "string", True, False, "milestone.name", "里程碑名称"),
            Attribute("plan_date", "date", False, False, "milestone.plan_date", "计划日期"),
            Attribute("actual_date", "date", False, False, "milestone.actual_date", "实际日期"),
            Attribute("status", "enum", False, False, "milestone.status", "未开始/进行中/已完成/风险"),
            Attribute("acceptance", "string", False, False, "milestone.acceptance", "验收结论"),
        ],
        relations=["hasMilestone_inv"],
    ),
    "Receipt": Entity(
        name="Receipt", kind="child", parent="Contract", desc="收款（客户→我方，流入/回款）",
        attributes=[
            Attribute("receipt_no", "string", True, True, "receipt.receipt_no", "收款单号"),
            Attribute("amount", "number", False, False, "receipt.amount", "金额"),
            Attribute("date", "date", False, False, "receipt.date", "到账日期"),
            Attribute("payer", "string", False, False, "receipt.payer", "付款方(客户)"),
            Attribute("status", "enum", False, False, "receipt.status", "待收/已收/退票"),
        ],
        relations=["hasReceipt_inv"],
    ),
    "Payment": Entity(
        name="Payment", kind="child", parent="Contract", desc="付款（我方→供应商/分包，流出）",
        attributes=[
            Attribute("payment_no", "string", True, True, "payment.payment_no", "付款单号"),
            Attribute("amount", "number", False, False, "payment.amount", "金额"),
            Attribute("date", "date", False, False, "payment.date", "付款日期"),
            Attribute("payee", "string", False, False, "payment.payee", "收款方(供应商)"),
            Attribute("status", "enum", False, False, "payment.status", "待付/已付/拒付"),
        ],
        relations=["hasPayment_inv", "placedWith_inv2"],
    ),
    "CostItem": Entity(
        name="CostItem", kind="child", parent="Project", desc="成本明细（人工/其他/预提，挂项目）",
        attributes=[
            Attribute("item_no", "string", True, True, "cost_item.item_no", "成本项编号"),
            Attribute("category", "enum", False, False, "cost_item.category", "人工/其他/预提"),
            Attribute("amount", "number", False, False, "cost_item.amount", "金额"),
            Attribute("period", "string", False, False, "cost_item.period", "归属期间"),
            Attribute("note", "string", False, False, "cost_item.note", "备注"),
        ],
        relations=["hasCostItem_inv"],
    ),
}


# 关系（Link）：主体.谓词(客体) [基数] 说明
LINKS: List[Dict[str, str]] = [
    {"predicate": "realizes", "subj": "Opportunity", "obj": "Project", "card": "1:1",
     "desc": "商机中标后生成项目"},
    {"predicate": "belongsTo", "subj": "Contract", "obj": "Project", "card": "N:1",
     "desc": "合同归属项目（主合同+变更可 1:N）"},
    {"predicate": "managedBy", "subj": "Project", "obj": "Personnel", "card": "1:1",
     "desc": "项目由某人员任项目经理"},
    {"predicate": "hasMember", "subj": "Project", "obj": "Personnel", "card": "N:M",
     "desc": "人员参与项目（role=销售/交付工程师…，带角色限定）"},
    {"predicate": "ownedBy", "subj": "Opportunity", "obj": "Personnel", "card": "1:1",
     "desc": "商机由销售负责人跟进"},
    {"predicate": "hasProcurement", "subj": "Project", "obj": "Procurement", "card": "1:N",
     "desc": "项目下采购订单"},
    {"predicate": "placedWith", "subj": "Procurement", "obj": "Supplier", "card": "N:1",
     "desc": "采购订单向某供应商下单"},
    {"predicate": "hasMilestone", "subj": "Project", "obj": "Milestone", "card": "1:N",
     "desc": "项目里程碑"},
    {"predicate": "hasReceipt", "subj": "Contract", "obj": "Receipt", "card": "1:N",
     "desc": "合同收款（客户→我方，回款）"},
    {"predicate": "hasPayment", "subj": "Contract", "obj": "Payment", "card": "1:N",
     "desc": "合同/采购付款（我方→供应商，流出）"},
    {"predicate": "hasCostItem", "subj": "Project", "obj": "CostItem", "card": "1:N",
     "desc": "项目成本明细（人工/其他/预提）"},
    {"predicate": "signedWith", "subj": "Contract", "obj": "Supplier", "card": "N:2",
     "desc": "合同签约方（甲方客户/乙方我方或供应商，Supplier.type 区分）"},
]

# 兼容导出：供 9006 /spec 渲染器（历史字段名）
CONCEPTS = {name: e.desc for name, e in ENTITIES.items()}
RELATIONS = {f"{l['subj']}.{l['predicate']}({l['obj']})": l["desc"] for l in LINKS}


# ═══════════════════════════════════════════════════════════════════════
# Function：动力层·计算/判定（只读，不改事实）
# ═══════════════════════════════════════════════════════════════════════
COST_WARNING_RATIO = 0.9  # 预算完成比阈值：≥90% 触发预警（对齐 9006 COST_WARNING_RATIO）


def cost_warning_rule(budget: Optional[float], current_cost: Optional[float],
                      threshold: float = COST_WARNING_RATIO) -> Tuple[str, str]:
    """项目成本预警·纯语义规则（与 9006 _cost_status 逐字等价，已影子比对）。

    入参：budget 预算（None/<=0 视为缺预算）；current_cost 当前成本（缺失按 0）。
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
    """Function F-project-cost-warning 实现：在 cost_warning_rule 之上补齐
    预算完成比 / 剩余成本，返回结构化结果。纯函数、无 IO。"""
    c = float(current_cost) if current_cost is not None else 0.0
    b = float(budget) if budget is not None else None
    est = float(estimate) if estimate is not None else None
    status, note = cost_warning_rule(b, c)
    ratio = round(c / b, 4) if (b is not None and b > 0) else None
    remaining = round(b - c, 2) if (b is not None and c is not None) else None
    return {
        'status': status, 'note': note, 'estimate': est, 'budget': b,
        'current_cost': c, 'budget_ratio': ratio, 'remaining_cost': remaining,
    }


def cost_rollup(payments: List[Dict[str, Any]], cost_items: List[Dict[str, Any]]) -> Dict[str, float]:
    """Function F-cost-rollup 实现：项目当前成本 = Σ付款 + Σ成本明细（人工/其他/预提）。

    与用户拍板的成本模型一致：成本不是独立事物，而是 Payment + CostItem 的聚合。
    纯函数、无 IO。
    """
    pay_sum = round(sum(float(p.get("amount") or 0) for p in payments), 2)
    item_sum = round(sum(float(c.get("amount") or 0) for c in cost_items), 2)
    return {
        "current_cost": round(pay_sum + item_sum, 2),
        "payment_sum": pay_sum,
        "costitem_sum": item_sum,
    }


_FUNCTION_DEFS = [
    Definition(
        id="F-project-cost-warning", name="项目成本预警", kind="function", domain="project",
        description="依据 预算 与 当前成本 计算预算执行比，给出 正常/预警/超支 状态。",
        inputs=["estimate", "budget", "current_cost"],
        outputs=["status", "note", "budget_ratio", "remaining_cost"],
        invariant="budget>=0 and current_cost>=0", version="0.2", ontology_bound=True,
    ),
    Definition(
        id="F-cost-rollup", name="项目成本聚合", kind="function", domain="project",
        description="项目当前成本 = Σ付款(Payment) + Σ成本明细(CostItem)。成本明细含人工/其他/预提。",
        inputs=["payments", "cost_items"], outputs=["current_cost", "payment_sum", "costitem_sum"],
        invariant="current_cost = payment_sum + costitem_sum and all>=0", version="0.2", ontology_bound=True,
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
        description="合同签订到回款的天数（基于 Receipt 最近一笔到账日期）。",
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
        "不变量": ["project_no 全局唯一"], "幂等": True,
    },
    "linkContractToProject": {
        "定义": "将合同关联到项目。",
        "条件": ["项目已立", "合同已存在或可同步新建"],
        "效果": "建立 project.hasContract(contract)。",
        "不变量": ["同一合同只挂一个主项目"], "幂等": True,
    },
    "assignPersonnelToProject": {
        "定义": "将人员指派到项目（项目经理/销售/交付工程师，role 限定）。",
        "条件": ["项目已立", "人员已存在或可同步建档"],
        "效果": "建立 hasMember(role)；若项目经理则置 managedBy。",
        "不变量": ["同一项目仅一名项目经理"], "幂等": True,
    },
    "createProcurement": {
        "定义": "在项目下新建采购订单。",
        "条件": ["项目已立"],
        "效果": "新增 Procurement，建立 hasProcurement + placedWith(Supplier)。",
        "不变量": ["po_no 全局唯一"], "幂等": True,
    },
    "recordPayment": {
        "定义": "记录一笔付款（我方→供应商/分包，流出）。",
        "条件": ["关联合同或采购订单已立"],
        "效果": "新增 Payment，建立 hasPayment。",
        "不变量": ["payment_no 全局唯一", "amount>=0"], "幂等": True,
    },
    "recordReceipt": {
        "定义": "记录一笔收款（客户→我方，流入/回款）。",
        "条件": ["关联合同已立"],
        "效果": "新增 Receipt，建立 hasReceipt。",
        "不变量": ["receipt_no 全局唯一", "amount>=0"], "幂等": True,
    },
    "addCostItem": {
        "定义": "追加一笔成本明细（人工/其他/预提）。",
        "条件": ["项目已立"],
        "效果": "新增 CostItem，建立 hasCostItem；影响 Project.current_cost(派生)。",
        "不变量": ["item_no 全局唯一", "amount>=0", "category∈{人工,其他,预提}"], "幂等": True,
    },
    "completeMilestone": {
        "定义": "标记里程碑完成（含实际日期/验收结论）。",
        "条件": ["里程碑已立"],
        "效果": "更新 Milestone.status=已完成 + actual_date + acceptance。",
        "不变量": ["actual_date 不早于 plan_date(软约束，可标注延期)"], "幂等": True,
    },
    "raiseProjectCostWarning": {
        "定义": "当成本预警状态为 预警/超支 时，写一条 CostWarning 事实。",
        "条件": ["项目已立", "成本预警状态 ∈ {预警, 超支}"],
        "效果": "新增 CostWarning(project, status, ratio, ts)；可触发通知。",
        "不变量": ["仅在状态非 正常 时写预警", "同状态按周期去重"], "幂等": True,
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
    {"id": "cost-rollup-nonnegative", "desc": "current_cost = ΣPayment + ΣCostItem，各项均非负"},
    {"id": "payment-receipt-distinct", "desc": "收款(流入/回款)与付款(流出)为独立实体，方向不同不得混用"},
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
    status = abox.get("status") or ""
    closed = status.upper() in ("CLOSED", "ARCHIVED", "CANCELLED")
    facts = {
        "项目已立": has_proj,
        "合同已立": bool(abox.get("contract_no")),
        "关联合同或采购订单已立": bool(abox.get("contract_no")),
        "商机号或合同号至少其一存在（可后置关联）": bool(abox.get("opportunity_no")) or bool(abox.get("contract_no")),
        "project_no 已给定且唯一": has_proj,
        "同一项目仅一名项目经理": True,
        "同一合同只挂一个主项目（子项目另行挂接）": True,
        "成本预警状态 ∈ {预警, 超支}": abox.get("warning_raised") or False,
    }
    for c in spec.get("条件", []):
        if facts.get(c) is False:
            reasons.append(f"前置不满足: {c}")
    if closed:
        reasons.append("项目已关闭/归档/取消，禁止变更")
    return (len(reasons) == 0), reasons


# ═══════════════════════════════════════════════════════════════════════
# to_spec()：导出 TBox 供 9006 本体可观测页 / LLM 语境（不落库，运行期只读）
# ═══════════════════════════════════════════════════════════════════════
def to_spec() -> Dict[str, Any]:
    """导出当前 TBox，形状兼容 9006 /api/ontology/spec，可直接被可观测页渲染。

    返回 concepts / relations / functions / actions / invariants（历史字段）
    + entities / links（结构化扩展，含属性与来源字段映射）。
    """
    return {
        "concepts": CONCEPTS,
        "relations": RELATIONS,
        "functions": [functions.get(fid).__dict__ for fid in functions.ids()],
        "actions": [
            {"id": aid, "name": aid, "definition": s["定义"], "conditions": s["条件"],
             "effects": s["效果"], "invariants": s["不变量"], "idempotent": s["幂等"]}
            for aid, s in ACTIONS_PROJ.items()
        ],
        "invariants": INVARIANTS,
        "entities": [
            {
                "name": e.name, "kind": e.kind, "parent": e.parent, "desc": e.desc,
                "attributes": [
                    {"name": a.name, "type": a.type, "required": a.required,
                     "unique": a.unique, "source": a.source, "desc": a.desc}
                    for a in e.attributes
                ],
                "relations": e.relations,
            }
            for e in ENTITIES.values()
        ],
        "links": LINKS,
    }


# ═══════════════════════════════════════════════════════════════════════
# 注册表引导：导入即注册声明 + pilot 实现（单一真相，平台/智能体共享）
# ═══════════════════════════════════════════════════════════════════════
def _register() -> None:
    for d in _FUNCTION_DEFS:
        functions.register(d)
    functions.register(
        Definition(
            id="F-project-cost-warning", name="项目成本预警", kind="function", domain="project",
            description="依据 预算 与 当前成本 计算预算执行比，给出 正常/预警/超支 状态。",
            inputs=["estimate", "budget", "current_cost"],
            outputs=["status", "note", "budget_ratio", "remaining_cost"],
            invariant="budget>=0 and current_cost>=0", version="0.2", ontology_bound=True,
        ),
        impl=project_cost_warning,
    )
    functions.register(
        Definition(
            id="F-cost-rollup", name="项目成本聚合", kind="function", domain="project",
            description="项目当前成本 = Σ付款(Payment) + Σ成本明细(CostItem)。",
            inputs=["payments", "cost_items"],
            outputs=["current_cost", "payment_sum", "costitem_sum"],
            invariant="current_cost = payment_sum + costitem_sum and all>=0",
            version="0.2", ontology_bound=True,
        ),
        impl=cost_rollup,
    )
    for aid, spec in ACTIONS_PROJ.items():
        actions.register(Definition(
            id=aid, name=aid, kind="action", domain="project",
            description=spec.get("定义", ""),
            inputs=list(spec.get("条件", [])),
            invariant="; ".join(spec.get("不变量", [])) or None,
            version="0.2", ontology_bound=True,
            meta={"效果": spec.get("效果", ""), "幂等": spec.get("幂等", True)},
        ))


_register()
