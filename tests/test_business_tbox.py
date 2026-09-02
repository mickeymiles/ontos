# -*- coding: utf-8 -*-
"""业务 TBox 结构化 + 成本聚合 + to_spec 测试。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ontos import domain_business as biz
from ontos.domain_business import ENTITIES, LINKS, to_spec, cost_rollup
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
    # Function 含成本预警 + 成本聚合
    fids = {f["id"] for f in spec["functions"]}
    assert {"F-project-cost-warning", "F-cost-rollup"} <= fids
    # Action 含采购/收支/成本明细/里程碑
    aids = {a["id"] for a in spec["actions"]}
    assert {"createProcurement", "recordPayment", "recordReceipt",
            "addCostItem", "completeMilestone"} <= aids


if __name__ == "__main__":
    test_entities_structured()
    test_links_cardinality()
    test_cost_rollup_model()
    test_spec_shape()
    print("ALL TBOX TESTS PASSED")
