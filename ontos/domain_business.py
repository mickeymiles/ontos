# -*- coding: utf-8 -*-
"""通用业务本体地基（ontos · 场景收敛锁定版 v4 · 合同/项目/里程碑/收款/付款）。

这是「基于本体的智能体平台」的通用业务域骨架。本文件 = **TBox（定义层）** 的
单一真相源：实体 / 属性 / 关系 / Function / Action 的声明都写在这里（纯 Python，
不落库；运行期只读导出，见 to_spec()）。ABox（真实数据行）在 9006 的 SQLite。

═══ v4 场景收敛（2026-09-03 与用户拍板）═══
当前只覆盖 **5 个财务/经营分析场景**，只构建它们直接需要的本体：
  回款周期 / 资金占用 / 项目毛利率 / 项目成本预警 / 项目 ROI。
其余（商机/报价单/采购流程/人员/供应商主数据/成本明细实体）列入范围外（⌛），后续补充。

关键定义决议：
- 实体（5）：合同 Contract / 项目 Project / 里程碑 Milestone / 收款单 Receipt / 付款单 Payment。
  * 里程碑大/小均挂项目；小里程碑通过 decomposedFrom 关联大里程碑（是大里程碑的细化分解）。
  * 收款/付款是经营对象实体（非流水集合）：里程碑确认产值 → 开票 → 账期 → 回款/付款（可分期、可逾期）。
- 成本 = Project 的**派生度量属性**（非实体）：current_cost = ΣPayment + Σ成本明细行(ABox)。
  成本明细行保留在数据层做下钻，不在 TBox 升格为实体（待"需独立处理成本项"场景再升格）。
- 范围外关系 / 实体仅占位，不进主 LINKS/ENTITIES 渲染（见 OUT_OF_SCOPE_* 注释）。

设计原则（v1.2 总纲）：
- TBox 机器可读、可喂 LLM；Function 只读判定，Action 写回受约束 + 不变量 + 审计。
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
    "Contract": Entity(
        name="Contract", kind="top", desc="合同（法律实体，归属项目；毛利率场景需签单毛利）",
        attributes=[
            Attribute("contract_no", "string", True, True, "contract.contract_no", "合同号"),
            Attribute("amount", "number", False, False, "contract.sign_amount", "签约金额"),
            Attribute("sign_date", "date", False, False, "contract.sign_date", "签约日期"),
            Attribute("period", "number", False, False, "contract.period", "合同周期(月)"),
            Attribute("type", "enum", False, False, "contract.type", "主合同/变更"),
            Attribute("sign_gross_profit", "number", False, False, "contract.sign_gross_profit", "签单毛利(○待建列)"),
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
            Attribute("current_cost", "number", False, False, "(派生)=ΣPayment+Σ成本明细行(ABox)", "当前成本(派生属性)"),
            Attribute("start_date", "date", False, False, "core_project.start_date", "开始日期"),
            Attribute("end_date", "date", False, False, "core_project.end_date", "结束日期"),
        ],
        relations=["belongsTo_inv", "hasMilestone"],
    ),
    "Milestone": Entity(
        name="Milestone", kind="child", parent="Project",
        desc="里程碑（挂项目；分大/小两级，小里程碑是大里程碑的执行拆解）",
        attributes=[
            Attribute("ms_no", "string", True, True, "milestone.ms_no", "里程碑编号"),
            Attribute("name", "string", True, False, "milestone.name", "里程碑名称"),
            Attribute("level", "enum", False, False, "milestone.level", "major(合同里程碑·粗)/minor(执行里程碑·细·○待建列)"),
            Attribute("plan_date", "date", False, False, "milestone.plan_date", "计划日期"),
            Attribute("actual_date", "date", False, False, "milestone.actual_date", "实际日期"),
            Attribute("status", "enum", False, False, "milestone.status", "未开始/进行中/已完成/风险"),
            Attribute("acceptance", "string", False, False, "milestone.acceptance", "验收结论"),
            Attribute("value", "number", False, False, "milestone.value/plan_output", "大里程碑对应产值(合同额分摊·○待建列)"),
            Attribute("progress", "number", False, False, "milestone.progress", "小里程碑进度%(○待建列)"),
            Attribute("parent_ms", "string", False, False, "milestone.parent_ms", "小里程碑→父大里程碑(ms_no·○待建列)"),
        ],
        relations=["hasMilestone_inv", "decomposedFrom", "realizesReceivable"],
    ),
    "Receipt": Entity(
        name="Receipt", kind="child", parent="Contract",
        desc="收款/回款单（经营对象：里程碑确认产值→开票→账期→回款；可分期、可逾期）",
        attributes=[
            Attribute("receipt_no", "string", True, True, "finance_detail.receipt_no", "收款单号(○待建列)"),
            Attribute("source_milestone", "string", False, False, "finance_detail.source_milestone", "产值来源里程碑(ms_no·○待建列)"),
            Attribute("amount", "number", False, False, "finance_detail.amount", "应收/开票金额"),
            Attribute("invoice_no", "string", False, False, "finance_detail.invoice_no", "发票号(○待建列)"),
            Attribute("invoice_date", "date", False, False, "finance_detail.invoice_date", "开票日(○待建列)"),
            Attribute("invoiced", "enum", False, False, "finance_detail.invoiced", "未开票/已开票(○待建列)"),
            Attribute("due_date", "date", False, False, "finance_detail.due_date", "到期日(账期截止·○待建列)"),
            Attribute("received_amount", "number", False, False, "finance_detail.received_amount", "已回款金额(○待建列)"),
            Attribute("received_date", "date", False, False, "finance_detail.received_date", "回款日(○待建列)"),
            Attribute("payer", "string", False, False, "finance_detail.payer", "付款方(客户)"),
            Attribute("status", "enum", False, False, "finance_detail.status", "待收/部分/已收/逾期(○待建列)"),
        ],
        relations=["hasReceipt_inv", "sourceMilestone"],
    ),
    "Payment": Entity(
        name="Payment", kind="child", parent="Contract",
        desc="付款/应付单（经营对象：供应商交付→收票→账期→付款；可分期、可逾期；source_po ⌛待采购域）",
        attributes=[
            Attribute("payment_no", "string", True, True, "finance_detail.payment_no", "付款单号(○待建列)"),
            Attribute("source_po", "string", False, False, "finance_detail.source_po", "来源采购单(po_no·⌛待采购域接入)"),
            Attribute("amount", "number", False, False, "finance_detail.amount", "应付/开票金额"),
            Attribute("invoice_no", "string", False, False, "finance_detail.invoice_no", "供应商发票号(○待建列)"),
            Attribute("invoice_date", "date", False, False, "finance_detail.invoice_date", "收票日(○待建列)"),
            Attribute("invoiced", "enum", False, False, "finance_detail.invoiced", "未收票/已收票(○待建列)"),
            Attribute("due_date", "date", False, False, "finance_detail.due_date", "付款到期日(账期截止·○待建列)"),
            Attribute("paid_amount", "number", False, False, "finance_detail.paid_amount", "已付金额(○待建列)"),
            Attribute("paid_date", "date", False, False, "finance_detail.paid_date", "付款日(○待建列)"),
            Attribute("payee", "string", False, False, "finance_detail.payee", "收款方(供应商)"),
            Attribute("status", "enum", False, False, "finance_detail.status", "待付/部分/已付/逾期(○待建列)"),
        ],
        relations=["hasPayment_inv", "sourceProcurement_out"],
    ),
}


# 关系（Link）：主体.谓词(客体) [基数] 说明
LINKS: List[Dict[str, str]] = [
    {"predicate": "belongsTo", "subj": "Contract", "obj": "Project", "card": "N:1",
     "desc": "合同归属项目（主合同+变更可 1:N）"},
    {"predicate": "hasMilestone", "subj": "Project", "obj": "Milestone", "card": "1:N",
     "desc": "项目里程碑（大/小均挂项目）"},
    {"predicate": "decomposedFrom", "subj": "Milestone", "obj": "Milestone", "card": "N:1",
     "desc": "小里程碑(执行)按大里程碑(合同)拆解、关联父大里程碑"},
    {"predicate": "realizesReceivable", "subj": "Milestone", "obj": "Receipt", "card": "1:N",
     "desc": "大里程碑确认产值，据此生成应收/回款单（产值来源）"},
    {"predicate": "sourceMilestone", "subj": "Receipt", "obj": "Milestone", "card": "N:1",
     "desc": "回款单对应的产值来源里程碑"},
    {"predicate": "hasReceipt", "subj": "Contract", "obj": "Receipt", "card": "1:N",
     "desc": "合同收款（客户→我方，回款）"},
    {"predicate": "hasPayment", "subj": "Contract", "obj": "Payment", "card": "1:N",
     "desc": "合同/采购付款（我方→供应商，流出）"},
    {"predicate": "signedWith", "subj": "Contract", "obj": "Supplier", "card": "N:2",
     "desc": "合同签约方（甲方客户/乙方我方或供应商；⌛ Supplier 范围外，仅占位）"},
]

# ═══════════════════════════════════════════════════════════════════════
# 范围外占位（⌛ 本版不构建，仅记录以便后续收敛，不进 to_spec 主渲染）
# ═══════════════════════════════════════════════════════════════════════
# 范围外实体：Opportunity(商机) / Personnel(人员) / Supplier(供应商) / Procurement(采购)
#             / Quote(报价单) / CostItem(成本明细·降级为 ABox 数据)。
# 范围外关系（待对应场景补充时再加）：
#   realizes(Opportunity→Project) / ownedBy(Opportunity→Personnel)
#   managedBy(Project→Personnel) / hasMember(Project→Personnel)
#   hasProcurement(Project→Procurement) / placedWith(Procurement→Supplier)
#   payableFrom(Procurement→Payment) / sourceProcurement(Payment→Procurement)
#   hasCostItem(Project→CostItem) / answersInquiry(Quote→Procurement)
#   procuresAgainst(Procurement→Contract) / hasQuote(Opportunity→Quote)

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


def cost_rollup(payments: List[Dict[str, Any]], cost_detail_rows: List[Dict[str, Any]]) -> Dict[str, float]:
    """Function F-cost-rollup 实现：项目当前成本 = Σ付款(Payment) + Σ成本明细行(ABox)。

    成本明细行（人工/其他/预提）来自 ABox 数据层，不在 TBox 升格为实体。
    纯函数、无 IO。
    """
    pay_sum = round(sum(float(p.get("amount") or 0) for p in payments), 2)
    item_sum = round(sum(float(c.get("amount") or 0) for c in cost_detail_rows), 2)
    return {
        "current_cost": round(pay_sum + item_sum, 2),
        "payment_sum": pay_sum,
        "costitem_sum": item_sum,
    }


def receivable_status(invoice_date: Optional[str] = None, due_date: Optional[str] = None,
                      amount: float = 0.0, received_amount: float = 0.0,
                      received_date: Optional[str] = None,
                      today: Optional[str] = None) -> Dict[str, Any]:
    """Function F-receivable-status 实现：应收/回款单的**状态 + 账龄 + 逾期**判定。

    输入：invoice_date 开票日, due_date 到期日(账期截止), amount 应收金额,
          received_amount 已回款, received_date 回款日, today 今天(缺省取系统日期)。
    输出：status∈{待收,部分,已收,逾期}, remain 未回金额, overdue_days 逾期天数,
          aging_days 账龄天数, aging_bucket 账龄区间。
    规则：已收>=应收→已收；0<已收<应收→部分；已收=0 且 today>due_date→逾期；否则待收。
    纯函数、无 IO（today 缺省用系统日期，仅影响未显式传参时的判定）。
    """
    from datetime import date as _date, datetime as _dt

    def _parse(s):
        if not s:
            return None
        try:
            return _dt.strptime(str(s), "%Y-%m-%d").date()
        except Exception:
            return None

    amt = float(amount or 0)
    recv = float(received_amount or 0)
    remain = round(amt - recv, 2)
    t = _parse(today) or _date.today()
    dd = _parse(due_date)
    overdue_days = (t - dd).days if dd is not None else None
    # 状态判定
    if amt > 0 and recv >= amt:
        status = "已收"
    elif recv > 0:
        status = "部分"
    elif overdue_days is not None and overdue_days > 0:
        status = "逾期"
    else:
        status = "待收"
    # 账龄区间（开票日 → 今天）
    inv = _parse(invoice_date)
    aging_days = (t - inv).days if inv is not None else None
    if aging_days is None:
        bucket = "未知"
    elif aging_days <= 30:
        bucket = "0-30天"
    elif aging_days <= 60:
        bucket = "31-60天"
    elif aging_days <= 90:
        bucket = "61-90天"
    else:
        bucket = "90天以上"
    return {
        "status": status, "remain": remain,
        "overdue_days": overdue_days, "aging_days": aging_days,
        "aging_bucket": bucket,
    }


def payment_cycle(sign_date: Optional[str] = None, receipts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Function F-payment-cycle 实现：回款周期 = 签约日 → 首笔回款日。

    输入：sign_date 签约日, receipts 回款单列表（取 received_date / due_date）。
    输出：cycle_days(签约到首笔回款天数), sign_date, first_recv_date, due_date(首笔账期)。
    纯函数、无 IO。
    """
    from datetime import datetime as _dt

    def _parse(s):
        if not s:
            return None
        try:
            return _dt.strptime(str(s), "%Y-%m-%d").date()
        except Exception:
            return None

    sd = _parse(sign_date)
    recvs = receipts or []
    recv_dates = [_parse(r.get("received_date")) for r in recvs]
    recv_dates = [d for d in recv_dates if d]
    first_recv = min(recv_dates) if recv_dates else None
    due_dates = [_parse(r.get("due_date")) for r in recvs]
    due_dates = [d for d in due_dates if d]
    due = min(due_dates) if due_dates else None
    cycle_days = (first_recv - sd).days if (sd and first_recv) else None
    return {
        "cycle_days": cycle_days,
        "sign_date": sign_date,
        "first_recv_date": first_recv.isoformat() if first_recv else None,
        "due_date": due.isoformat() if due else None,
    }


