# -*- coding: utf-8 -*-
"""业务 TBox 结构化 + 成本聚合 + to_spec 测试。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ontos import domain_business as biz
from ontos.domain_business import ENTITIES, LINKS, to_spec, cost_rollup, receivable_status
from ontos.registry import functions


def test_entities_structured():
    # 5 顶层 + 5 子实体
    tops = [n for n, e in ENTITIES.items() if e.kind == "top"]
    children = [n for n, e in ENTITIES.items() if e.kind == "child"]
    assert set(tops) == {"Opportunity", "Contract", "Project", "Personnel", "Supplier"}, tops
    assert set(children) == {"Procurement", "Milestone", "Receipt", "Payment", "CostItem"}, children
    # 每个实体都有属性，且至少含唯一主键
    for name, e in ENTITIES.items():
        assert e.attributes, f"{name} 无属性"
        uniq = [a for a in e.attributes if a.unique]
        assert uniq, f"{name} 缺少唯一主键属性"


def test_links_cardinality():
    preds = {l["predicate"] for l in LINKS}
    for need in ["realizes", "belongsTo", "managedBy", "hasProcurement",
                 "placedWith", "hasMilestone", "hasReceipt", "hasPayment",
                 "hasCostItem", "signedWith", "hasMember", "ownedBy"]:
        assert need in preds, f"缺关系 {need}"


def test_cost_rollup_model():
    # 成本 = Σ付款 + Σ成本明细（人工/其他）
    payments = [{"amount": 60.0}, {"amount": 30.0}]
    items = [{"amount": 8.0, "category": "人工"}, {"amount": 2.0, "category": "其他"}]
    out = cost_rollup(payments, items)
    assert out["payment_sum"] == 90.0
    assert out["costitem_sum"] == 10.0
    assert out["current_cost"] == 100.0
    # 经注册表调用一致
    reg = functions.call("F-cost-rollup", payments=payments, cost_items=items)
    assert reg == out


def test_spec_shape():
    spec = to_spec()
    assert "entities" in spec and "links" in spec
    assert len(spec["entities"]) == 10
    # 兼容 9006 /spec 历史字段
    assert set(spec["concepts"].keys()) == set(ENTITIES.keys())
    assert len(spec["relations"]) == len(LINKS)
    # Function 含成本预警 + 成本聚合 + 应收状态
    fids = {f["id"] for f in spec["functions"]}
    assert {"F-project-cost-warning", "F-cost-rollup", "F-receivable-status"} <= fids
    # Action 含采购/收支/成本明细/里程碑/确认产值
    aids = {a["id"] for a in spec["actions"]}
    assert {"createProcurement", "recordPayment", "recordReceipt",
            "addCostItem", "completeMilestone", "confirmMilestoneValue"} <= aids


def test_receivable_lifecycle():
    # 里程碑确认产值 → 据此开票(2026-01-01) → 账期 60 天(到期 2026-03-02) → 部分回款
    inv = "2026-01-01"
    due = "2026-03-02"          # 开票日 + 60 天
    today = "2026-03-10"        # 已逾期 8 天
    # 状态：已收>=应收? 否；已收>0? 部分回款 40/100 → 部分（≠逾期，因已有回款）
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
    # 实体属性已含产值来源/发票/账期/回款状态
    rec = ENTITIES["Receipt"]
    rec_attrs = {a.name for a in rec.attributes}
    assert {"source_milestone", "invoice_no", "invoice_date", "due_date",
            "received_amount", "received_date", "status"} <= rec_attrs, rec_attrs
    assert ENTITIES["Milestone"].attributes[-1].name == "value"
    # 关系：里程碑→回款（产值来源）
    preds = {l["predicate"] for l in LINKS}
    assert {"realizesReceivable", "sourceMilestone", "payableFrom", "sourceProcurement"} <= preds
    print("[OK] 应收/回款生命周期：状态/账龄/逾期 + 实体属性 + 关系 全部通过")


if __name__ == "__main__":
    test_entities_structured()
    test_links_cardinality()
    test_cost_rollup_model()
    test_spec_shape()
    test_receivable_lifecycle()
    print("ALL TBOX TESTS PASSED")
