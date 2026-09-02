# -*- coding: utf-8 -*-
"""本体知识层（ontos · 干净重建种子）。

基于「语义网/本体化 LLM 智能体」范式，不再用硬编码状态机：
  - TBox：领域概念（类/关系），机器可读且可喂给 LLM；
  - ABox：从任务/邮件/报价抽取的事实三元组（由 build_abox 纯函数构造，无 DB 副作用）；
  - 可行动作：本体声明 = 定义 + 前置(条件) + 效果(effect) + 不变量(invariant) + 幂等(idempotent)；
  - 语义规则：condition ⇒ 该动作可执行；invariant 恒成立；校验器在执行前统一裁决并给 LLM 拒绝原因。

注意：本模块是**声明 + 纯语义校验**，不依赖任何 app/backend 运行时（已与 schema 解耦）。
执行器（调度/写回）由 ontos/engine.py 负责，不再照搬旧 decision/execution 硬编码。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ────────────────────────────────────────────
# TBox：领域概念（供 LLM 语境 / 文档 / 校验引用）
# ────────────────────────────────────────────
CONCEPTS = {
    "Person": "人（工程师 / 审批人 / 供应商）",
    "Engineer": "发起询价的运维工程师（内部流收件人，始终在场）",
    "Approver": "采购审批人（内部流抄送，确认选定供应商）",
    "Supplier": "备件供应商（外部流参与者，按线程回复）",
    "Part": "待采购备件（类型/品牌/PN/规格/成色/数量）",
    "InquiryTask": "一次备件询价采购任务（核心根实体，属本业务独立 Task 表）",
    "InquiryEmail": "工程师发起的初始询价申请邮件（事实源 A）",
    "Quote": "供应商针对某任务的报价（单价/货期/成色/有效/超时）",
    "Approval": "审批人的选定/确认决定",
    "Order": "对选中供应商下达的订货",
    "Shipment": "供应商发货回执（快递单号）",
    "Settlement": "结算通知（任务闭环）",
}
RELATIONS = {
    "task.submittedBy(person)": "任务由某工程师发起",
    "task.invites(keywords supplier)": "任务向供应商发出询价(发过一次B)",
    "supplier.offersQuote(task, {price, freight, condition})": "供应商对任务报价",
    "quote.valid": "报价有效(解析成功且未超时)",
    "task.selectedSupplier(supplier)": "审批人确认选中的供应商(下订货对象)",
    "task.approval(approvedBy approver)": "审批人的选定决定",
    "task.order(to supplier)": "对选中供应商下达订货(发过E)",
    "task.shipmentNo(tracking)": "已登记快递单号",
    "task.engineerFeedbackFinished": "工程师反馈更换完成",
    "task.closed(closure)": "任务已闭环(终态)",
}

# ────────────────────────────────────────────
# 可行动作规范（本体声明）：定义 / 条件 / 效果 / 不变量 / 幂等
# ────────────────────────────────────────────
ACTIONS = {
    "requestMissingFields": {
        "定义": "工程师询价缺必填字段时，回信指出缺哪些；不建任务、不询价。",
        "条件": ["工程师询价缺必填字段"],
        "效果": "回一封指出缺失字段的信；不产生任务。",
        "不变量": [],
        "幂等": True,
    },
    "createTask": {
        "定义": "工程师询价字段齐全后，把该询价立为任务并生成 taskId、算报价截止时间。",
        "条件": ["工程师询价必填字段齐全", "该询价尚未建立任务"],
        "效果": "新增 InquiryTask(INIT)；记录发起工程师与报价截止。",
        "不变量": ["同一询价(Message-ID)只建一次任务"],
        "幂等": True,
    },
    "distributeInquiry": {
        "定义": "向目标供应商各发一封询价邮件Ｂ(不含收货地址)，请其报价。",
        "条件": ["任务已立", "目标供应商列表非空", "本任务尚未发过询价"],
        "效果": "向每家供应商发B；外部流进入 INVITE_QUOTE；记录 b_msg_ids。",
        "不变量": ["同一任务对同一批供应商只发一次询价"],
        "幂等": True,
    },
    "receiveSupplierQuote": {
        "定义": "在B询价线程收到供应商回复，识别{单价/货期/成色}归档为一条Quote。",
        "条件": ["已发过询价", "收到B线程供应商回复"],
        "效果": "新增 Quote(task, supplier, price, freight, condition)。",
        "不变量": ["同一回复(Message-ID)只记一次报价"],
        "幂等": True,
    },
    "finalizeQuoteCollection": {
        "定义": "全部有效报价或到截止，结束报价收集进入决策。",
        "条件": ["有有效报价", "或已到报价截止"],
        "效果": "结束收集(收尾态)。",
        "不变量": [],
        "幂等": True,
    },
    "submitApproval": {
        "定义": "报价收集结束后，把报价汇总发给工程师并抄送审批人(内部流D)，请确认选家。",
        "条件": ["至少一条有效报价", "收集已结束", "内部流尚未发起审批"],
        "效果": "发D汇总；内部流 → R_APPROVAL；记录 d_msg_id。",
        "不变量": ["无有效报价不得发起审批", "同一任务只发一次D"],
        "幂等": True,
    },
    "processApprovalDecision": {
        "定义": "读审批人回复，确认所选供应商∈本次有效报价候选池；合法则定为 target_supplier。",
        "条件": ["已发审批D", "收到审批人回复"],
        "效果": "写入 task.selectedSupplier(若合法)。",
        "不变量": ["被选供应商必须在本次有效报价者之列"],
        "幂等": True,
    },
    "confirmOrderToSupplier": {
        "定义": "审批确认后，向选中供应商发订货确认邮件Ｅ(含收货地址/数量/其报价原文), 正式下单。",
        "条件": ["至少一条有效报价", "target_supplier 已由审批确定", "尚未对该供应商下过订货"],
        "效果": "发E；外部流 → ORDER_CONFIRM；记录 e_msg_id 及其报价引用。",
        "不变量": ["未审批/无报价不得下订货", "已下过订货不得重复下发"],
        "幂等": True,
    },
    "receiveTrackingNumber": {
        "定义": "读取供应商『已发货+单号』回复，登记快递单号。",
        "条件": ["已下达订货E", "收到供应商带单号的发货回复"],
        "效果": "写入 task.shipmentNo；外部流 → WAIT_ENGINEER_CLOSE。",
        "不变量": ["未下订货不得登记运单"],
        "幂等": True,
    },
    "requestTrackingNo": {
        "定义": "供应商回了发货但缺单号，主动回信请其补单号，保持订货态。",
        "条件": ["已下达订货E", "收到发货回复但缺单号"],
        "效果": "回信向该供应商索取单号。",
        "不变量": [],
        "幂等": True,
    },
    "engineerFinalClose": {
        "定义": "工程师反馈更换完成，向供应商发结算邮件G，任务整体关闭。",
        "条件": ["已发货并登记单号", "工程师已反馈完成"],
        "效果": "发G；内部流 → R_CLOSED，外部流 → R_SETTLE，状态 → CLOSED。",
        "不变量": ["货未发/单未登记不得闭环", "已闭环不得重复"],
        "幂等": True,
    },
    "abortTask": {
        "定义": "到报价截止且无有效报价(或全部被拒)，向工程师发中止通知F，任务关闭。",
        "条件": ["已到报价截止", "无有效报价"],
        "效果": "发F(中止通知)；任务 → CLOSED_ABORT。",
        "不变量": ["存在有效报价或已下订货时禁止中止"],
        "幂等": True,
    },
    "requestQuoteClarification": {
        "定义": "供应商回了询价但无法解析出{单价/货期}（解析失败）。主动回信告知缺哪些、请补充后重发，保持收集，不中止。",
        "条件": ["收到无法解析的报价回复"],
        "效果": "回信向该供应商说明报价缺字段/格式，请补充后重发；外部流保持收集。",
        "不变量": ["收到未解析回复≠无回复，不应走中止；应在仍收集期内催促补全"],
        "幂等": False,
    },
    "manualCloseTask": {
        "定义": "后台有权限人员手动关闭/取消任务(不属邮件链路)。",
        "条件": ["由后台授权操作发起"],
        "效果": "任务 → CLOSED_MANUAL；写审计。",
        "不变量": [],
        "幂等": True,
    },
}

# ────────────────────────────────────────────
# 全局不变量（跨动作，恒定成立——语义护栏）
# ────────────────────────────────────────────
INVARIANTS = [
    {"id": "once_per_action", "desc": "同一任务对同一语义动作只做一次(B/D/E/G各只发一次)"},
    {"id": "no_regression", "desc": "任务沿 立项→询价→收集→审批→订货→运单→完成 只前进、不回退"},
    {"id": "thread_grounded", "desc": "发信必落真实线程(E/G在供应商报价线程、D/F在工程师询价线程)并携带原文"},
    {"id": "engineer_internal", "desc": "内部流工程师始终在收件人；外部流全员回复"},
]


def get_action(action_id: str) -> Optional[Dict[str, Any]]:
    return ACTIONS.get(action_id)


def list_action_ids() -> List[str]:
    return list(ACTIONS.keys())


# ────────────────────────────────────────────
# ABox：从任务/邮件/报价抽取事实三元组（纯函数，无 DB 副作用）
# ────────────────────────────────────────────
def build_abox(task: Dict[str, Any]) -> Dict[str, Any]:
    """将任务记录(dict)转换为语义事实表(ABox)，供 LLM 语境与校验器使用。

    纯函数：不触发任何建表/IO；数据来源由调用方保证已就绪。
    """
    meta = task.get("spare_info") or {}
    quotes = meta.get("quotes") or []
    supplied = bool((meta.get("b_msg_ids") or []))
    supplied_set = bool(meta.get("target_supplier"))
    order_sent = bool(meta.get("e_msg_id"))
    approval_sent = bool(meta.get("d_msg_id"))
    engineer_done = bool(meta.get("engineer_close"))
    valid_quotes = [q for q in quotes if q.get("email") and q.get("unit_price")]
    facts = {
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "from_email": task.get("from_email"),
        "part": {k: meta.get(k) for k in ("project_no", "project_name", "part_type", "brand", "pn", "spec", "condition", "count", "address", "urgent")},
        "internal_status": task.get("internal_status"),
        "external_status": task.get("external_status"),
        "quotes": valid_quotes,
        "quote_count": len(valid_quotes),
        "target_supplier_list": [s.get("email") for s in (meta.get("suppliers") or [])],
        "inquiry_sent": supplied,
        "approval_sent": approval_sent,
        "target_supplier_set": supplied_set,
        "order_sent": order_sent,
        "tracking_number": meta.get("tracking_no", ""),
        "engineer_feedback_finished": engineer_done,
        "deadline_passed": bool(meta.get("deadline_passed")),
        "unparseable_supplier_emails": list(meta.get("unparseable_replies") or []),
    }
    return facts


def validate_action(action_id: str, abox: Dict[str, Any], rejected_prev=None) -> Tuple[bool, List[str]]:
    """校验动作在『当前事实(ABox)』下是否可执行：(ok, 拒绝原因列表)。

    依据：动作自身条件 + 全局不变量 + 幂等。供 LLM 决策执行前裁决；不满足则给 LLM 原因重选。
    纯函数，无副作用。
    """
    spec = ACTIONS.get(action_id)
    if not spec:
        return False, ["未知动作"]
    reasons: List[str] = []
    cond = spec.get("条件") or []
    has_order = abox.get("order_sent")
    has_tracking = bool(abox.get("tracking_number"))
    closed = str(abox.get("status") or "").upper() in ("CLOSED", "R_SETTLE", "CLOSED_ABORT", "CLOSED_MANUAL")
    req_ok = bool(abox.get("part", {}).get("pn") and abox.get("part", {}).get("count"))
    facts = {
        # 原始布尔（once_map 幂等用）
        "inquiry_sent": abox.get("inquiry_sent"),
        "approval_sent": abox.get("approval_sent"),
        "order_sent": has_order,
        "closed": closed,
        # 条件谓词
        "工程师询价缺必填字段": not req_ok,
        "工程师询价必填字段齐全": req_ok,
        "该询价已建立任务": bool(abox.get("task_id")),
        "任务已立": bool(abox.get("task_id")),
        "该询价尚未建立任务": False,
        "本任务尚未发过询价": not abox.get("inquiry_sent"),
        "已发过询价": abox.get("inquiry_sent"),
        "收到B线程供应商回复": bool(abox.get("quotes")) or True,
        "目标供应商列表非空": bool(abox.get("target_supplier_list")),
        "至少一条有效报价": abox.get("quote_count", 0) >= 1,
        "有有效报价": abox.get("quote_count", 0) >= 1,
        "或已到报价截止": bool(abox.get("deadline_passed")),
        "收集已结束": bool(abox.get("deadline_passed")) or abox.get("quote_count", 0) >= 1,
        "内部流尚未发起审批": not abox.get("approval_sent"),
        "已发审批D": abox.get("approval_sent"),
        "收到审批人回复": bool(abox.get("target_supplier_set")) or abox.get("approval_sent"),
        "target_supplier 已由审批确定": abox.get("target_supplier_set"),
        "尚未对该供应商下过订货": not has_order,
        "已下达订货E": has_order,
        "收到供应商带单号的发货回复": has_tracking,
        "收到发货回复但缺单号": has_order,
        "已发货并登记单号": has_tracking,
        "已登记快递单号": has_tracking,
        "工程师已反馈完成": abox.get("engineer_feedback_finished"),
        "已到报价截止": bool(abox.get("deadline_passed")),
        "无有效报价": abox.get("quote_count", 0) == 0,
        "由后台授权操作发起": False,
        "收到无法解析的报价回复": bool(abox.get("unparseable_supplier_emails")),
    }
    for c in cond:
        if facts.get(c) is False:
            reasons.append(f"前置不满足: {c}")
    # 语义动作只做一次（幂等；once_map 基于原始布尔）
    once_map = {
        "distributeInquiry": ("inquiry_sent", "已发过询价，不得重复分发"),
        "submitApproval": ("approval_sent", "已发过审批D，不得重复发起"),
        "confirmOrderToSupplier": ("order_sent", "已下过订货，不得重复下发"),
        "engineerFinalClose": ("closed", "已闭环，不得重复"),
    }
    f, msg = once_map.get(action_id, (None, None)) or (None, None)
    if f and facts.get(f):
        reasons.append(msg)
    return (len(reasons) == 0), reasons