def capital_occupation(payments: Optional[List[Dict[str, Any]]] = None,
                       receipts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Function F-capital-occupation 实现：资金占用 = 已付 + 应收未收。

    输入：payments 付款单列表(取 paid_amount/amount), receipts 收款单列表(取 amount/received_amount)。
    输出：occupied(净占用), paid_total(已付合计), receivable_remain(应收未收), net(=occupied)。
    基线：occupied = ΣPayment.paid_amount + ΣReceipt.remain(amount - received_amount)。
    纯函数、无 IO。
    """
    pays = payments or []
    recvs = receipts or []
    paid_total = round(sum(float(p.get("paid_amount") or p.get("amount") or 0) for p in pays), 2)
    recv_total = round(sum(float(r.get("amount") or 0) for r in recvs), 2)
    recv_recv = round(sum(float(r.get("received_amount") or 0) for r in recvs), 2)
    receivable_remain = round(recv_total - recv_recv, 2)
    occupied = round(paid_total + receivable_remain, 2)
    return {
        "occupied": occupied,
        "paid_total": paid_total,
        "receivable_remain": receivable_remain,
        "net": occupied,
    }


def project_margin(sign_amount: float = 0.0, sign_gross_profit: float = 0.0) -> Dict[str, Any]:
    """Function F-project-margin 实现：项目/合同毛利率 = 签单毛利 / 合同额。

    输入：sign_amount 签约金额, sign_gross_profit 签单毛利。
    输出：gross_rate(毛利率) | None(合同额非正)。纯函数、无 IO。
    """
    a = float(sign_amount or 0)
    g = float(sign_gross_profit or 0)
    if a <= 0:
        return {"gross_rate": None, "sign_amount": a, "sign_gross_profit": g,
                "note": "合同额非正，毛利率无意义"}
    return {"gross_rate": round(g / a, 4), "sign_amount": a, "sign_gross_profit": g}


def project_roi(revenue: float = 0.0, current_cost: float = 0.0) -> Dict[str, Any]:
    """Function F-project-roi 实现：项目 ROI = (收益 - 成本) / 成本。

    收益可取回款总额或合同额；current_cost 取 Project.current_cost(派生)。
    输入：revenue 收益, current_cost 当前成本。
    输出：roi | None(成本非正)。纯函数、无 IO。
    """
    c = float(current_cost or 0)
    r = float(revenue or 0)
    if c <= 0:
        return {"roi": None, "revenue": r, "current_cost": c,
                "note": "当前成本非正，ROI 无意义"}
    return {"roi": round((r - c) / c, 4), "revenue": r, "current_cost": c}


_FUNCTION_DEFS: List[Definition] = [
    Definition(
        id="F-payment-cycle", name="回款周期", kind="function", domain="financial",
        description="合同签订到首笔回款的天数（基于 Receipt 回款日；账期=开票日+账期天数）。",
        inputs=["sign_date", "receipts"],
        outputs=["cycle_days", "sign_date", "first_recv_date", "due_date"],
        invariant="cycle_days>=0", version="0.4", ontology_bound=True,
    ),
    Definition(
        id="F-receivable-status", name="应收/回款状态", kind="function", domain="financial",
        description="基于 开票日/到期日/应收金额/已回款 判定 待收/部分/已收/逾期，并给出账龄区间与逾期天数。",
        inputs=["invoice_date", "due_date", "amount", "received_amount", "received_date", "today"],
        outputs=["status", "remain", "overdue_days", "aging_days", "aging_bucket"],
        invariant="remain = amount - received_amount and remain>=0", version="0.4", ontology_bound=True,
    ),
    Definition(
        id="F-capital-occupation", name="资金占用", kind="function", domain="financial",
        description="资金占用 = Σ已付(Payment.paid_amount) + Σ应收未收(Receipt.amount-received_amount)。",
        inputs=["payments", "receipts"],
        outputs=["occupied", "paid_total", "receivable_remain", "net"],
        invariant="occupied = paid_total + receivable_remain and all>=0", version="0.4", ontology_bound=True,
    ),
    Definition(
        id="F-project-margin", name="项目毛利率", kind="function", domain="financial",
        description="项目/合同毛利率 = 签单毛利 / 合同额。",
        inputs=["sign_amount", "sign_gross_profit"],
        outputs=["gross_rate", "sign_amount", "sign_gross_profit"],
        invariant="sign_amount>0 implies gross_rate=sign_gross_profit/sign_amount",
        version="0.4", ontology_bound=True,
    ),
    Definition(
        id="F-project-cost-warning", name="项目成本预警", kind="function", domain="project",
        description="依据 预算 与 当前成本 计算预算执行比，给出 正常/预警/超支 状态。",
        inputs=["estimate", "budget", "current_cost"],
        outputs=["status", "note", "budget_ratio", "remaining_cost"],
        invariant="budget>=0 and current_cost>=0", version="0.4", ontology_bound=True,
    ),
    Definition(
        id="F-cost-rollup", name="项目成本聚合", kind="function", domain="project",
        description="项目当前成本 = Σ付款(Payment) + Σ成本明细行(ABox，人工/其他/预提)。",
        inputs=["payments", "cost_detail_rows"], outputs=["current_cost", "payment_sum", "costitem_sum"],
        invariant="current_cost = payment_sum + costitem_sum and all>=0", version="0.4", ontology_bound=True,
    ),
    Definition(
        id="F-project-roi", name="项目ROI", kind="function", domain="financial",
        description="项目 ROI = (收益 - 当前成本) / 当前成本；收益取回款总额或合同额。",
        inputs=["revenue", "current_cost"], outputs=["roi", "revenue", "current_cost"],
        invariant="current_cost>0 implies roi=(revenue-current_cost)/current_cost",
        version="0.4", ontology_bound=True,
    ),
]

# 声明 + 实现绑定（单一真相，平台/智能体共享）
_FUNCTION_IMPLS = {
    "F-payment-cycle": payment_cycle,
    "F-receivable-status": receivable_status,
    "F-capital-occupation": capital_occupation,
    "F-project-margin": project_margin,
    "F-project-cost-warning": project_cost_warning,
    "F-cost-rollup": cost_rollup,
    "F-project-roi": project_roi,
}


# ═══════════════════════════════════════════════════════════════════════
# Action：动力层·变更（写回，受约束 + 不变量 + 审计 + S1–S5）
# ═══════════════════════════════════════════════════════════════════════
ACTIONS_PROJ = {
    "recordReceipt": {
        "定义": "记录一笔收款（客户→我方，流入/回款；含产值来源/开票/账期/已收）。",
        "条件": ["关联合同已立", "source_milestone 已确认产值（realizesReceivable）"],
        "效果": "新增 Receipt（含 source_milestone/发票/账期/received_amount），建立 hasReceipt + sourceMilestone。",
        "不变量": ["receipt_no 全局唯一", "amount>=0", "received_amount<=amount", "invoiced=已开票 方可回款"], "幂等": True,
    },
    "recordPayment": {
        "定义": "记录一笔付款（我方→供应商/分包，流出；含开票/账期/已付；source_po ⌛待采购域）。",
        "条件": ["关联合同已立"],
        "效果": "新增 Payment（含发票/账期/paid_amount），建立 hasPayment。",
        "不变量": ["payment_no 全局唯一", "amount>=0", "paid_amount<=amount"], "幂等": True,
    },
    "confirmMilestoneValue": {
        "定义": "大里程碑达成（初验）确认产值(value)，建立 realizesReceivable 关系（可据此开票回款）。",
        "条件": ["里程碑已立(且 level=major)", "验收结论已填（acceptance）", "value>=0"],
        "效果": "更新 Milestone.value + status=已完成；建立 realizesReceivable(Milestone→Receipt)。",
        "不变量": ["value>=0", "未确认产值不得生成应收", "仅 major 里程碑可确认产值"], "幂等": True,
    },
    "createMinorMilestone": {
        "定义": "在大里程碑下新建小里程碑（执行拆解，按月份/任务细化），关联父大里程碑。",
        "条件": ["父大里程碑(Milestone.level=major)已立"],
        "效果": "新增 Milestone(level=minor)，建立 decomposedFrom(→父大里程碑)。",
        "不变量": ["ms_no 全局唯一", "parent_ms 必须指向一 major 里程碑"], "幂等": True,
    },
    "completeMilestone": {
        "定义": "标记里程碑完成（含实际日期/验收结论；小里程碑完成可累加 project 进度）。",
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
    {"id": "budget-nonnegative", "desc": "预算/概算/当前成本均非负"},
    {"id": "no-physical-delete", "desc": "红线：事实（项目/合同）不得物理删除或覆盖，仅可置状态/打标"},
    {"id": "cost-warning-only-with-budget", "desc": "成本预警只在具备有效预算时判定；缺预算不得误报超支"},
    {"id": "traceable-action", "desc": "一切变更动作须可追溯到发起方（人/数字员工）并留审计"},
    {"id": "payment-receipt-distinct", "desc": "收款(流入/回款)与付款(流出)为独立实体，方向不同不得混用"},
    {"id": "receivable-from-milestone", "desc": "回款单须源自里程碑确认的产值(source_milestone=realizesReceivable)，无产值不回款"},
    {"id": "invoice-before-receipt", "desc": "回款/付款须先开票(invoiced=已开票)，账期自开票日起算，到期未回为逾期"},
    {"id": "received-not-exceed-amount", "desc": "已回款/已付金额不得大于应收/应付金额"},
    {"id": "milestone-level-model", "desc": "小里程碑须通过 decomposedFrom 关联大里程碑（大里程碑确认产值，小里程碑跟踪执行）"},
    {"id": "capital-occupation-nonnegative", "desc": "资金占用各项(已付/应收未收/净占用)均非负"},
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
        "关联合同已立": bool(abox.get("contract_no")),
        "source_milestone 已确认产值（realizesReceivable）": True,  # 细则由 ABox 校验器后续加强
        "里程碑已立(且 level=major)": has_proj,
        "里程碑已立": has_proj,
        "父大里程碑(Milestone.level=major)已立": has_proj,
        "项目已立且成本预警状态 ∈ {预警, 超支}": abox.get("warning_raised") or False,
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
        impl = _FUNCTION_IMPLS.get(d.id)
        functions.register(d, impl=impl)
    for aid, spec in ACTIONS_PROJ.items():
        actions.register(Definition(
            id=aid, name=aid, kind="action", domain="project",
            description=spec.get("定义", ""),
            inputs=list(spec.get("条件", [])),
            invariant="; ".join(spec.get("不变量", [])) or None,
            version="0.4", ontology_bound=True,
            meta={"效果": spec.get("效果", ""), "幂等": spec.get("幂等", True)},
        ))


_register()
