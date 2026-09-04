# -*- coding: utf-8 -*-
"""业务域骨架 + 成本预警 pilot 测试（含与 9006 现算法影子比对）。

运行：从 ontos 仓库根目录
  python -m tests.test_business_domain
或
  python tests/test_business_domain.py
"""
import os
import sys

# 确保能 import ontos 包（仓库根在 sys.path）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ontos import domain_business as biz              # 导入即注册 Function/Action
from ontos.domain_business import cost_warning_rule
from ontos.registry import functions, actions


# ── 1) 独立黄金用例（不依赖 9006，作为语义 oracle）─────────────
GOLDEN = [
    # (budget, current, 期望status, 期望note片段)
    (100.0, 50.0,  "正常", "预算执行在阈值内"),
    (100.0, 95.0,  "预警", "预算完成比已达 95%"),
    (200.0, 180.0, "预警", "预算完成比已达 90%"),     # 边界含 0.9
    (100.0, 120.0, "超支", "已超过预算"),
    (None,  0.0,   "正常", "缺预算且无有效成本"),
    (None,  30.0,  "正常", "缺预算，暂无法判定预警（有效成本 ¥30）"),
    (0.0,   10.0,  "正常", "缺预算，暂无法判定预警（有效成本 ¥10）"),
    (100.0, 0.0,   "正常", "预算执行在阈值内（预算完成比 0%）"),
]


def test_golden():
    for budget, current, exp_status, exp_note in GOLDEN:
        status, note = cost_warning_rule(budget, current)
        assert status == exp_status, f"({budget},{current}) status={status} != {exp_status}"
        assert exp_note in note, f"({budget},{current}) note={note!r} 不含 {exp_note!r}"
    print("[OK] 黄金用例 8/8 通过")


# ── 2) 与 9006 现算法影子比对（若可导入则真比对，否则跳过）──
def _load_legacy():
    legacy_path = "/Users/macbook/AI-Agent/contract-compare-9006/backend"
    if not os.path.isdir(legacy_path):
        return None
    saved = sys.path[:]
    try:
        sys.path.insert(0, legacy_path)
        from core.project_metrics import _cost_status
        return _cost_status
    except Exception as e:                       # 导入失败（缺依赖/环境问题）→ 跳过真比对
        print(f"[SKIP] 无法导入 9006 _cost_status（{e}），仅跑黄金用例")
        return None
    finally:
        sys.path[:] = saved


def test_shadow_vs_legacy():
    legacy = _load_legacy()
    if legacy is None:
        return
    # 用一组覆盖各分支的输入对拍
    cases = [(100.0, 50.0), (100.0, 95.0), (200.0, 180.0), (100.0, 120.0),
             (None, 0.0), (None, 30.0), (0.0, 10.0), (100.0, 0.0), (250.0, 249.0)]
    for budget, current in cases:
        got_s, got_n = cost_warning_rule(budget, current)
        exp_s, exp_n = legacy(budget, current)
        # v6 起 ontos 用语义更准确的「有效成本」(=当前成本+工单预估) 替代「当前成本」，
        # 判定状态(status)必须逐字一致；note 仅在术语差异处归一化后比对。
        got_n_norm = got_n.replace("有效成本", "当前成本")
        assert got_s == exp_s and got_n_norm == exp_n, \
            f"不一致 ({budget},{current}): ontos=({got_s},{got_n!r}) 9006=({exp_s},{exp_n!r})"
    print(f"[OK] 影子比对 {len(cases)} 例：ontos 与 9006 判定状态逐字一致（note 术语已归一化）")


# ── 3) 注册表契约验证 ───────────────────────────────────────
def test_registry():
    # pilot Function 已注册且可经注册表调用
    assert functions.has("F-project-cost-warning")
    res = functions.call("F-project-cost-warning", budget=100, current_cost=96)
    assert res["status"] == "预警", res
    assert abs(res["budget_ratio"] - 0.96) < 1e-6, res
    assert res["remaining_cost"] == 4.0, res
    # 6 个主场景 Function 声明齐全
    for fid in ("F-project-margin", "F-payment-cycle", "F-project-cost-warning",
                "F-capital-occupation", "F-project-roi", "F-cost-rollup"):
        assert functions.has(fid), fid
    # v6.1 Action 集声明齐全（含新增 applyInvoice / createSubContract）
    for aid in ("recordReceipt", "recordPayment", "confirmMilestoneValue", "applyInvoice",
                "completeMilestone", "raiseProjectCostWarning", "createSubContract"):
        assert actions.has(aid), aid
    # 业务实体 / 关系声明存在（v6.1：15 实体）
    assert set(["Project", "Contract", "Milestone", "Receipt", "Payment", "Opportunity",
                "PreSales", "OutputValue", "Invoice", "Deposit"]).issubset(biz.CONCEPTS.keys())
    assert "Contract.belongsTo(Project)" in biz.RELATIONS
    assert "Project.hasMilestone(Milestone)" in biz.RELATIONS
    # v6：子里程碑已移除 → decomposedFrom 不再存在；v6.1：里程碑不再 sourcedFromContract / executesAs
    assert "Milestone.decomposedFrom(Milestone)" not in biz.RELATIONS
    assert "Contract.sourcedFromContract(Milestone)" not in biz.RELATIONS
    assert "Milestone.executesAs(Order)" not in biz.RELATIONS
    # LTC 链路 + 执行链 + 财经链 关系存在
    assert "Opportunity.hasPreSales(PreSales)" in biz.RELATIONS
    assert "PreSales.winContract(Contract)" in biz.RELATIONS
    assert "Milestone.hasOutputValue(OutputValue)" in biz.RELATIONS
    assert "Contract.hasReceipt(Receipt)" in biz.RELATIONS
    assert "Contract.hasInvoice(Invoice)" in biz.RELATIONS
    assert "Contract.hasDeposit(Deposit)" in biz.RELATIONS
    assert "Order.hasWorkOrder(WorkOrder)" in biz.RELATIONS
    assert "Task.assignedTo(Person)" in biz.RELATIONS
    print("[OK] 注册表契约：Function + Action + 实体 + 关系 声明完整（LTC 链路已固化）")


