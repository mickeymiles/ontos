# -*- coding: utf-8 -*-
"""业务 TBox 结构化 + 成本聚合 + 新增 Function + to_spec 测试（v5 项目为核心版）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ontos import domain_business as biz
from ontos.domain_business import (ENTITIES, LINKS, INVARIANTS, to_spec, cost_rollup,
                                   receivable_status)
from ontos.registry import functions


def test_entities_v6():
    # v6.1：4 主实体(商机/售前/合同/项目) + 交付链(里程碑/产值/订单/工单/任务/人)
    #       + 财经链(回款/付款/发票/保证金) + 预警 = 15
    names = set(ENTITIES.keys())
    assert names == {"Contract", "Project", "Milestone", "Receipt", "Payment", "Warning",
                     "Order", "WorkOrder", "Task", "Person", "Opportunity", "PreSales",
                     "OutputValue", "Invoice", "Deposit"}, names
    # 每个实体都有属性，且至少含唯一主键
    for name, e in ENTITIES.items():
        assert e.attributes, f"{name} 无属性"
        assert any(a.unique for a in e.attributes), f"{name} 缺唯一主键属性"


def test_links_v5():
    preds = {l["predicate"] for l in LINKS}
    for need in ["belongsTo", "hasMilestone", "hasOutputValue", "signedWith", "hasSubContract",
                 "hasWarning", "hasOrder", "hasWorkOrder", "hasTask", "assignedTo",
                 "hasInvoice", "hasReceipt", "hasPayment", "hasDeposit",
                 "hasPreSales", "winContract"]:
        assert need in preds, f"缺关系 {need}"
    # 已移除的旧关系不应存在
    for gone in ["realizesReceivable", "sourceMilestone", "sourcedFromContract", "executesAs"]:
        assert gone not in preds, f"不应存在旧关系 {gone}"


def test_ltc_mounts_v61():
    """LTC 绑定约束：里程碑/产值挂项目；财经(发票/回款/保证金/付款)挂合同；链路 商机→售前→合同→项目。"""
    by_pred = {l["predicate"]: l for l in LINKS}

    # 1) 财经全部挂【合同】，不挂项目
    assert by_pred["hasReceipt"]["subj"] == "Contract", by_pred["hasReceipt"]
    assert by_pred["hasPayment"]["subj"] == "Contract", by_pred["hasPayment"]
    assert by_pred["hasInvoice"]["subj"] == "Contract", by_pred["hasInvoice"]
    assert by_pred["hasDeposit"]["subj"] == "Contract", by_pred["hasDeposit"]
    assert ENTITIES["Receipt"].parent == "Contract"
    assert ENTITIES["Payment"].parent == "Contract"
    assert ENTITIES["Invoice"].parent == "Contract"
    assert ENTITIES["Deposit"].parent == "Contract"

    # 2) 项目不含财经关系；合同不含里程碑/产值
    p_rels = set(ENTITIES["Project"].relations)
    c_rels = set(ENTITIES["Contract"].relations)
    assert {"hasReceipt", "hasPayment", "hasInvoice", "hasDeposit"} & p_rels == set(), p_rels
    assert "hasMilestone" not in c_rels and "hasOutputValue" not in c_rels, c_rels
    assert {"hasReceipt", "hasPayment", "hasInvoice", "hasDeposit"} <= c_rels, c_rels

    # 3) 里程碑/产值挂【项目】
    assert ENTITIES["Milestone"].parent == "Project"
    assert ENTITIES["OutputValue"].parent == "Milestone"
    assert "hasOutputValue" in set(ENTITIES["Milestone"].relations)
    assert "sourcedFromContract" not in set(ENTITIES["Milestone"].relations)

    # 4) LTC 链路：商机→售前→合同→项目
    assert by_pred["hasPreSales"]["subj"] == "Opportunity"
    assert by_pred["hasPreSales"]["obj"] == "PreSales"
    assert by_pred["winContract"]["subj"] == "PreSales"
    assert by_pred["winContract"]["obj"] == "Contract"
    assert by_pred["belongsTo"]["subj"] == "Contract"
    assert by_pred["belongsTo"]["obj"] == "Project"

    # 5) 合同是财经根对象 + 凭证：须含 文本 / 是否归档 / 存放位置 / 签订时间 / 付款条款
    c_attrs = {a.name for a in ENTITIES["Contract"].attributes}
    assert {"doc_file", "archived", "storage_location", "sign_date", "payment_terms"} <= c_attrs, c_attrs

    # 6) 分包合同：Contract 自关系 + parent_contract_no
    assert by_pred["hasSubContract"]["subj"] == "Contract"
    assert by_pred["hasSubContract"]["obj"] == "Contract"
    assert "parent_contract_no" in c_attrs

    # 7) 语义护栏已固化
    inv_ids = {i["id"] for i in INVARIANTS}
    assert {"finance-on-contract", "milestone-value-on-project", "ltc-chain-order",
            "value-invoice-receipt-chain", "subcontract-parent-valid"} <= inv_ids, inv_ids
    print("[OK] LTC 绑定：里程碑/产值挂项目 · 财经(发票/回款/保证金/付款)挂合同 · 链路 商机→售前→合同→项目")


def test_cost_rollup_model():
    # 成本 = Σ付款 + Σ成本明细行（ABox 数据，非实体）
    payments = [{"amount": 60.0}, {"amount": 30.0}]
    rows = [{"amount": 8.0}, {"amount": 2.0}]
    out = cost_rollup(payments, rows)
    assert out["payment_sum"] == 90.0
    assert out["costitem_sum"] == 10.0
    assert out["current_cost"] == 100.0
    # 经注册表调用一致
    reg = functions.call("F-cost-rollup", payments=payments, cost_detail_rows=rows)
    assert reg == out


def test_spec_shape():
    spec = to_spec()
    assert "entities" in spec and "links" in spec
    assert len(spec["entities"]) == 15          # v6.1：4 主 + 交付链6 + 财经链4 + 预警
    # ★阈值策略与枚举由本体声明并导出（平台/智能体读取，不得自行硬编码）
    assert spec["policies"]["costWarning"]["warn_ratio"] == 0.9
    assert spec["policies"]["costWarning"]["overrun_ratio"] == 1.0
    assert spec["policies"]["costWarning"]["require_budget"] is True
    assert set(spec["enums"]["costWarningStatus"]) == {"正常", "预警", "超支"}
    assert spec["enums"]["statusToSeverity"] == {"预警": "预警", "超支": "严重"}
    # 兼容 9006 /spec 历史字段
    assert set(spec["concepts"].keys()) == set(ENTITIES.keys())
    assert len(spec["relations"]) == len(LINKS)
    # Function 含 6 个主场景函数 + 应收状态
    fids = {f["id"] for f in spec["functions"]}
    assert {"F-project-cost-warning", "F-cost-rollup", "F-capital-occupation",
            "F-project-roi", "F-project-margin", "F-payment-cycle",
            "F-receivable-status"} <= fids
    # Action 含 v6.1 集（财经动作前置改为「关联合同已立」；新增产值触发开票 applyInvoice）
    aids = {a["id"] for a in spec["actions"]}
    assert {"recordReceipt", "recordPayment", "confirmMilestoneValue", "applyInvoice",
            "completeMilestone", "raiseProjectCostWarning",
            "createSubContract"} <= aids
    # v6.1：财经动作(回款/付款)前置是「关联合同已立」而非「项目已立」
    acts = {a["id"]: a for a in spec["actions"]}
    for aid in ("recordReceipt", "recordPayment"):
        assert "关联合同已立" in acts[aid]["conditions"], acts[aid]["conditions"]


def test_new_functions():
    # 资金占用：已付80 + 应收未收60 = 占用140
    occ = functions.call("F-capital-occupation",
        payments=[{"paid_amount": 50.0}, {"paid_amount": 30.0}],
        receipts=[{"amount": 100.0, "received_amount": 40.0}])
    assert occ["paid_total"] == 80.0, occ
    assert occ["receivable_remain"] == 60.0, occ
    assert occ["occupied"] == 140.0, occ
    # ROI：(150-100)/100 = 0.5
    roi = functions.call("F-project-roi", revenue=150.0, current_cost=100.0)
    assert roi["roi"] == 0.5, roi
    # 毛利率：40/200 = 0.2
    gm = functions.call("F-project-margin", sign_amount=200.0, sign_gross_profit=40.0)
    assert gm["gross_rate"] == 0.2, gm
    # 回款周期：签约 2026-01-01 → 首笔回款 2026-03-15 = 73 天
    pc = functions.call("F-payment-cycle", sign_date="2026-01-01",
                        receipts=[{"received_date": "2026-03-15", "due_date": "2026-03-02"}])
    assert pc["cycle_days"] == 73, pc
    # 边界：合同额非正 → 毛利率 None
    assert functions.call("F-project-margin", sign_amount=0.0, sign_gross_profit=10.0)["gross_rate"] is None
    print("[OK] 新增 Function：资金占用/ROI/毛利率/回款周期 全部通过")


def test_receivable_lifecycle():
    # 里程碑确认产值 → 触发开票申请(挂合同, 2026-01-01) → 账期 60 天(到期 2026-03-02) → 部分回款
    inv = "2026-01-01"
    due = "2026-03-02"          # 开票日 + 60 天
    today = "2026-03-10"        # 已逾期 8 天
    r1 = receivable_status(invoice_date=inv, due_date=due, amount=100.0,
                           received_amount=40.0, received_date="2026-02-15", today=today)
    assert r1["status"] == "部分", r1
    assert r1["remain"] == 60.0, r1
    # 未回款且超期 → 逾期
    r2 = receivable_status(invoice_date=inv, due_date=due, amount=100.0,
                           received_amount=0.0, today=today)
    assert r2["status"] == "逾期", r2
    assert r2["overdue_days"] == 8, r2
    assert r2["aging_bucket"] == "61-90天", r2
    # 全额回款 → 已收
    r3 = receivable_status(invoice_date=inv, due_date=due, amount=100.0,
                           received_amount=100.0, received_date="2026-02-01", today=today)
    assert r3["status"] == "已收", r3
    # 未到账期未回款 → 待收
    r4 = receivable_status(invoice_date=inv, due_date=due, amount=100.0,
                           received_amount=0.0, today="2026-01-20")
    assert r4["status"] == "待收", r4
    # 经注册表调用一致
    reg = functions.call("F-receivable-status", invoice_date=inv, due_date=due,
                         amount=100.0, received_amount=0.0, today=today)
    assert reg == r2, reg
    # 实体属性：回款单挂合同，含来源项目/发票/账期/回款状态（无 source_milestone，改为 source_project_no）
    rec_attrs = {a.name for a in ENTITIES["Receipt"].attributes}
    assert {"source_project_no", "source_invoice_no", "invoice_no", "invoice_date", "due_date",
            "received_amount", "received_date", "status"} <= rec_attrs, rec_attrs
    assert "source_milestone" not in rec_attrs, rec_attrs
    # 里程碑只剩项目级属性；产值(value)已下放到 OutputValue 实体
    ms_attrs = {a.name for a in ENTITIES["Milestone"].attributes}
    assert "value" not in ms_attrs, ms_attrs
    assert {"level", "progress", "parent_ms"} & ms_attrs == set(), ms_attrs
    # 产值实体存在且含 value
    ov_attrs = {a.name for a in ENTITIES["OutputValue"].attributes}
    assert {"value", "report_date", "status"} <= ov_attrs, ov_attrs
    # 关系：里程碑→产值(hasOutputValue)；财经挂合同；LTC 链路关系存在
    preds = {l["predicate"] for l in LINKS}
    assert {"hasOutputValue", "hasInvoice", "hasReceipt", "hasPayment", "hasDeposit",
            "hasPreSales", "winContract", "hasOrder", "hasWorkOrder", "hasTask",
            "assignedTo"} <= preds
    assert {"realizesReceivable", "sourceMilestone", "sourcedFromContract",
            "executesAs"} & preds == set(), preds
    print("[OK] 应收/回款生命周期 + 里程碑项目级属性 + 产值实体 + LTC 关系 全部通过")


def test_cost_formula_functions():
    # 预算 = 100 + 50 + 30 = 180
    b = functions.call("F-project-budget", hw_integration_fee=100.0,
                      service_est_cost=50.0, sw_est_impl_fee=30.0)
    assert b["budget"] == 180.0, b
    # 成本 = 80 + 40 + 10 + 5 + 8 + 7 = 150
    c = functions.call("F-project-cost", hw_integration_actual=80.0, sw_impl_actual=40.0,
                      prior_svc_direct=10.0, prior_svc_indirect=5.0,
                      curr_svc_direct=8.0, curr_svc_indirect=7.0)
    assert c["cost"] == 150.0, c
    # 滞后剩余 = 180 - 150 = 30
    rem = functions.call("F-project-cost-remaining", budget=180.0, cost=150.0)
    assert rem["remaining_cost"] == 30.0, rem
    # 工单预估 = 20 + 5 + 3 + 2 = 30
    wo = functions.call("F-workorder-cost-rollup", workorders=[
        {"est_personnel": 20.0, "est_travel": 5.0, "est_flexible": 3.0, "est_variable": 2.0}])
    assert wo["wo_est_cost"] == 30.0, wo
    # 当前预估剩余 = 180 - 150 - 30 = 0
    cur = functions.call("F-project-current-remaining", budget=180.0, cost=150.0, wo_est_cost=30.0)
    assert cur["current_remaining_cost"] == 0.0, cur
    # 缺预算 → None（防误报）
    assert functions.call("F-project-cost-remaining", budget=None, cost=150.0)["remaining_cost"] is None
    # COST_FORMULA_POLICY 导出（★成本公式单一真相）
    spec = to_spec()
    assert "costFormula" in spec["policies"], spec["policies"].keys()
    assert spec["policies"]["costFormula"]["budget"]["formula"] == \
        "硬件集成费 + 服务预估成本 + 软件预估实施费"
    print("[OK] 成本双口径 Function：预算/成本/滞后剩余/工单预估/当前预估剩余 全部通过")


def test_entities_cn_names():
    # 全部 15 个实体必须有中文名（拓扑/页面显示，name 为稳定英文键）
    expected = {"Project": "项目", "Contract": "合同", "Milestone": "里程碑",
                "Receipt": "回款", "Payment": "付款", "Warning": "预警",
                "Order": "订单", "WorkOrder": "工单", "Task": "任务", "Person": "人员",
                "Opportunity": "商机", "PreSales": "售前", "OutputValue": "产值",
                "Invoice": "发票", "Deposit": "保证金"}
    for name, e in ENTITIES.items():
        assert e.cn, f"{name} 缺中文名"
        assert e.cn == expected.get(name), f"{name} 中文名应为 {expected.get(name)}，实得 {e.cn}"
    # to_spec 必须带 cn
    spec = to_spec()
    for ent in spec["entities"]:
        assert "cn" in ent and ent["cn"], ent
    print("[OK] 全部 15 实体均含正确中文名（cn）且 to_spec 导出")


if __name__ == "__main__":
    test_entities_v6()
    test_links_v5()
    test_ltc_mounts_v61()
    test_cost_rollup_model()
    test_spec_shape()
    test_new_functions()
    test_receivable_lifecycle()
    test_cost_formula_functions()
    test_entities_cn_names()
    print("ALL TBOX TESTS PASSED")
