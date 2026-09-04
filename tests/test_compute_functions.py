# -*- coding: utf-8 -*-
"""7 个本体计算纯函数的单测：回款周期/资金占用/毛利率/ROI/成本聚合/应收状态/成本预警。

目的：
- 固化「算法只在 ontos 一份」的可验证保证——9006(dispatch) / demo(本地直调) / 9010(转发)
  都复用同一批纯函数，这里锁住它们的输入/输出契约与不变量。
- 覆盖 §7「后续场景按 v4 收敛逐一定义并补纯函数 + 测试」中的「补测试」部分。

运行：
  python -m tests.test_compute_functions      # 直接跑
  pytest tests/test_compute_functions.py -q   # pytest
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ontos import domain_business as biz


# ───────────────────────── 回款周期 F-payment-cycle ─────────────────────────
def test_payment_cycle_last():
    r = biz.payment_cycle(
        sign_date="2024-01-01",
        receipts=[{"received_date": "2024-03-01"}, {"received_date": "2024-05-01"}],
        basis="last",
    )
    assert r["cycle_days"] == 121          # 2024-01-01 → 2024-05-01（含闰年 2 月 29 天）
    assert r["basis"] == "last"
    assert r["recv_count"] == 2
    assert r["recv_date"] == "2024-05-01"


def test_payment_cycle_first():
    r = biz.payment_cycle(
        sign_date="2024-01-01",
        receipts=[{"received_date": "2024-03-01"}, {"received_date": "2024-05-01"}],
        basis="first",
    )
    assert r["cycle_days"] == 60           # 2024-01-01 → 2024-03-01
    assert r["basis"] == "first"
    assert r["first_recv_date"] == "2024-03-01"


def test_payment_cycle_missing_sign_date():
    r = biz.payment_cycle(sign_date=None, receipts=[{"received_date": "2024-03-01"}])
    assert r["cycle_days"] is None
    assert "NaN" in r["note"]


def test_payment_cycle_no_receipts():
    r = biz.payment_cycle(sign_date="2024-01-01", receipts=[])
    assert r["cycle_days"] is None
    assert "NaN" in r["note"]


def test_payment_cycle_recv_before_sign_is_anomaly():
    r = biz.payment_cycle(
        sign_date="2024-06-01",
        receipts=[{"received_date": "2024-01-01"}],
    )
    assert r["cycle_days"] is not None and r["cycle_days"] < 0
    assert "异常" in r["note"]


# ──────────────────────── 资金占用 F-capital-occupation ────────────────────────
def test_capital_occupation_basic():
    r = biz.capital_occupation(
        payments=[{"paid_amount": 100}],
        receipts=[{"amount": 200, "received_amount": 50}],
    )
    assert r["paid_total"] == 100
    assert r["receivable_remain"] == 150
    assert r["occupied"] == 250
    assert r["net"] == 250
    # 不变量：occupied = paid_total + receivable_remain 且各项非负
    assert r["occupied"] == r["paid_total"] + r["receivable_remain"]
    assert all(v >= 0 for v in (r["occupied"], r["paid_total"], r["receivable_remain"]))


def test_capital_occupation_empty():
    r = biz.capital_occupation(payments=[], receipts=[])
    assert r["occupied"] == 0
    assert r["paid_total"] == 0
    assert r["receivable_remain"] == 0


# ───────────────────────── 毛利率 F-project-margin ─────────────────────────
def test_project_margin():
    r = biz.project_margin(sign_amount=1000, sign_gross_profit=200)
    assert r["gross_rate"] == 0.2
    assert "sign_amount" in r and "sign_gross_profit" in r


def test_project_margin_zero_amount():
    r = biz.project_margin(sign_amount=0, sign_gross_profit=200)
    assert r["gross_rate"] is None
    assert "无意义" in r["note"]


# ─────────────────────────── ROI F-project-roi ───────────────────────────
def test_project_roi():
    r = biz.project_roi(revenue=1200, current_cost=1000)
    assert r["roi"] == 0.2


def test_project_roi_zero_cost():
    r = biz.project_roi(revenue=1200, current_cost=0)
    assert r["roi"] is None
    assert "无意义" in r["note"]


# ───────────────────────── 成本聚合 F-cost-rollup ─────────────────────────
def test_cost_rollup():
    r = biz.cost_rollup(
        payments=[{"amount": 100}],
        cost_detail_rows=[{"amount": 50}],
    )
    assert r["payment_sum"] == 100
    assert r["costitem_sum"] == 50
    assert r["current_cost"] == 150
    assert r["current_cost"] == r["payment_sum"] + r["costitem_sum"]


# ─────────────────────── 应收状态 F-receivable-status ───────────────────────
def test_receivable_overdue():
    r = biz.receivable_status(
        invoice_date="2024-01-01", due_date="2024-02-01",
        amount=100, received_amount=0, today="2024-03-01",
    )
    assert r["status"] == "逾期"
    assert r["overdue_days"] == 29        # 2024-02-01 → 2024-03-01
    assert r["aging_days"] == 60          # 2024-01-01 → 2024-03-01
    assert r["aging_bucket"] == "31-60天"
    assert r["remain"] == 100


def test_receivable_collected():
    r = biz.receivable_status(amount=100, received_amount=100)
    assert r["status"] == "已收"
    assert r["remain"] == 0


def test_receivable_partial():
    r = biz.receivable_status(amount=100, received_amount=40)
    assert r["status"] == "部分"
    assert r["remain"] == 60


# ─────────────────────── 成本预警 F-project-cost-warning ───────────────────────
def test_cost_warning_normal():
    r = biz.project_cost_warning(budget=1000, current_cost=800)
    assert r["status"] == "正常"
    assert r["budget_ratio"] == 0.8


def test_cost_warning_warn():
    r = biz.project_cost_warning(budget=1000, current_cost=950)
    assert r["status"] == "预警"
    assert r["budget_ratio"] == 0.95
    assert r["remaining_cost"] == 50


def test_cost_warning_over():
    r = biz.project_cost_warning(budget=1000, current_cost=1200)
    assert r["status"] == "超支"


def test_cost_warning_no_budget_no_false_alarm():
    # 缺预算不得误报超支（不变量 cost-warning-only-with-budget）
    r = biz.project_cost_warning(budget=None, current_cost=500)
    assert r["status"] == "正常"


# ─────────────────────── 全函数 dispatch 可达性回归 ───────────────────────
def test_all_functions_reachable_via_dispatch():
    ids = [f["id"] for f in biz.list_compute_functions()]
    sample = {
        "payment_cycle": {"sign_date": "2024-01-01", "receipts": [{"received_date": "2024-03-01"}]},
        "capital_occupation": {"payments": [], "receipts": []},
        "project_margin": {"sign_amount": 1000, "sign_gross_profit": 200},
        "project_roi": {"revenue": 1200, "current_cost": 1000},
        "cost_rollup": {"payments": [], "cost_detail_rows": []},
        "receivable_status": {"amount": 100, "received_amount": 50},
        "project_cost_warning": {"budget": 1000, "current_cost": 800},
        "project_cost_warning_from_ledger": {"budget": 1000, "payments": [], "cost_detail_rows": []},
        "project_budget": {"hw_integration_fee": 100, "service_est_cost": 50, "sw_est_impl_fee": 30},
        "project_cost": {"hw_integration_actual": 80, "sw_impl_actual": 40, "prior_svc_direct": 10,
                        "prior_svc_indirect": 5, "curr_svc_direct": 8, "curr_svc_indirect": 7},
        "project_cost_remaining": {"budget": 1000, "cost": 800},
        "workorder_cost_rollup": {"workorders": [{"est_personnel": 20, "est_travel": 5,
                                                 "est_flexible": 3, "est_variable": 2}]},
        "project_current_remaining": {"budget": 1000, "cost": 800, "wo_est_cost": 30},
    }
    # 同时用 F- 前缀键验证 _COMPUTE_FUNCS 双命名注册完整
    for fid in ids:
        r = biz.dispatch(fid, sample[fid])
        assert r["success"] is True, (fid, r)
        r2 = biz.dispatch("F-" + fid.replace("_", "-"), sample[fid])
        assert r2["success"] is True, ("F-" + fid, r2)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print("ALL OK (%d tests)" % len(fns))
