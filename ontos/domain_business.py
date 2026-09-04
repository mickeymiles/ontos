# -*- coding: utf-8 -*-
"""通用业务本体地基（ontos · 场景收敛锁定版 v5 · 项目为核心 / 合同为过程凭证）。

这是「基于本体的智能体平台」的通用业务域骨架。本文件 = **TBox（定义层）** 的
单一真相源：实体 / 属性 / 关系 / Function / Action 的声明都写在这里（纯 Python，
不落库；运行期只读导出，见 to_spec()）。ABox（真实数据行）在 9006 的 SQLite。

═══ 核心铁则（LTC · 2026-09-04 用户拍板，★硬性绑定约束）═══
主业务时序链路：**商机 → 售前(投标) → 合同 → 项目(交付：自主/采购/分包)**。

- 里程碑、产值 → 归属【项目】实体，不和合同直接绑定（项目是交付进度的聚合根）。
- 财经类（发票、回款/收款、保证金、付款）→ 归属【合同】实体，不和项目直接绑定
  （**合同是所有财经动作的根对象**，只管钱、不管交付进度）；多项目对应同一合同时，
  回款统一对账到合同，再在项目间做成本/资金分摊。
- 投标方案、标书、应答文件、评标资料 → 归属【售前(投标)】实体（独立实体，非商机的附件）。
- 合同 Contract = **财经根对象 / 契约凭证**：发票/回款/保证金/付款全部挂合同；
  同时是交付的源头（一份合同拆分为多个交付项目）。
- 项目 Project = **交付执行聚合根**：里程碑、产值、成本、交付成果围绕项目组织，
  回答"交付得怎么样、成本超没超"。

═══ 场景收敛（与用户拍板）═══
当前覆盖 **5 个财务/经营分析场景**：
  回款周期 / 资金占用 / 项目毛利率 / 项目成本预警 / 项目 ROI。

关键定义决议（v6.1 · 2026-09-04 LTC 修正）：
- 实体（15）：4 主实体 商机/Opportunity、售前(投标)/PreSales、合同/Contract、项目/Project；
  交付链：Milestone(项目交付节点·产值计量) → OutputValue(产值记录)
    → Order(交付执行) → WorkOrder(工单·预估成本) → Task(任务·人执行) → Person(人员·费率)；
  财经链（挂合同）：Receipt(回款) / Payment(付款) / Invoice(发票) / Deposit(保证金)；
  预警事实：Warning(跨场景通用)。
  * ★子里程碑(sub-milestone)已移除：里程碑仅项目级（按付款节奏确定产值），
    执行拆解由 Order→WorkOrder→Task 承担。
  * 里程碑/产值 **挂项目**；发票/回款/保证金/付款 **挂合同**（财经根对象）。
  * 产值(项目) **触发** 开票申请（动作），开票结果落地【合同】——产值与发票是「触发」非「归属」关系。
  * 收款/付款是经营对象实体：里程碑确认产值 → 触发开票 → 账期 → 回款/付款（可分期、可逾期）。
- 成本双口径（详见 COST_FORMULA_POLICY，★单一真相）：
  * 滞后口径（主数据，lag≈1月）：预算 = 硬件集成费+服务预估成本+软件预估实施费；
    成本 = 硬件集成费实际+软件实际实施费+往年/当年服务直接/间接；剩余 = 预算−成本。
  * 当前预估口径（补滞后）：当前预估剩余 = 预算−成本−工单预估成本
    （Task×Person 费率后续替换工单预估人员成本）。
- 范围外实体仅占位，不进主 LINKS/ENTITIES 渲染（见 OUT_OF_SCOPE_* 注释）。

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
    cn: str = ""                                # 中文名（★拓扑/页面显示用；name 为稳定英文键，勿改）
    parent: Optional[str] = None                # child 的父实体
    desc: str = ""
    attributes: List[Attribute] = field(default_factory=list)
    relations: List[str] = field(default_factory=list)   # 关系谓词 key（见 LINKS）


# 实体定义（含结构化属性 + 来源字段映射）
ENTITIES: Dict[str, Entity] = {
    "Project": Entity(
        name="Project", cn="项目", kind="top",
        desc="项目（★交付执行聚合根：合同落地后的执行交付单元，支持自主/采购/分包三种模式）。"
             "里程碑、产值、交付成果围绕项目组织；财经(发票/回款/保证金/付款)不挂项目、统一归合同。"
             "★四算(概算/预算/核算/决算)亦不挂项目——宿主是合同下的 CostBaseline，项目只作分摊维度。",
        attributes=[
            Attribute("project_no", "string", True, True, "core_project.project_no", "项目编号"),
            Attribute("name", "string", True, False, "core_project.name", "项目名称"),
            Attribute("status", "enum", False, False, "core_project.status", "执行态：进行中/已完成/关闭"),
            Attribute("delivery_mode", "enum", False, False, "core_project.delivery_mode", "交付模式：自主实施/外购采购/分包"),
            # ── 四算属性（★DEPRECATED-待迁移）：宿主应为 Contract 下的 CostBaseline ──
            # 迁移时机：与成本预警切源同批。★此处保留属性本体，以维持 build_project_abox /
            # F-project-cost-warning 不回归；待 9006 成本预警改读 CostBaseline 后方可移除。
            # 概算是项目的属性（展示口径），★不参与成本预警判定，故不是 F-project-cost-warning 的入参
            Attribute("estimate", "number", False, False, "(主数据)=硬件预估成本+服务预估成本",
                      "概算(预估成本) ★DEPRECATED:权威源=CostBaseline(calc_type=概算)"),
            Attribute("budget", "number", False, False, "plm_baseline.total_cost",
                      "预算(概算/预算基线) ★DEPRECATED:权威源=CostBaseline(calc_type=基准预算)"),
            Attribute("current_cost", "number", False, False,
                      "(派生)=F-cost-rollup(ΣPayment+Σ成本明细行)",
                      "当前成本(派生属性；★唯一权威来源=F-cost-rollup，禁止调用方自行拼装)"
                      " ★DEPRECATED:权威源=CostBaseline(calc_type=核算)"),
            Attribute("start_date", "date", False, False, "core_project.start_date", "开始日期"),
            Attribute("end_date", "date", False, False, "core_project.end_date", "结束日期"),
        ],
        relations=["belongsTo_inv", "hasMilestone", "hasOrder", "hasWarning"],
    ),
    "Contract": Entity(
        name="Contract", cn="合同", kind="top",
        desc="合同（★财经根对象 / 契约凭证）。发票/回款/保证金/付款全部挂合同（只管钱、不管交付进度）；"
             "同时是交付源头（一份合同拆分为多个交付项目）。记录「签了什么、跟谁签、纸面在哪」。",
        attributes=[
            Attribute("contract_no", "string", True, True, "contract.contract_no", "合同号"),
            Attribute("name", "string", False, False, "contract.name", "合同名称(○待建列)"),
            Attribute("type", "enum", False, False, "contract.type", "主合同/分包合同/变更"),
            Attribute("parent_contract_no", "string", False, False, "contract.parent_contract_no",
                      "父合同号（分包合同指向主合同；主合同为空·○待建列）"),
            Attribute("amount", "number", False, False, "contract.sign_amount", "签约金额"),
            Attribute("sign_date", "date", False, False, "contract.sign_date", "签订时间"),
            Attribute("period", "number", False, False, "contract.period", "合同周期(月)"),
            Attribute("sign_gross_profit", "number", False, False, "contract.sign_gross_profit", "签单毛利(○待建列)"),
            Attribute("payment_terms", "string", False, False, "contract.payment_terms", "付款条款(○待建列)"),
            Attribute("warranty_terms", "string", False, False, "contract.warranty_terms", "质保条款(○待建列)"),
            Attribute("party_a", "string", False, False, "contract.party_a", "甲方(客户)"),
            Attribute("party_b", "string", False, False, "contract.party_b", "乙方(我方)"),
            Attribute("doc_file", "string", False, False, "contract.doc_file", "合同文本/扫描件(○待建列)"),
            Attribute("archived", "enum", False, False, "contract.archived", "是否归档：未归档/已归档(○待建列)"),
            Attribute("storage_location", "string", False, False, "contract.storage_location", "存放位置(○待建列)"),
        ],
        relations=["belongsTo", "hasSubContract", "signedWith", "hasWarning",
                   "hasReceipt", "hasPayment", "hasInvoice", "hasDeposit", "fromPreSales_inv"],
    ),
    "Milestone": Entity(
        name="Milestone", cn="里程碑", kind="child", parent="Project",
        desc="里程碑（★挂【项目】——交付节点，产值计量的依据，供 PMO 跟踪，与回款周期关联）。"
             "按合同付款节奏确定；★子里程碑已移除，本实体仅项目级里程碑。",
        attributes=[
            Attribute("ms_no", "string", True, True, "milestone.ms_no", "里程碑编号"),
            Attribute("name", "string", True, False, "milestone.name", "里程碑名称"),
            Attribute("plan_date", "date", False, False, "milestone.plan_date", "计划日期(付款节奏)"),
            Attribute("actual_date", "date", False, False, "milestone.actual_date", "实际日期"),
            Attribute("status", "enum", False, False, "milestone.status", "未开始/进行中/已完成/风险"),
            Attribute("acceptance", "string", False, False, "milestone.acceptance", "验收结论"),
        ],
        relations=["hasMilestone_inv", "hasOutputValue"],
    ),
    "Receipt": Entity(
        name="Receipt", cn="回款", kind="child", parent="Contract",
        desc="回款单（★挂【合同】——财经根对象的资金流入；实际到账资金，与合同应收对账；"
             "可分期、可逾期。由项目产值触发的开票申请落地为发票后，回款统一归合同）",
        attributes=[
            Attribute("receipt_no", "string", True, True, "finance_detail.receipt_no", "收款单号(○待建列)"),
            Attribute("source_project_no", "string", False, False, "finance_detail.source_project_no", "产值来源项目号(多项目对应一合同时用于分摊·○待建列)"),
            Attribute("source_invoice_no", "string", False, False, "finance_detail.source_invoice_no", "对应发票号(○待建列)"),
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
        relations=["hasReceipt_inv"],
    ),
    "Payment": Entity(
        name="Payment", cn="付款", kind="child", parent="Contract",
        desc="付款/应付单（★挂【合同】——财经根对象的资金流出；我方→供应商/分包，收票→账期→付款；"
             "可分期、可逾期；source_po ⌛待采购域）",
        attributes=[
            Attribute("payment_no", "string", True, True, "finance_detail.payment_no", "付款单号(○待建列)"),
            Attribute("source_po", "string", False, False, "finance_detail.source_po", "来源采购单(po_no·⌛待采购域接入)"),
            Attribute("source_project_no", "string", False, False, "finance_detail.source_project_no", "来源项目号(成本分摊·○待建列)"),
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
        relations=["hasPayment_inv"],
    ),
    "Warning": Entity(
        name="Warning", cn="预警", kind="child", parent=None,
        desc="预警（★跨场景通用事实载体：商机/合同/项目执行各类预警的统一收口）。"
             "由 Function 判定产出，具备独立编号与处理生命周期，可单独分派与闭环；"
             "经 subject_type+subject_no 与 hasWarning 关系指回主体（多态，故 parent=None）。",
        attributes=[
            Attribute("warning_no", "string", True, True, "", "预警编号（全局唯一·○待建列）"),
            Attribute("warning_type", "enum", True, False, "", "预警类型：成本超支/回款逾期/进度延期/合同到期/商机停滞"),
            Attribute("severity", "enum", True, False, "", "严重度：提醒/预警/严重"),
            Attribute("status", "enum", False, False, "", "处理生命周期：待处理/已确认/已处理/已关闭"),
            Attribute("subject_type", "string", True, False, "", "主体实体类型：Project/Contract/Opportunity"),
            Attribute("subject_no", "string", True, False, "", "主体编号（项目号/合同号/商机号）"),
            Attribute("metric_name", "string", False, False, "", "触发指标名（如 budget_ratio 预算完成比）"),
            Attribute("metric_value", "number", False, False, "", "触发时指标实际值"),
            Attribute("threshold", "number", False, False, "", "触发阈值（取本体声明策略值）"),
            Attribute("message", "string", False, False, "", "预警描述（可解释文案，供页面/智能体直接呈现）"),
            Attribute("source_function", "string", False, False, "", "产出本预警的 Function id（可追溯）"),
            Attribute("raised_at", "date", False, False, "", "产生时间"),
            Attribute("owner", "string", False, False, "", "处理责任人(○待定)"),
            Attribute("resolved_at", "date", False, False, "", "关闭时间(○待定)"),
        ],
        relations=["hasWarning_inv"],
    ),
    "Order": Entity(
        name="Order", cn="订单", kind="child", parent="Project",
        desc="订单（项目交付执行单元：项目的交付过程分解为订单，聚焦交付落地；"
             "与里程碑为项目下并行的「交付进度(PMO)」与「执行落地」两个视角）。",
        attributes=[
            Attribute("order_no", "string", True, True, "order.order_no", "订单编号"),
            Attribute("name", "string", True, False, "order.name", "订单名称"),
            Attribute("source_milestone", "string", False, False, "order.source_milestone", "关联里程碑(ms_no·可选)"),
            Attribute("status", "enum", False, False, "order.status", "未启动/执行中/已完成/验收"),
            Attribute("delivery_date", "date", False, False, "order.delivery_date", "交付日期"),
            Attribute("amount", "number", False, False, "order.amount", "订单金额(合同额分摊·○待建列)"),
        ],
        relations=["hasOrder_inv", "hasWorkOrder"],
    ),
    "WorkOrder": Entity(
        name="WorkOrder", cn="工单", kind="child", parent="Order",
        desc="工单（订单的细化分解；明确工单内容 + 预估成本四分项。初期人员成本由项目经理预估，"
             "后续由 Task×Person 费率替换）。",
        attributes=[
            Attribute("wo_no", "string", True, True, "work_order.wo_no", "工单编号"),
            Attribute("name", "string", True, False, "work_order.name", "工单名称/内容"),
            Attribute("status", "enum", False, False, "work_order.status", "待派/执行中/已完成"),
            Attribute("est_personnel", "number", False, False, "work_order.est_personnel", "预估人员投入成本(初期PM预估)"),
            Attribute("est_travel", "number", False, False, "work_order.est_travel", "预估差旅投入"),
            Attribute("est_flexible", "number", False, False, "work_order.est_flexible", "预估灵活用工投入"),
            Attribute("est_variable", "number", False, False, "work_order.est_variable", "预估变动费用"),
        ],
        relations=["hasWorkOrder_inv", "hasTask"],
    ),
    "Task": Entity(
        name="Task", cn="任务", kind="child", parent="WorkOrder",
        desc="任务（工单的分解，由人员执行；人员有费率可估算滞后成本）。"
             "★本期仅建实体、不参与成本计算（后续替换工单预估人员成本）。",
        attributes=[
            Attribute("task_no", "string", True, True, "task.task_no", "任务编号"),
            Attribute("name", "string", True, False, "task.name", "任务名称"),
            Attribute("assignee", "string", False, False, "task.assignee", "执行人(person_no)"),
            Attribute("est_hours", "number", False, False, "task.est_hours", "预估工时(后续×费率估算)"),
            Attribute("status", "enum", False, False, "task.status", "待办/进行中/完成"),
        ],
        relations=["hasTask_inv", "assignedTo"],
    ),
    "Person": Entity(
        name="Person", cn="人员", kind="top",
        desc="人员（资源/费率主数据；任务由其执行，费率用于后续估算滞后成本）。参考实体，parent=None。",
        attributes=[
            Attribute("person_no", "string", True, True, "person.person_no", "人员编号"),
            Attribute("name", "string", True, False, "person.name", "姓名"),
            Attribute("role", "string", False, False, "person.role", "角色/工种"),
            Attribute("rate", "number", False, False, "person.rate", "费率(元/工时·○待建列)"),
        ],
        relations=["assignedTo_inv"],
    ),
    # ── LTC 主实体：商机 / 售前(投标)（顶层，独立实体，非附件）──────────────────
    "Opportunity": Entity(
        name="Opportunity", cn="商机", kind="top",
        desc="商机（销售机会，线索转化而来；立项评估、预估收益）。一条商机可发起多轮投标。",
        attributes=[
            Attribute("opp_no", "string", True, True, "opportunity.opp_no", "商机编号"),
            Attribute("name", "string", True, False, "opportunity.name", "商机名称"),
            Attribute("customer", "string", False, False, "opportunity.customer", "客户"),
            Attribute("est_amount", "number", False, False, "opportunity.est_amount", "预估收益/商机金额"),
            Attribute("est_close_date", "date", False, False, "opportunity.est_close_date", "预估成交时间"),
            Attribute("win_prob", "number", False, False, "opportunity.win_prob", "赢单概率(0~1)"),
            Attribute("status", "enum", False, False, "opportunity.status", "跟进中/已中标/已丢单"),
        ],
        relations=["hasPreSales"],
    ),
    "PreSales": Entity(
        name="PreSales", cn="售前", kind="top",
        desc="售前(投标)（★独立实体，非商机附件；商机中标前的投标应答阶段）。"
             "支持同一商机多次投标版本管理；中标后生成一份合同。",
        attributes=[
            Attribute("presales_no", "string", True, True, "presales.presales_no", "投标编号"),
            Attribute("name", "string", True, False, "presales.name", "投标名称"),
            Attribute("bid_round", "number", False, False, "presales.bid_round", "投标轮次(同一商机可多次)"),
            Attribute("proposal", "string", False, False, "presales.proposal", "投标方案/标书"),
            Attribute("quote_list", "string", False, False, "presales.quote_list", "报价清单"),
            Attribute("bid_open_record", "string", False, False, "presales.bid_open_record", "开标记录"),
            Attribute("eval_result", "string", False, False, "presales.eval_result", "评标结果"),
            Attribute("award_notice", "string", False, False, "presales.award_notice", "中标通知书"),
            Attribute("bid_deposit_no", "string", False, False, "presales.bid_deposit_no", "投标保证金(前置关联·○待建列)"),
            Attribute("status", "enum", False, False, "presales.status", "投标中/已中标/未中标"),
        ],
        relations=["hasPreSales_inv", "winContract"],
    ),
    # ── 交付链附属：产值(OutputValue，挂项目·经里程碑) ────────────────────────
    "OutputValue": Entity(
        name="OutputValue", cn="产值", kind="child", parent="Milestone",
        desc="产值记录（★挂【项目·经里程碑】——阶段性完工计量值；产值≠开票金额，"
             "产值是业务进度，开票是财经动作。一个里程碑可多次产值调整）。",
        attributes=[
            Attribute("ov_no", "string", True, True, "output_value.ov_no", "产值记录编号"),
            Attribute("value", "number", False, False, "output_value.value", "产值计量值(合同额分摊·○待建列)"),
            Attribute("report_date", "date", False, False, "output_value.report_date", "报量日期"),
            Attribute("type", "enum", False, False, "output_value.type", "进度产值/变更产值"),
            Attribute("status", "enum", False, False, "output_value.status", "待审/已确认"),
        ],
        relations=["hasOutputValue_inv"],
    ),
    # ── 财经链附属：发票 / 保证金（挂合同） ─────────────────────────────────
    "Invoice": Entity(
        name="Invoice", cn="发票", kind="child", parent="Contract",
        desc="发票（★挂【合同】——财经根对象；可由项目产值触发开票申请，但发票本体归属合同）。",
        attributes=[
            Attribute("invoice_no", "string", True, True, "finance_detail.invoice_no", "发票号"),
            Attribute("amount", "number", False, False, "finance_detail.invoice_amount", "开票金额"),
            Attribute("invoice_date", "date", False, False, "finance_detail.invoice_date", "开票日"),
            Attribute("type", "enum", False, False, "finance_detail.invoice_type", "专票/普票"),
            Attribute("source_project_no", "string", False, False, "finance_detail.source_project_no", "产值触发来源项目(○待建列)"),
            Attribute("status", "enum", False, False, "finance_detail.invoice_status", "已开具/已作废"),
        ],
        relations=["hasInvoice_inv"],
    ),
    "Deposit": Entity(
        name="Deposit", cn="保证金", kind="child", parent="Contract",
        desc="保证金（★挂【合同】——财经根对象；投标保证金可前置关联售前，履约保证金归属合同）。",
        attributes=[
            Attribute("deposit_no", "string", True, True, "finance_detail.deposit_no", "保证金编号"),
            Attribute("type", "enum", False, False, "finance_detail.deposit_type", "投标保证金/履约保证金"),
            Attribute("amount", "number", False, False, "finance_detail.deposit_amount", "保证金金额"),
            Attribute("pay_date", "date", False, False, "finance_detail.deposit_pay_date", "缴纳日"),
            Attribute("status", "enum", False, False, "finance_detail.deposit_status", "已缴/已退/已结算"),
        ],
        relations=["hasDeposit_inv"],
    ),
    # ── 四算主线：成本基线（★挂【合同】——财经根对象；四算=本实体的四次实例化 + 版本链）──
    "CostBaseline": Entity(
        name="CostBaseline", cn="成本基线", kind="child", parent="Contract",
        desc="成本基线（★挂【合同】——财经根对象；四算=概算/基准预算/生产预算/核算/决算的统一承载）。"
             "每一次「算」产出一条基线记录，靠 calc_type + version 区分；★变更/超支升级出新版本，禁止覆盖。"
             "★产生地 ≠ 归集地：概算由商机产生、核算由项目产生，但归集锚一律是合同——"
             "否则「决算毛利率 ≥ 签单毛利率」这一一号可度量目标无法计算。"
             "注：ontos 的 kind 已被 top|child 占用，故四算类型字段命名为 calc_type。",
        attributes=[
            Attribute("baseline_no", "string", True, True, "cost_baseline.baseline_no", "基线编号(○待建表)"),
            Attribute("calc_type", "enum", True, False, "cost_baseline.calc_type",
                      "★四算类型：概算/基准预算/生产预算/核算/决算（候选值见模块常量 COST_BASELINE_CALC_TYPES）"),
            Attribute("contract_no", "string", False, False, "cost_baseline.contract_no",
                      "归集锚(合同号)；★概算期可空——此时合同尚未存在，Win 后回填（同 List 的双可空模式）"),
            Attribute("producer_type", "enum", True, False, "cost_baseline.producer_type",
                      "产生者类型：Opportunity/Contract/Project（★多态：产生地 ≠ 归集地）"),
            Attribute("producer_no", "string", True, False, "cost_baseline.producer_no",
                      "产生者编号（多态引用，与 producer_type 配对）"),
            Attribute("version", "number", True, False, "cost_baseline.version",
                      "同 calc_type 内递增；变更/预算升级出新版，旧版作废不覆盖"),
            Attribute("contract_amount", "number", False, False, "cost_baseline.contract_amount", "该版口径下的合同额"),
            Attribute("cost_breakdown", "string", False, False, "cost_baseline.cost_breakdown",
                      "成本三分量(硬件/软件/服务)，与 COST_FORMULA_POLICY 对齐"),
            Attribute("gross_profit", "number", False, False, "cost_baseline.gross_profit", "毛利"),
            Attribute("gross_margin", "number", False, False, "cost_baseline.gross_margin", "毛利率(%)"),
            Attribute("period", "string", False, False, "cost_baseline.period",
                      "生产预算专用：按里程碑/时间段拆解（★生产预算=行，待 CostBaselineLine 落地）"),
            Attribute("effective_from", "date", False, False, "cost_baseline.effective_from", "生效日"),
            Attribute("status", "enum", False, False, "cost_baseline.status",
                      "草稿/已锁定/已升级/已作废/已决算；★概算审批通过即锁定，不得擅自更改"),
        ],
        relations=["producesEstimate_inv", "producesBudget_inv", "producesAccounting_inv",
                   "supersedesBaseline", "decomposesToMilestone"],
    ),
}

# ── 四算类型枚举（CostBaseline.calc_type 的机器可读候选；9006 四算功能读本体取此）──
COST_BASELINE_CALC_TYPES = ("概算", "基准预算", "生产预算", "核算", "决算")
COST_BASELINE_CALC_TYPE_CN = {
    "概算": "概算（售前/立项，顶层管控基线）",
    "基准预算": "基准预算（合同级总量，可因变更/超支升级出 v2）",
    "生产预算": "生产预算（拆到里程碑+时间段，行级，待 CostBaselineLine 落地）",
    "核算": "核算（实际发生+未来预估，滚动 v1…vN）",
    "决算": "决算（关闭时终态，决算毛利率对标签单毛利率）",
}
# 哪些阶段参与成本/毛利计算（9006 本期全部参与；核算/决算虽有实际数但口径按业务逐步放开）
COST_BASELINE_CALCULATED = ("概算", "基准预算", "生产预算", "核算", "决算")


# 关系（Link）：主体.谓词(客体) [基数] 说明
LINKS: List[Dict[str, str]] = [
    # ── LTC 主链路：商机 → 售前(投标) → 合同 → 项目 ──
    {"predicate": "hasPreSales", "subj": "Opportunity", "obj": "PreSales", "card": "1:N",
     "desc": "商机发起投标（一次商机可多轮投标；反向：一次投标仅属一条商机）"},
    {"predicate": "winContract", "subj": "PreSales", "obj": "Contract", "card": "1:0..1",
     "desc": "投标中标 → 生成一份合同；未中标则无下游合同（一份合同仅来自一次成功投标）"},
    {"predicate": "belongsTo", "subj": "Contract", "obj": "Project", "card": "N:1",
     "desc": "合同归属项目（★合同拆分交付项目；一份合同→多个交付项目，一个交付项目仅属一份合同）"},
    {"predicate": "hasSubContract", "subj": "Contract", "obj": "Contract", "card": "1:N",
     "desc": "主合同 → 分包合同（自关系：分包合同经 parent_contract_no 指向主合同；分包合同亦归属同一项目）"},
    # ── 交付链：项目 → 里程碑 → 产值 → 订单 → 工单 → 任务 → 人 ──
    {"predicate": "hasMilestone", "subj": "Project", "obj": "Milestone", "card": "1:N",
     "desc": "项目交付里程碑节点（按付款节奏确定，产值计量依据；子里程碑已移除）"},
    {"predicate": "hasOutputValue", "subj": "Milestone", "obj": "OutputValue", "card": "1:N",
     "desc": "里程碑验收后报产值（一个里程碑可多次产值调整；产值是业务进度，非开票金额）"},
    {"predicate": "hasOrder", "subj": "Project", "obj": "Order", "card": "1:N",
     "desc": "项目交付订单（执行落地视图；与里程碑并为项目下「进度 vs 执行」双视角）"},
    {"predicate": "hasWorkOrder", "subj": "Order", "obj": "WorkOrder", "card": "1:N",
     "desc": "订单的工单分解（细化交付内容 + 预估成本）"},
    {"predicate": "hasTask", "subj": "WorkOrder", "obj": "Task", "card": "1:N",
     "desc": "工单的任务分解（由人员执行）"},
    {"predicate": "assignedTo", "subj": "Task", "obj": "Person", "card": "N:1",
     "desc": "任务指派给人员（人员费率用于估算滞后成本）"},
    # ── 财经链（★挂合同，合同是财经根对象）──
    {"predicate": "hasInvoice", "subj": "Contract", "obj": "Invoice", "card": "1:N",
     "desc": "合同发票（可由项目产值触发开票申请，但发票本体归属合同）"},
    {"predicate": "hasReceipt", "subj": "Contract", "obj": "Receipt", "card": "1:N",
     "desc": "★合同回款（客户→我方，实际到账，与合同应收对账；多项目对应一合同时统一归合同再做分摊）"},
    {"predicate": "hasPayment", "subj": "Contract", "obj": "Payment", "card": "1:N",
     "desc": "★合同付款（我方→供应商/分包，流出；收票→账期→付款）"},
    {"predicate": "hasDeposit", "subj": "Contract", "obj": "Deposit", "card": "1:N",
     "desc": "合同保证金（投标保证金可前置关联售前，履约保证金归属合同）"},
    {"predicate": "signedWith", "subj": "Contract", "obj": "Supplier", "card": "N:2",
     "desc": "合同签约方（甲方客户/乙方我方或供应商；⌛ Supplier 范围外，仅占位）"},
    # ── 预警（多态，指回主体）──
    {"predicate": "hasWarning", "subj": "Project", "obj": "Warning", "card": "1:N",
     "desc": "★项目预警（执行态类：成本超支/回款逾期/进度延期…由 Function 判定后写入）"},
    {"predicate": "hasWarning", "subj": "Contract", "obj": "Warning", "card": "1:N",
     "desc": "★合同预警（凭证类：合同到期/未归档…由对应 Function 判定后写入）"},
    {"predicate": "hasWarning", "subj": "Opportunity", "obj": "Warning", "card": "1:N",
     "desc": "★商机预警（线索类：商机停滞…由对应 Function 判定后写入）"},
    # ── 四算主线：成本基线（★产生地 ≠ 归集地；基线一律挂合同，项目只作分摊维度）──
    {"predicate": "producesEstimate", "subj": "Opportunity", "obj": "CostBaseline", "card": "1:N",
     "desc": "★商机(售前投标)产生【概算】：销售主导，审批通过后锁定、不得擅自更改；"
             "概算期 contract_no 为空，Win 后回填（此时合同才存在）"},
    {"predicate": "producesBudget", "subj": "Contract", "obj": "CostBaseline", "card": "1:N",
     "desc": "★合同产生【基准预算】与【决算】：基准预算=合同级总量(头)，触发于合同签订前/变更时/超支升级时；"
             "决算=完工或终止后由项目财经推进的终态基线"},
    {"predicate": "producesAccounting", "subj": "Project", "obj": "CostBaseline", "card": "1:N",
     "desc": "★项目产生【核算】：按「实际发生 + 未来预估」滚动计算，PM 确认成本归集、项目财经做盈亏分析与风险预警"},
    {"predicate": "supersedesBaseline", "subj": "CostBaseline", "obj": "CostBaseline", "card": "1:0..1",
     "desc": "★基线版本链（自关系）：合同变更 / 成本超支升级时出新版本，旧版置「已作废」★禁止覆盖，"
             "以保留「签单时的承诺 vs 现在的承诺」的可追溯性"},
    {"predicate": "decomposesToMilestone", "subj": "CostBaseline", "obj": "Milestone", "card": "1:N",
     "desc": "★生产预算=行：基准预算拆解到各里程碑 + 各时间段；"
             "⌛ 待 CostBaselineLine 实体落地（当前合同:项目=1:1，暂不需要分摊）"},
]

# ═══════════════════════════════════════════════════════════════════════
# 范围外占位（⌛ 本版不构建，仅记录以便后续收敛，不进 to_spec 主渲染）
# ═══════════════════════════════════════════════════════════════════════
# 范围外实体：Supplier(供应商) / Procurement(采购) / Quote(报价单)
#             / CostItem(成本明细·降级为 ABox 数据)。
# ★ 商机/Opportunity、售前/PreSales 已于 v6.1 升格为一级实体（LTC 主链路）。
# ★ Personnel(人员) 已于 v6 升格为 Person 实体（任务执行 + 费率估算）。
# 范围外关系（待对应场景补充时再加）：
#   hasProcurement(Project→Procurement) / placedWith(Procurement→Supplier)
#   payableFrom(Procurement→Payment) / sourceProcurement(Payment→Procurement)
#   hasCostItem(Project→CostItem) / answersInquiry(Quote→Procurement)
#   procuresAgainst(Procurement→Contract) / hasQuote(Opportunity→Quote)
#   managedBy(Project→Person) / hasMember(Project→Person)  # 后续项目-人员管理视角

# 兼容导出：供 9006 /spec 渲染器（历史字段名）
CONCEPTS = {name: e.desc for name, e in ENTITIES.items()}
RELATIONS = {f"{l['subj']}.{l['predicate']}({l['obj']})": l["desc"] for l in LINKS}


# ═══════════════════════════════════════════════════════════════════════
# Function：动力层·计算/判定（只读，不改事实）
# ═══════════════════════════════════════════════════════════════════════
# ── 成本预警·本体声明（★单一真相：阈值与规则语义在此显式声明，平台/智能体一律读取，
#    不得各自硬编码。修改阈值只需改本块，无需改任何实现代码）──────────────────
COST_WARNING_POLICY: Dict[str, Any] = {
    "metric": "budget_ratio",       # 判定指标：预算完成比 = 当前成本 / 预算
    "warn_ratio": 0.9,              # 预算完成比 ≥ 90%  → 判定「预警」
    "overrun_ratio": 1.0,           # 预算完成比 > 100% → 判定「超支」（严重）
    "require_budget": True,         # 缺有效预算(budget<=0/None)不得判定预警/超支 → 防误报
    "source_function": "F-project-cost-warning",
}
COST_WARNING_RATIO = COST_WARNING_POLICY["warn_ratio"]   # 兼容旧引用；新代码请用 POLICY
COST_WARNING_OVERRUN_RATIO = COST_WARNING_POLICY["overrun_ratio"]
# 判定状态枚举（Function 输出值，非实体）
COST_WARNING_STATUS: Tuple[str, ...] = ("正常", "预警", "超支")
# 预警严重度 / 处理生命周期 / 预警类型 枚举（Warning 实体属性取值域）
WARNING_SEVERITY: Tuple[str, ...] = ("提醒", "预警", "严重")
WARNING_LIFECYCLE: Tuple[str, ...] = ("待处理", "已确认", "已处理", "已关闭")
WARNING_TYPES: Tuple[str, ...] = ("成本超支", "回款逾期", "进度延期", "合同到期", "商机停滞")
# 判定状态 → 预警严重度 固定映射（仅非“正常”才产生 Warning 事实）
STATUS_TO_SEVERITY: Dict[str, str] = {"预警": "预警", "超支": "严重"}

# ── 成本公式·本体声明（★单一真相：预算/成本分量与物理列映射、滞后口径，平台/智能体一律读取）──
COST_FORMULA_POLICY: Dict[str, Any] = {
    "lag_months": 1,
    "lag_note": "主数据滞后约1个月：视图月 M 看到的是 M-2 月底快照（如 8 月看 6 月底、9 月看 7 月底）",
    "budget": {
        "formula": "硬件集成费 + 服务预估成本 + 软件预估实施费",
        "columns": {"hw_integration_fee": "硬件集成费", "service_est_cost": "服务预估成本",
                    "sw_est_impl_fee": "软件预估实施费"},
    },
    "cost": {
        "formula": "硬件集成费实际 + 软件实际实施费 + 往年服务直接/间接 + 当年服务直接/间接",
        "columns": {
            "hw_integration_actual": "硬件集成费实际", "sw_impl_actual": "软件实际实施费",
            "prior_svc_direct": "往年实际服务直接成本", "prior_svc_indirect": "往年实际服务间接成本",
            "curr_svc_direct": "当年实际服务直接成本", "curr_svc_indirect": "当年实际服务间接成本",
        },
    },
    "current_remaining": "预算 − 成本 − 工单预估成本(Σ工单 人员/差旅/灵活用工/变动)",
    "out_of_scope_columns": ["软件项目分包预估成本", "软件协力分包预估/实际成本", "服务协力分包预估/实际成本",
                            "往年/当年实际培训费用", "大区/事业部项目直接/间接成本"],
    "source_function": "F-project-budget / F-project-cost / F-project-current-remaining",
}
# 范围外类型（⌛ 待对应场景接入）：合同到期 / 商机停滞 / 回款逾期 / 进度延期 仅有类型占位


def cost_warning_rule(budget: Optional[float], current_cost: Optional[float],
                      wo_est_cost: Optional[float] = 0.0,
                      threshold: float = COST_WARNING_POLICY["warn_ratio"],
                      overrun_ratio: float = COST_WARNING_POLICY["overrun_ratio"]
                      ) -> Tuple[str, str]:
    """项目成本预警·纯语义规则（与 9006 _cost_status 逐字等价，已影子比对）。

    阈值缺省取本体声明 COST_WARNING_POLICY（★单一真相）。成本预警判定的是
    **有效成本 = 当前成本 + 工单预估成本(wo_est_cost)**，即「当前预估口径」：
    工单预估用于补主数据滞后缺口（见 COST_FORMULA_POLICY）。wo_est_cost 缺省 0 → 退化为滞后口径。

    入参：budget 预算（None/<=0 视为缺预算）；current_cost 当前成本（缺失按 0）；
          wo_est_cost 工单预估成本（缺失按 0）。
    返回：(status, note)；status ∈ COST_WARNING_STATUS = {正常, 预警, 超支}
    """
    b = budget if budget is not None else None
    c = (current_cost if current_cost is not None else 0.0) + (wo_est_cost if wo_est_cost is not None else 0.0)
    if b is None or b <= 0:
        if c > 0:
            return '正常', '缺预算，暂无法判定预警（有效成本 ¥%s）' % format(round(c), ',')
        return '正常', '缺预算且无有效成本，无法比较'
    ratio = c / b if b > 0 else None
    if ratio is not None and ratio > overrun_ratio:
        return '超支', '有效成本 ¥%s 已超过预算（超支 ¥%s）' % (
            format(round(c), ','), format(round(c - b), ','))
    if ratio is not None and ratio >= threshold:
        return '预警', '预算完成比已达 %d%%，接近预算上限' % round(ratio * 100)
    return '正常', '预算执行在阈值内（预算完成比 %d%%）' % (round(ratio * 100) if ratio is not None else 0)


def project_cost_warning(budget: Optional[float] = None,
                         current_cost: Optional[float] = None,
                         wo_est_cost: Optional[float] = None,
                         warn_ratio: Optional[float] = None,
                         overrun_ratio: Optional[float] = None) -> Dict[str, Any]:
    """Function F-project-cost-warning 实现：在 cost_warning_rule 之上补齐
    预算完成比 / 当前预估剩余成本 / 严重度，返回结构化结果。纯函数、无 IO。

    口径（★单一真相，见 COST_FORMULA_POLICY）：
    - 有效成本 = current_cost + wo_est_cost（工单预估补主数据滞后）。
    - 当前预估剩余成本 = budget - current_cost - wo_est_cost。
    阈值缺省取本体声明 COST_WARNING_POLICY；显式传入则用于假设分析。

    ★入参约定：
    - 概算 estimate **不是本函数入参**——概算只是 Project 的展示属性，不参与预警判定。
    - current_cost 的权威来源是 F-cost-rollup；wo_est_cost 的权威来源是 F-workorder-cost-rollup。
      两者均可在缺省(0)时退化为滞后口径，保证向后兼容。
    """
    c = float(current_cost) if current_cost is not None else 0.0
    woe = float(wo_est_cost) if wo_est_cost is not None else 0.0
    b = float(budget) if budget is not None else None
    w = float(warn_ratio) if warn_ratio is not None else COST_WARNING_POLICY["warn_ratio"]
    o = float(overrun_ratio) if overrun_ratio is not None else COST_WARNING_POLICY["overrun_ratio"]
    effective = c + woe
    status, note = cost_warning_rule(b, c, wo_est_cost=woe, threshold=w, overrun_ratio=o)
    ratio = round(effective / b, 4) if (b is not None and b > 0) else None
    remaining = round(b - c - woe, 2) if (b is not None and c is not None) else None
    return {
        'status': status, 'note': note, 'budget': b,
        'current_cost': c, 'wo_est_cost': woe, 'effective_cost': round(effective, 2),
        'budget_ratio': ratio, 'remaining_cost': remaining,
        # ── 供 raiseProjectCostWarning 写 Warning 实体（预警事实）所需字段 ──
        'severity': STATUS_TO_SEVERITY.get(status),      # 正常 → None（不产生预警事实）
        'threshold': w, 'overrun_ratio': o,
        'metric_name': COST_WARNING_POLICY["metric"],
        'source_function': COST_WARNING_POLICY["source_function"],
        'policy': dict(COST_WARNING_POLICY),             # 回显本体声明，便于审计/页面标注
    }


def project_cost_warning_from_ledger(budget: Optional[float] = None,
                                     payments: Optional[List[Dict[str, Any]]] = None,
                                     cost_detail_rows: Optional[List[Dict[str, Any]]] = None,
                                     warn_ratio: Optional[float] = None,
                                     overrun_ratio: Optional[float] = None) -> Dict[str, Any]:
    """组合函数 F-project-cost-warning-from-ledger：成本聚合 → 成本预警判定，一步出结果。

    ★本体声明「F-project-cost-warning.depends_on = F-cost-rollup」的可执行落地：
    本函数强制 current_cost 由 F-cost-rollup 产出（Σ付款 + Σ成本明细行），
    杜绝调用方各自拼装导致的「当前成本」口径漂移
    （此前平台用 Σ已付款、PLM 用四算 actual_cum、本体说 Σ付款+明细，三套并存）。

    纯函数、无 IO。返回 F-project-cost-warning 全量字段 + cost_breakdown 成本构成明细。
    """
    roll = cost_rollup(payments or [], cost_detail_rows or [])
    res = project_cost_warning(budget=budget, current_cost=roll["current_cost"],
                               warn_ratio=warn_ratio, overrun_ratio=overrun_ratio)
    res["cost_breakdown"] = {
        "payment_sum": roll["payment_sum"],
        "costitem_sum": roll["costitem_sum"],
        "source_function": "F-cost-rollup",
    }
    return res


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


def payment_cycle(sign_date: Optional[str] = None, receipts: Optional[List[Dict[str, Any]]] = None,
                  basis: str = "last", recv_source: Optional[str] = None) -> Dict[str, Any]:
    """Function F-payment-cycle 实现：回款周期 = 合同签订日 → 回款日。

    ★ 口径对齐 9006 现网（project_metrics.payment_cycle）：
      回款周期 = **最后一笔**回款日 − 合同签订日（basis='last'，默认）。
      现网 ETL 亦为「最后一笔」；本函数额外支持 basis='first'（首笔回款速度）供分析。

    输入：sign_date 合同签订日；receipts 回款单列表（取 received_date / due_date）；
          basis ∈ {last, first}；recv_source 回款时间的来源标记（由 ABox 层传入，
          仅作可追溯标记不参与计算：plm_milestone / finance_detail / maindata）。
    输出：cycle_days, recv_date(实际采用), first/last_recv_date, recv_count, basis, recv_source。
    缺数据：sign_date 或回款日缺失 → cycle_days=None（现网口径为 NaN + 说明）。
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

    if basis not in ("last", "first"):
        basis = "last"
    sd = _parse(sign_date)
    recvs = receipts or []
    recv_dates = sorted(d for d in (_parse(r.get("received_date")) for r in recvs) if d)
    if not recv_dates:
        picked = None
    elif basis == "first":
        picked = recv_dates[0]
    else:
        picked = recv_dates[-1]
    cycle_days = (picked - sd).days if (sd and picked) else None
    due_dates = [d for d in (_parse(r.get("due_date")) for r in recvs) if d]
    due = min(due_dates) if due_dates else None

    note = ""
    if sd is None:
        note = "NaN：缺合同签订时间（sign_date）"
    elif picked is None:
        note = "NaN：无任何有效回款记录"
    elif cycle_days is not None and cycle_days < 0:
        note = "异常：回款日早于合同签订日，请核查 sign_date 与回款日期"

    return {
        "cycle_days": cycle_days,
        "sign_date": sign_date,
        "recv_date": picked.isoformat() if picked else None,
        "first_recv_date": recv_dates[0].isoformat() if recv_dates else None,
        "last_recv_date": recv_dates[-1].isoformat() if recv_dates else None,
        "due_date": due.isoformat() if due else None,
        "recv_count": len(recv_dates),
        "basis": basis,
        "recv_source": recv_source,
        "note": note,
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


# ── 成本双口径·本体声明实现（★单一真相，分量物理列见 COST_FORMULA_POLICY）──────────
def project_budget(hw_integration_fee: float = 0.0, service_est_cost: float = 0.0,
                   sw_est_impl_fee: float = 0.0) -> Dict[str, Any]:
    """Function F-project-budget 实现：预算 = 硬件集成费 + 服务预估成本 + 软件预估实施费。

    分量物理列见 COST_FORMULA_POLICY.budget.columns（★单一真相）。纯函数、无 IO。
    """
    b = round(float(hw_integration_fee) + float(service_est_cost) + float(sw_est_impl_fee), 2)
    return {
        "budget": b,
        "breakdown": {
            "hw_integration_fee": round(float(hw_integration_fee), 2),
            "service_est_cost": round(float(service_est_cost), 2),
            "sw_est_impl_fee": round(float(sw_est_impl_fee), 2),
        },
        "source_function": "F-project-budget",
    }


def project_cost(hw_integration_actual: float = 0.0, sw_impl_actual: float = 0.0,
                prior_svc_direct: float = 0.0, prior_svc_indirect: float = 0.0,
                curr_svc_direct: float = 0.0, curr_svc_indirect: float = 0.0) -> Dict[str, Any]:
    """Function F-project-cost 实现：成本 = 硬件集成费实际 + 软件实际实施费
    + 往年服务直接/间接 + 当年服务直接/间接（主数据，滞后约1月，见 COST_FORMULA_POLICY）。

    纯函数、无 IO。
    """
    cost = round(float(hw_integration_actual) + float(sw_impl_actual)
                + float(prior_svc_direct) + float(prior_svc_indirect)
                + float(curr_svc_direct) + float(curr_svc_indirect), 2)
    return {
        "cost": cost,
        "breakdown": {
            "hw_integration_actual": round(float(hw_integration_actual), 2),
            "sw_impl_actual": round(float(sw_impl_actual), 2),
            "prior_svc_direct": round(float(prior_svc_direct), 2),
            "prior_svc_indirect": round(float(prior_svc_indirect), 2),
            "curr_svc_direct": round(float(curr_svc_direct), 2),
            "curr_svc_indirect": round(float(curr_svc_indirect), 2),
        },
        "source_function": "F-project-cost",
    }


def project_cost_remaining(budget: Optional[float] = None, cost: float = 0.0) -> Dict[str, Any]:
    """Function F-project-cost-remaining 实现：滞后剩余成本 = 预算 − 成本（主数据快照口径）。

    缺有效预算(budget<=0/None) → remaining_cost=None（防误报）。纯函数、无 IO。
    """
    b = float(budget) if budget is not None else None
    c = float(cost) if cost is not None else 0.0
    remaining = round(b - c, 2) if (b is not None and b > 0) else None
    return {"budget": b, "cost": c, "remaining_cost": remaining,
            "source_function": "F-project-cost-remaining"}


def workorder_cost_rollup(workorders: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Function F-workorder-cost-rollup 实现：工单预估成本 = Σ工单(人员+差旅+灵活用工+变动)。

    用于补主数据滞后缺口；初期工单人员成本由项目经理预估，后续可由 Task×Person 费率替换。
    纯函数、无 IO。
    """
    wos = workorders or []
    est = round(sum(float(wo.get(k) or 0) for wo in wos
                   for k in ("est_personnel", "est_travel", "est_flexible", "est_variable")), 2)
    return {"wo_est_cost": est, "count": len(wos), "source_function": "F-workorder-cost-rollup"}


def project_current_remaining(budget: Optional[float] = None, cost: float = 0.0,
                              wo_est_cost: float = 0.0) -> Dict[str, Any]:
    """Function F-project-current-remaining 实现：当前预估剩余成本 = 预算 − 成本 − 工单预估成本。

    即在滞后口径上叠加执行侧工单预估，反映更及时的真实剩余。缺有效预算 → None。纯函数、无 IO。
    """
    b = float(budget) if budget is not None else None
    c = float(cost) if cost is not None else 0.0
    woe = float(wo_est_cost) if wo_est_cost is not None else 0.0
    remaining = round(b - c - woe, 2) if (b is not None and b > 0) else None
    return {"budget": b, "cost": c, "wo_est_cost": woe, "current_remaining_cost": remaining,
            "source_function": "F-project-current-remaining"}


# ═══════════════════════════════════════════════════════════════════════
# 计算分发器：供 9006 / demo 共用，确保"算法只在 ontos 一份"
# ═══════════════════════════════════════════════════════════════════════
import inspect as _inspect


def _norm_fn_key(name: str) -> str:
    """归一化函数名：去掉前缀 F-、连字符转下划线（payment_cycle / F-payment-cycle 等价）。"""
    s = str(name or "").strip()
    if s.startswith("F-"):
        s = s[2:]
    return s.replace("-", "_")


# 对外暴露的计算函数（纯函数、无 IO）。键同时支持 "payment_cycle" 与 "F-payment-cycle" 两种命名。
_COMPUTE_FUNCS = {
    "payment_cycle": payment_cycle,
    "F-payment-cycle": payment_cycle,
    "capital_occupation": capital_occupation,
    "F-capital-occupation": capital_occupation,
    "project_margin": project_margin,
    "F-project-margin": project_margin,
    "project_roi": project_roi,
    "F-project-roi": project_roi,
    "cost_rollup": cost_rollup,
    "F-cost-rollup": cost_rollup,
    "project_budget": project_budget,
    "F-project-budget": project_budget,
    "project_cost": project_cost,
    "F-project-cost": project_cost,
    "project_cost_remaining": project_cost_remaining,
    "F-project-cost-remaining": project_cost_remaining,
    "workorder_cost_rollup": workorder_cost_rollup,
    "F-workorder-cost-rollup": workorder_cost_rollup,
    "project_current_remaining": project_current_remaining,
    "F-project-current-remaining": project_current_remaining,
    "receivable_status": receivable_status,
    "F-receivable-status": receivable_status,
    "project_cost_warning": project_cost_warning,
    "F-project-cost-warning": project_cost_warning,
    "project_cost_warning_from_ledger": project_cost_warning_from_ledger,
    "F-project-cost-warning-from-ledger": project_cost_warning_from_ledger,
}
_COMPUTE_FUNCS_NORM = {_norm_fn_key(k): v for k, v in _COMPUTE_FUNCS.items()}


def list_compute_functions() -> list:
    """列出所有可计算函数（含参数与说明），供 UI / agent 发现。"""
    seen = set()
    out = []
    for fn in _COMPUTE_FUNCS_NORM.values():
        if fn in seen:
            continue
        seen.add(fn)
        sig = _inspect.signature(fn)
        params = []
        for pname, p in sig.parameters.items():
            if pname == "return":
                continue
            params.append({
                "name": pname,
                "required": p.default is _inspect.Parameter.empty,
                "default": None if p.default is _inspect.Parameter.empty else p.default,
                "annotation": (str(p.annotation).replace("typing.", "")
                               if p.annotation is not _inspect.Parameter.empty else "Any"),
            })
        out.append({
            "id": fn.__name__,
            "fid": "F-" + fn.__name__.replace("_", "-"),
            "doc": (fn.__doc__ or "").strip().split("\n")[0],
            "params": params,
        })
    return out


def dispatch(function: str, params: dict = None) -> dict:
    """统一计算分发：入参 = 函数名(或 F-xxx) + 参数字典，返回该函数计算结果。

    - 函数名缺失/未知 → {'success': False, 'error': 'unknown_function', ...}
    - 参数缺失/类型错误 → {'success': False, 'error': 'param_error', ...}（不抛 500）
    - 成功 → {'success': True, 'function': <名>, 'result': <原函数返回值>}
    """
    if not function:
        return {"success": False, "error": "missing_function",
                "message": "未提供 function 名称"}
    fn = _COMPUTE_FUNCS_NORM.get(_norm_fn_key(function))
    if fn is None:
        return {"success": False, "error": "unknown_function",
                "message": f"未知计算函数：{function}",
                "available": [f["id"] for f in list_compute_functions()]}
    params = params or {}
    if not isinstance(params, dict):
        return {"success": False, "error": "param_error",
                "message": "params 必须是对象/字典"}
    try:
        result = fn(**params)
    except TypeError as e:
        return {"success": False, "error": "param_error",
                "message": f"参数不匹配：{e}",
                "signature": str(_inspect.signature(fn))}
    except Exception as e:  # 业务纯函数不应抛，但兜底
        return {"success": False, "error": "compute_error",
                "message": f"{type(e).__name__}: {e}"}
    return {"success": True, "function": fn.__name__, "result": result}


_FUNCTION_DEFS: List[Definition] = [
    Definition(
        id="F-payment-cycle", name="回款周期", kind="function", domain="financial", category="周期", produces_for=['Contract', 'Project'],
        description="回款周期 = 回款日 − 合同签订日。basis='last'(★默认，对齐 9006 现网口径："
                    "最后一笔回款) 或 'first'(首笔回款速度)。缺 sign_date 或无有效回款 → "
                    "cycle_days=None（现网为 NaN + 说明）；回款日早于签约日标记异常。",
        inputs=["sign_date", "receipts", "basis", "recv_source"],
        outputs=["cycle_days", "recv_date", "first_recv_date", "last_recv_date",
                 "recv_count", "due_date", "basis", "recv_source", "note"],
        invariant="sign_date 与回款日均有效时 cycle_days=(recv_date-sign_date).days；"
                  "回款日早于签约日须标记异常而非静默归零",
        version="0.5", ontology_bound=True,
    ),
    Definition(
        id="F-receivable-status", name="应收/回款状态", kind="function", domain="financial", category="状态判定", produces_for=['Receipt'],
        description="基于 开票日/到期日/应收金额/已回款 判定 待收/部分/已收/逾期，并给出账龄区间与逾期天数。",
        inputs=["invoice_date", "due_date", "amount", "received_amount", "received_date", "today"],
        outputs=["status", "remain", "overdue_days", "aging_days", "aging_bucket"],
        invariant="remain = amount - received_amount and remain>=0", version="0.5", ontology_bound=True,
    ),
    Definition(
        id="F-capital-occupation", name="资金占用", kind="function", domain="financial", category="资金占用", produces_for=['Contract', 'Project'],
        description="资金占用 = Σ已付(Payment.paid_amount) + Σ应收未收(Receipt.amount-received_amount)。",
        inputs=["payments", "receipts"],
        outputs=["occupied", "paid_total", "receivable_remain", "net"],
        invariant="occupied = paid_total + receivable_remain and all>=0", version="0.5", ontology_bound=True,
    ),
    Definition(
        id="F-project-margin", name="项目毛利率", kind="function", domain="financial", category="比率", produces_for=['Contract', 'Project'],
        description="项目/合同毛利率 = 签单毛利 / 合同额。",
        inputs=["sign_amount", "sign_gross_profit"],
        outputs=["gross_rate", "sign_amount", "sign_gross_profit"],
        invariant="sign_amount>0 implies gross_rate=sign_gross_profit/sign_amount",
        version="0.5", ontology_bound=True,
    ),
    Definition(
        id="F-project-cost-warning", name="项目成本预警", kind="function", domain="financial", category="预警", produces_for=['Project'],
        description="依据 预算 与 当前成本 计算预算完成比(budget_ratio=current_cost/budget)，"
                    "按本体声明阈值(COST_WARNING_POLICY)给出 正常/预警/超支 判定状态。"
                    "★阈值与规则语义由本体声明，调用方不得自行硬编码；需试算其他阈值时"
                    "用 warn_ratio/overrun_ratio 入参覆盖，不改本体声明。",
        inputs=["budget", "current_cost", "warn_ratio", "overrun_ratio"],
        outputs=["status", "severity", "note", "budget_ratio", "remaining_cost",
                 "threshold", "overrun_ratio", "metric_name", "source_function", "policy"],
        # ★不变量按「有无有效预算」分述，避免 self-contradiction
        invariant="current_cost>=0; "
                  "budget 缺失或非正时 status=正常（require_budget，防误报）; "
                  "budget>0 时：budget_ratio=current_cost/budget，"
                  "status=超支 iff budget_ratio>overrun_ratio，"
                  "status=预警 iff warn_ratio<=budget_ratio<=overrun_ratio",
        version="0.8", ontology_bound=True,
        meta={"policy": COST_WARNING_POLICY, "status_enum": COST_WARNING_STATUS,
              "severity_map": STATUS_TO_SEVERITY,
              # ★声明依赖：current_cost 的权威来源，禁止调用方自行拼装
              "depends_on": ["F-cost-rollup", "F-workorder-cost-rollup"],
              "current_cost_source": "F-cost-rollup",
              "wo_est_cost_source": "F-workorder-cost-rollup",
              "current_remaining": "budget - current_cost - wo_est_cost（见 COST_FORMULA_POLICY）",
              "composite": "F-project-cost-warning-from-ledger"},
    ),
    Definition(
        id="F-cost-rollup", name="项目成本聚合", kind="function", domain="financial", category="聚合", produces_for=['Project'],
        description="项目当前成本 = Σ付款(Payment) + Σ成本明细行(ABox，人工/其他/预提)。",
        inputs=["payments", "cost_detail_rows"], outputs=["current_cost", "payment_sum", "costitem_sum"],
        invariant="current_cost = payment_sum + costitem_sum and all>=0", version="0.5", ontology_bound=True,
    ),
    Definition(
        id="F-project-cost-warning-from-ledger", name="项目成本预警(从台账)", kind="function",
        domain="financial", category="组合", produces_for=['Project'],
        description="组合函数：先经 F-cost-rollup 由付款/成本明细聚合出当前成本，"
                    "再交由 F-project-cost-warning 判定。★成本口径的唯一入口，"
                    "调用方不得自行拼装 current_cost（此前平台/PLM/本体三套口径并存）。",
        inputs=["budget", "payments", "cost_detail_rows", "warn_ratio", "overrun_ratio"],
        outputs=["status", "severity", "note", "budget_ratio", "remaining_cost",
                 "threshold", "metric_name", "source_function", "policy", "cost_breakdown"],
        invariant="current_cost = F-cost-rollup(payments, cost_detail_rows).current_cost; "
                  "判定语义与 F-project-cost-warning 完全一致（同一阈值策略）",
        version="0.7", ontology_bound=True,
        meta={"composes": ["F-cost-rollup", "F-project-cost-warning"],
              "policy": COST_WARNING_POLICY},
    ),
    Definition(
        id="F-project-roi", name="项目ROI", kind="function", domain="financial", category="比率", produces_for=['Project'],
        description="项目 ROI = (收益 - 当前成本) / 当前成本；收益取回款总额或合同额。",
        inputs=["revenue", "current_cost"], outputs=["roi", "revenue", "current_cost"],
        invariant="current_cost>0 implies roi=(revenue-current_cost)/current_cost",
        version="0.5", ontology_bound=True,
    ),
    Definition(
        id="F-project-budget", name="项目预算", kind="function", domain="financial", category="聚合", produces_for=['Project'],
        description="预算 = 硬件集成费 + 服务预估成本 + 软件预估实施费（主数据，滞后约1月，见 COST_FORMULA_POLICY）。",
        inputs=["hw_integration_fee", "service_est_cost", "sw_est_impl_fee"],
        outputs=["budget", "breakdown", "source_function"],
        invariant="budget = hw_integration_fee + service_est_cost + sw_est_impl_fee",
        version="0.1", ontology_bound=True, meta={"policy": COST_FORMULA_POLICY},
    ),
    Definition(
        id="F-project-cost", name="项目成本", kind="function", domain="financial", category="聚合", produces_for=['Project'],
        description="成本 = 硬件集成费实际 + 软件实际实施费 + 往年服务直接/间接 + 当年服务直接/间接"
                    "（主数据，滞后约1月，见 COST_FORMULA_POLICY）。",
        inputs=["hw_integration_actual", "sw_impl_actual", "prior_svc_direct", "prior_svc_indirect",
                "curr_svc_direct", "curr_svc_indirect"],
        outputs=["cost", "breakdown", "source_function"],
        invariant="cost = hw_integration_actual + sw_impl_actual + prior_svc_direct + prior_svc_indirect"
                  " + curr_svc_direct + curr_svc_indirect",
        version="0.1", ontology_bound=True, meta={"policy": COST_FORMULA_POLICY},
    ),
    Definition(
        id="F-project-cost-remaining", name="滞后剩余成本", kind="function", domain="financial", category="派生", produces_for=['Project'],
        description="滞后剩余成本 = 预算 − 成本（主数据快照口径，未叠加工单预估）。",
        inputs=["budget", "cost"], outputs=["budget", "cost", "remaining_cost", "source_function"],
        invariant="remaining_cost = budget - cost (budget>0)", version="0.1", ontology_bound=True,
    ),
    Definition(
        id="F-workorder-cost-rollup", name="工单预估成本汇总", kind="function", domain="financial", category="聚合", produces_for=['Project'],
        description="工单预估成本 = Σ工单(人员投入+差旅+灵活用工+变动费用)；用于补主数据滞后缺口。"
                    "初期人员成本由项目经理预估，后续可由 Task×Person 费率替换。",
        inputs=["workorders"], outputs=["wo_est_cost", "count", "source_function"],
        invariant="wo_est_cost = Σ(est_personnel+est_travel+est_flexible+est_variable) and >=0",
        version="0.1", ontology_bound=True,
    ),
    Definition(
        id="F-project-current-remaining", name="当前预估剩余成本", kind="function", domain="financial", category="派生", produces_for=['Project'],
        description="当前预估剩余成本 = 预算 − 成本 − 工单预估成本（叠加执行侧工单预估，反映更及时真实剩余）。",
        inputs=["budget", "cost", "wo_est_cost"],
        outputs=["budget", "cost", "wo_est_cost", "current_remaining_cost", "source_function"],
        invariant="current_remaining_cost = budget - cost - wo_est_cost (budget>0)",
        version="0.1", ontology_bound=True, meta={"policy": COST_FORMULA_POLICY},
    ),
]

# 声明 + 实现绑定（单一真相，平台/智能体共享）
_FUNCTION_IMPLS = {
    "F-payment-cycle": payment_cycle,
    "F-receivable-status": receivable_status,
    "F-capital-occupation": capital_occupation,
    "F-project-margin": project_margin,
    "F-project-cost-warning": project_cost_warning,
    "F-project-cost-warning-from-ledger": project_cost_warning_from_ledger,
    "F-cost-rollup": cost_rollup,
    "F-project-roi": project_roi,
    "F-project-budget": project_budget,
    "F-project-cost": project_cost,
    "F-project-cost-remaining": project_cost_remaining,
    "F-workorder-cost-rollup": workorder_cost_rollup,
    "F-project-current-remaining": project_current_remaining,
}


# ═══════════════════════════════════════════════════════════════════════
# Action：动力层·变更（写回，受约束 + 不变量 + 审计 + S1–S5）
# ═══════════════════════════════════════════════════════════════════════
ACTIONS_PROJ = {
    "recordReceipt": {
        "定义": "记录一笔回款（客户→我方，流入；实际到账，与合同应收对账）。★挂【合同】（财经根对象），"
                "经 source_project_no 关联产值来源项目以便多项目分摊。",
        "条件": ["关联合同已立", "对应发票已开具（invoice-before-receipt）"],
        "效果": "新增 Receipt（挂合同；含 source_project_no/source_invoice_no/发票/账期/received_amount），"
                "建立 hasReceipt(Contract→Receipt)。",
        "不变量": ["receipt_no 全局唯一", "amount>=0", "received_amount<=amount", "invoiced=已开票 方可回款"], "幂等": True, "分类": "财经入账", "指向": ['Contract', 'Receipt'],
    },
    "recordPayment": {
        "定义": "记录一笔付款（我方→供应商/分包，流出；含开票/账期/已付；source_po ⌛待采购域）。★挂【合同】（财经根对象）。",
        "条件": ["关联合同已立"],
        "效果": "新增 Payment（挂合同；含 source_project_no/发票/账期/paid_amount），建立 hasPayment(Contract→Payment)。",
        "不变量": ["payment_no 全局唯一", "amount>=0", "paid_amount<=amount"], "幂等": True, "分类": "财经入账", "指向": ['Contract', 'Payment'],
    },
    "createSubContract": {
        "定义": "在主合同下签订分包合同（过程凭证：记录分包契约与归档信息；不直接产生收付款）。",
        "条件": ["主合同已立"],
        "效果": "新增 Contract(type=分包合同, parent_contract_no=主合同号)，建立 hasSubContract(主→分包)。",
        "不变量": ["contract_no 全局唯一", "parent_contract_no 必须指向已存在的合同",
                 "不得自引用（合同不能是自己的父合同）", "分包合同仍须 belongsTo 某项目"], "幂等": True, "分类": "结构变更", "指向": ['Contract'],
    },
    "confirmMilestoneValue": {
        "定义": "里程碑达成（初验）后报产值（OutputValue），建立 hasOutputValue(Milestone→OutputValue) 关系。",
        "条件": ["里程碑已立", "验收结论已填（acceptance）", "产值 value>=0"],
        "效果": "新增 OutputValue（挂项目·经里程碑；含 value/report_date/type/status）；"
                "建立 hasOutputValue(Milestone→OutputValue)。★产值≠开票，仅业务进度计量。",
        "不变量": ["value>=0", "未确认产值不得触发开票申请"], "幂等": True, "分类": "交付履约", "指向": ['Milestone', 'OutputValue'],
    },
    "applyInvoice": {
        "定义": "由项目产值达标触发开票申请，落地为合同发票（Invoice）。★产值(项目)与发票(合同)是「触发」非「归属」关系。",
        "条件": ["关联合同已立", "存在已确认产值(OutputValue.status=已确认)", "开票金额>0"],
        "效果": "新增 Invoice（挂合同；含 amount/invoice_date/source_project_no），建立 hasInvoice(Contract→Invoice)；"
                "回款经 recordReceipt 统一归合同后再按 source_project_no 分摊。",
        "不变量": ["invoice_no 全局唯一", "amount>0", "发票本体归属合同、不挂项目", "同一产值仅可触发一次开票申请"], "幂等": True, "分类": "财经入账", "指向": ['Contract', 'Invoice'],
    },
    "completeMilestone": {
        "定义": "标记里程碑完成（含实际日期/验收结论）。",
        "条件": ["里程碑已立"],
        "效果": "更新 Milestone.status=已完成 + actual_date + acceptance。",
        "不变量": ["actual_date 不早于 plan_date(软约束，可标注延期)"], "幂等": True, "分类": "交付履约", "指向": ['Milestone'],
    },
    "raiseProjectCostWarning": {
        "定义": "当成本预警判定状态为 预警/超支 时，写一条 Warning 事实"
                "（warning_type=成本超支，subject=项目）。★判定由 F-project-cost-warning 产出，"
                "本动作只负责把判定结果落成可跟踪、可闭环的预警事实。",
        "条件": ["项目已立", "成本预警状态 ∈ {预警, 超支}"],
        "效果": "新增 Warning(warning_type=成本超支, severity=预警|严重, subject_type=Project, "
                "subject_no=项目号, metric_name=budget_ratio, metric_value=预算完成比, "
                "threshold=本体声明阈值, message=判定文案, "
                "source_function=F-project-cost-warning)；建立 hasWarning(Project→Warning)。",
        "不变量": ["仅在判定状态非 正常 时写预警",
                 "severity 与 status 固定映射（预警→预警，超支→严重）",
                 "缺有效预算不得写预警（require_budget）",
                 "warning_no 全局唯一",
                 "同主体+同类型+同状态 按周期去重"], "幂等": True, "分类": "预警闭环", "指向": ['Project', 'Warning'],
    },
    # ── 四算主线动作（★宿主=合同下的 CostBaseline）──────────────────────────
    "LockBaseline": {
        "定义": "锁定一条成本基线（★对应业务口径「概算审批通过后不得擅自更改」）。"
                "概算由销售主导、在投标报价阶段产生，审批通过即置「已锁定」，此后任何改动须出新版本、禁止覆盖。",
        "条件": [],  # ⌛校验器待 CostBaseline 的 ABox 构建器落地后补齐（与成本预警切源同批）
        "效果": "更新 CostBaseline.status=已锁定；此后该版本只读。",
        "不变量": ["已锁定基线不得直接修改（须经 supersedesBaseline 出新版本）",
                 "同 calc_type 内 version 单调递增"], "幂等": True, "分类": "四算基线", "指向": ['CostBaseline'],
    },
    "UpgradeBudget": {
        "定义": "★成本超支 → 预算升级：当成本预警判定为「超支」时，重编预算并出新版本"
                "（对应业务「成本超支导致预算升级时」这一预算触发条件）。"
                "★接在 raiseProjectCostWarning 之后，补齐「核算 → 预算」的反向闭环。",
        "条件": ["成本预警状态 ∈ {预警, 超支}"],
        "效果": "新增 CostBaseline(calc_type=基准预算, version=旧版+1)，旧版置「已升级」；"
                "建立 supersedesBaseline(新版→旧版)。",
        "不变量": ["旧版禁止覆盖，只可置「已升级」", "新版 version = 旧版 + 1",
                 "升级须可追溯到触发它的预警事实"], "幂等": True, "分类": "四算基线", "指向": ['CostBaseline'],
    },
    "Finalize": {
        "定义": "★决算：项目完工或终止后，由项目财经推进，产出全生命周期的终态基线并复盘。"
                "可度量目标：决算毛利率 ≥ 签单毛利率。",
        "条件": [],  # ⌛同上，待 CostBaseline ABox 构建器落地
        "效果": "新增 CostBaseline(calc_type=决算, status=已决算)，"
                "含全生命周期合同/回款/标准成本/财务成本/毛利。",
        "不变量": ["决算为终态，不得再出新版本",
                 "须可与概算基线比对（决算毛利率 vs 签单毛利率）"],
        "幂等": True, "分类": "四算基线", "指向": ['Contract', 'CostBaseline'],
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
    {"id": "value-invoice-receipt-chain", "desc": "★产值(项目/里程碑)触发开票申请→发票(挂合同)→回款(挂合同)；"
                                               "产值与发票是「触发」非「归属」关系，发票/回款本体一律归属合同，不得挂项目"},
    {"id": "invoice-before-receipt", "desc": "回款/付款须先开票(invoiced=已开票)，账期自开票日起算，到期未回为逾期"},
    {"id": "received-not-exceed-amount", "desc": "已回款/已付金额不得大于应收/应付金额"},
    {"id": "no-sub-milestone", "desc": "★子里程碑已移除：里程碑仅项目级（按付款节奏确定产值），执行拆解由 Order→WorkOrder→Task 承担"},
    {"id": "finance-on-contract", "desc": "★财经根对象=合同：发票/回款/保证金/付款全部挂合同（只管钱、不管交付进度）；"
                                         "多项目对应同一合同时回款统一对账到合同，再在项目间做成本/资金分摊"},
    {"id": "milestone-value-on-project", "desc": "★里程碑与产值挂项目（交付进度聚合根），不和合同直接绑定；"
                                               "合同只管财经，不承载交付进度"},
    {"id": "capital-occupation-nonnegative", "desc": "资金占用各项(已付/应收未收/净占用)均非负"},
    {"id": "ltc-chain-order", "desc": "★主业务时序：商机→售前(投标)→合同→项目(自主/采购/分包)；"
                                     "投标文档属独立售前实体（非商机附件）；未中标无下游合同"},
    {"id": "subcontract-parent-valid", "desc": "分包合同须经 hasSubContract 指向已存在的主合同，且不得自引用"},
]


# ═══════════════════════════════════════════════════════════════════════
# ABox：从记录构造事实三元组（纯函数，无 DB 副作用）
# ═══════════════════════════════════════════════════════════════════════
def build_project_abox(project: Dict[str, Any]) -> Dict[str, Any]:
    """将项目记录(dict)转换为语义事实表(ABox)，供校验器使用。纯函数。"""
    meta = project.get("meta") or {}
    # 成本预警判定状态：由本体函数现算（★不可由调用方伪造），供 Action 前置校验
    _st, _note = cost_warning_rule(project.get("budget"), project.get("current_cost"))
    return {
        "project_no": project.get("project_no"),
        "status": project.get("status") or "active",
        "contract_no": project.get("contract_no") or meta.get("contract_no"),
        "budget": project.get("budget"),
        "current_cost": project.get("current_cost"),
        "cost_status": _st,
        "cost_note": _note,
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
        # LTC v6.1：里程碑/产值挂项目、财经(发票/回款)挂合同；动作前置按主体区分
        "项目已立": has_proj,
        "关联项目已立": has_proj,
        "关联合同已立": bool(abox.get("contract_no")),   # 兼容历史条件串
        "主合同已立": bool(abox.get("contract_no")),     # createSubContract 前置
        "存在已确认产值（OutputValue.status=已确认）": True,  # 细则由 ABox 校验器后续加强
        "里程碑已立": has_proj,
        "里程碑已立(且 level=major)": has_proj,
        "父大里程碑(Milestone.level=major)已立": has_proj,
        # ★判定状态由本体函数现算，调用方无法伪造（修复此前条件串不匹配导致的护栏空转）
        "成本预警状态 ∈ {预警, 超支}": abox.get("cost_status") in ("预警", "超支"),
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
             "effects": s["效果"], "invariants": s["不变量"], "idempotent": s["幂等"],
             "category": s.get("分类", ""), "targets": s.get("指向", [])}
            for aid, s in ACTIONS_PROJ.items()
        ],
        "invariants": INVARIANTS,
        # ── 本体声明的阈值策略与枚举（★单一真相：平台/智能体一律读取，不得自行硬编码）──
        "policies": {"costWarning": COST_WARNING_POLICY, "costFormula": COST_FORMULA_POLICY},
        "enums": {
            "costWarningStatus": COST_WARNING_STATUS,
            "warningSeverity": WARNING_SEVERITY,
            "warningLifecycle": WARNING_LIFECYCLE,
            "warningTypes": WARNING_TYPES,
            "statusToSeverity": STATUS_TO_SEVERITY,
        },
        "entities": [
            {
                "name": e.name, "cn": e.cn, "kind": e.kind, "parent": e.parent, "desc": e.desc,
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
            category=spec.get("分类", ""), targets=list(spec.get("指向", [])),
            description=spec.get("定义", ""),
            inputs=list(spec.get("条件", [])),
            invariant="; ".join(spec.get("不变量", [])) or None,
            version="0.5", ontology_bound=True,
            meta={"效果": spec.get("效果", ""), "幂等": spec.get("幂等", True)},
        ))


_register()