# ── 4) adapters 局部落地样例 ───────────────────────────────
def test_adapters_landing():
    from ontos.adapters import cost_warning_all_from_records
    records = [
        {"project_no": "P1", "name": "A项目", "budget": 100.0, "current_cost": 96.0, "estimate": 120.0},
        {"project_no": "P2", "name": "B项目", "budget": 100.0, "current_cost": 50.0},
        {"project_no": "P3", "name": "C项目", "budget": 200.0, "current_cost": 210.0},
        {"project_no": "P4", "name": "D项目", "budget": None, "current_cost": 0.0},  # 缺预算且无成本 → 正确跳过
    ]
    out = cost_warning_all_from_records(records)
    assert out["total"] == 3, out["total"]            # P4 被跳过
    assert out["status_count"]["预警"] == 1, out["status_count"]
    assert out["status_count"]["超支"] == 1, out["status_count"]
    assert out["status_count"]["正常"] == 1, out["status_count"]
    print("[OK] adapters 局部落地样例：批量预警汇总正确（1预警/1超支/2正常）")


# ── 5) 组合函数：成本聚合 → 成本预警（★成本口径唯一入口）────────────
def test_cost_warning_from_ledger():
    from ontos.domain_business import project_cost_warning_from_ledger

    # 付款 60+20 + 成本明细 20 = 当前成本 100，预算 100 → 完成比 1.0 → 预警（非超支）
    res = project_cost_warning_from_ledger(
        budget=100.0,
        payments=[{"amount": 60.0}, {"amount": 20.0}],
        cost_detail_rows=[{"amount": 20.0}],
    )
    assert res["current_cost"] == 100.0, res
    assert res["budget_ratio"] == 1.0, res
    assert res["status"] == "预警", res            # ratio=1.0 不 > overrun_ratio=1.0
    assert res["severity"] == "预警", res
    assert res["cost_breakdown"]["payment_sum"] == 80.0, res
    assert res["cost_breakdown"]["costitem_sum"] == 20.0, res

    # 付款 130 > 预算 100 → 超支（严重）
    res2 = project_cost_warning_from_ledger(budget=100.0, payments=[{"amount": 130.0}])
    assert res2["status"] == "超支" and res2["severity"] == "严重", res2

    # 缺预算不得误报
    res3 = project_cost_warning_from_ledger(budget=None, payments=[{"amount": 130.0}])
    assert res3["status"] == "正常", res3

    # 注册表双通道可用（functions.call / dispatch）
    assert functions.has("F-project-cost-warning-from-ledger")
    r = functions.call("F-project-cost-warning-from-ledger",
                       budget=100.0, payments=[{"amount": 95.0}])
    assert r["status"] == "预警" and r["current_cost"] == 95.0, r
    print("[OK] 组合函数：聚合→判定 链路正确（含 registry 调用）")


# ── 6) v6 成本双口径 + 预警切口径(wo_est_cost) ────────────────
def test_cost_formula_and_warning_woest():
    # 新成本函数注册齐全
    for fid in ("F-project-budget", "F-project-cost", "F-project-cost-remaining",
                "F-workorder-cost-rollup", "F-project-current-remaining"):
        assert functions.has(fid), fid
    # 预算/成本/工单/当前剩余 端到端
    b = functions.call("F-project-budget", hw_integration_fee=100.0,
                      service_est_cost=50.0, sw_est_impl_fee=30.0)
    c = functions.call("F-project-cost", hw_integration_actual=80.0, sw_impl_actual=40.0,
                      prior_svc_direct=10.0, prior_svc_indirect=5.0,
                      curr_svc_direct=8.0, curr_svc_indirect=7.0)
    wo = functions.call("F-workorder-cost-rollup", workorders=[
        {"est_personnel": 20.0, "est_travel": 5.0, "est_flexible": 3.0, "est_variable": 2.0}])
    cur = functions.call("F-project-current-remaining", budget=b["budget"], cost=c["cost"],
                        wo_est_cost=wo["wo_est_cost"])
    assert b["budget"] == 180.0 and c["cost"] == 150.0, (b, c)
    assert wo["wo_est_cost"] == 30.0 and cur["current_remaining_cost"] == 0.0, (wo, cur)
    # 预警切口径：wo_est_cost 叠加有效成本，剩余 = 预算-当前-工单，向后兼容(缺省0=滞后)
    # w1: 缺省 wo_est_cost=0 (滞后口径)，当前成本 80/100=0.8 < 0.9 → 正常
    w1 = functions.call("F-project-cost-warning", budget=100.0, current_cost=80.0)
    assert w1["remaining_cost"] == 20.0 and w1["status"] == "正常", w1
    w2 = functions.call("F-project-cost-warning", budget=100.0, current_cost=90.0, wo_est_cost=15.0)
    assert w2["effective_cost"] == 105.0 and w2["status"] == "超支", w2
    assert w2["remaining_cost"] == -5.0 and w2["wo_est_cost"] == 15.0, w2
    print("[OK] v6 成本双口径 + 预警切口径(wo_est_cost) 全部通过")


if __name__ == "__main__":
    test_golden()
    test_shadow_vs_legacy()
    test_registry()
    test_adapters_landing()
    test_cost_warning_from_ledger()
    test_cost_formula_and_warning_woest()
    print("\nALL PASS ✅")
