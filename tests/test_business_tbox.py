# -*- coding: utf-8 -*-
"""业务 TBox 结构化 + 成本聚合 + 新增 Function + to_spec 测试（v4 场景收敛版）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ontos import domain_business as biz
from ontos.domain_business import ENTITIES, LINKS, to_spec, cost_rollup, receivable_status
from ontos.registry import functions


def test_entities_v4():
    # v4：仅 5 实体，无顶层/子实体混淆
    names = set(ENTITIES.keys())
    assert names == {"Contract", "Project", "Milestone", "Receipt", "Payment"}, names
    # 每个实体都有属性，且至少含唯一主键
    for name, e in ENTITIES.items():
        assert e.attributes, f"{name} 无属性"
        assert any(a.unique for a in e.attributes), f"{name} 缺唯一主键属性"


def test_links_v4():
    preds = {l["predicate"] for l in LINKS}
    for need in ["belongsTo", "hasMilestone", "decomposedFrom",
                 "realizesReceivable", "sourceMilestone", "hasReceipt",
                 "hasPayment", "signedWith"]:
        assert need in preds, f"缺关系 {need}"


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
    assert len(spec["entities"]) == 5
    # 兼容 9006 /spec 历史字段
    assert set(spec["concepts"].keys()) == set(ENTITIES.keys())
    assert len(spec["relations"]) == len(LINKS)
    # Function 含 6 个主场景函数 + 应收状态
    fids = {f["id"] for f in spec["functions"]}
    assert {"F-project-cost-warning", "F-cost-rollup", "F-capital-occupation",
            "F-project-roi", "F-project-margin", "F-payment-cycle",
            "F-receivable-status"} <= fids
    # Action 含 v4 最小集
    aids = {a["id"] for a in spec["actions"]}
    assert {"recordReceipt", "recordPayment", "confirmMilestoneValue",
            "createMinorMilestone", "completeMilestone", "raiseProjectCostWarning"} <= aids


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
    # 里程碑确认产值 → 据此开票(2026-01-01) → 账期 60 天(到期 2026-03-02) → 部分回款
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
    # 实体属性：收款单含产值来源/发票/账期/回款状态
    rec_attrs = {a.name for a in ENTITIES["Receipt"].attributes}
    assert {"source_milestone", "invoice_no", "invoice_date", "due_date",
            "received_amount", "received_date", "status"} <= rec_attrs, rec_attrs
    # 里程碑含 level/value/progress/parent_ms（大/小层级 + 产值）
    ms_attrs = {a.name for a in ENTITIES["Milestone"].attributes}
    assert {"level", "value", "progress", "parent_ms"} <= ms_attrs, ms_attrs
    # 关系：里程碑→回款（产值来源）+ 小→大 decomposedFrom
    preds = {l["predicate"] for l in LINKS}
    assert {"realizesReceivable", "sourceMilestone", "decomposedFrom"} <= preds
    print("[OK] 应收/回款生命周期 + 里程碑层级属性 + 关系 全部通过")


if __name__ == "__main__":
    test_entities_v4()
    test_links_v4()
    test_cost_rollup_model()
    test_spec_shape()
    test_new_functions()
    test_receivable_lifecycle()
    print("ALL TBOX TESTS PASSED")
