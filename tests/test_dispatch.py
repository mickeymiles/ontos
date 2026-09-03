# -*- coding: utf-8 -*-
"""dispatch() 计算分发器测试：确保 9006 / demo 共用同一份算法入口。

运行（从 ontos 仓库根目录）：
  python -m tests.test_dispatch
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ontos import domain_business as biz


def test_list_compute_functions():
    fns = biz.list_compute_functions()
    ids = {f["id"] for f in fns}
    assert "payment_cycle" in ids
    assert "project_roi" in ids
    # 去重：payment_cycle 与 F-payment-cycle 同源，只出现一次
    assert len(fns) == len(ids)


def test_dispatch_payment_cycle_first():
    r = biz.dispatch("payment_cycle", {
        "sign_date": "2024-01-01",
        "receipts": [{"received_date": "2024-03-01"}, {"received_date": "2024-05-01"}],
        "basis": "first",
    })
    assert r["success"] is True
    assert r["function"] == "payment_cycle"
    assert r["result"]["cycle_days"] == 60
    assert r["result"]["basis"] == "first"


def test_dispatch_f_prefix_alias():
    # F-project-roi 应与 project_roi 等价
    a = biz.dispatch("project_roi", {"revenue": 120, "current_cost": 100})
    b = biz.dispatch("F-project-roi", {"revenue": 120, "current_cost": 100})
    assert a["success"] and b["success"]
    assert a["result"]["roi"] == b["result"]["roi"] == 0.2


def test_dispatch_unknown_function():
    r = biz.dispatch("nope", {})
    assert r["success"] is False
    assert r["error"] == "unknown_function"
    assert "available" in r


def test_dispatch_missing_function_name():
    r = biz.dispatch("", {})
    assert r["success"] is False
    assert r["error"] == "missing_function"


def test_dispatch_param_error():
    # 故意传不存在的参数 → param_error（不抛 500）
    r = biz.dispatch("project_roi", {"revenue": 1, "current_cost": 2, "bogus": 3})
    assert r["success"] is False
    assert r["error"] == "param_error"


if __name__ == "__main__":
    for fn in (test_list_compute_functions, test_dispatch_payment_cycle_first,
               test_dispatch_f_prefix_alias, test_dispatch_unknown_function,
               test_dispatch_missing_function_name, test_dispatch_param_error):
        fn()
        print("PASS", fn.__name__)
    print("ALL OK")
