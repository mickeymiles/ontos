# -*- coding: utf-8 -*-
"""业务域适配器样例（ontos · 局部落地示范）。

展示 9006 既有数据如何经 ontos Function 统一计算，而不重写现有逻辑。
本模块纯函数、无 DB 耦合：调用方把已从 DB 取出的记录 dict 传进来即可。

真实落地时（P1 + C4 维护窗口）：9006 backend/core/project_metrics.cost_warning_all
只需把内部 `_cost_status(budget, current_cost)` 换成
`functions.call('F-project-cost-warning', budget=budget, current_cost=current_cost)`，
即完成「口径收敛到本体」，无需改页面契约。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .registry import functions


def cost_warning_all_from_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """对一批项目记录批量计算成本预警（局部落地样例）。

    每条 record 建议字段：project_no, contract_no, name, estimate, budget, current_cost。
    返回与 9006 cost_warning_all 同构的 summary + rows，便于页面/智能体直接消费。
    """
    details: List[Dict[str, Any]] = []
    total_budget = total_current = 0.0
    status_count: Dict[str, int] = {"正常": 0, "预警": 0, "超支": 0}
    for r in records:
        if r.get("estimate") is None and r.get("budget") is None \
                and float(r.get("current_cost") or 0) <= 0:
            continue
        res = functions.call(
            "F-project-cost-warning",
            estimate=r.get("estimate"),
            budget=r.get("budget"),
            current_cost=r.get("current_cost"),
        )
        status = res["status"]
        status_count[status] = status_count.get(status, 0) + 1
        if res.get("budget") is not None:
            total_budget += res["budget"]
        total_current += res.get("current_cost") or 0.0
        details.append({
            "project_no": r.get("project_no"),
            "contract_no": r.get("contract_no"),
            "name": r.get("name") or "",
            "estimate": res.get("estimate"),
            "budget": res.get("budget"),
            "current_cost": res.get("current_cost"),
            "remaining_cost": res.get("remaining_cost"),
            "budget_ratio": res.get("budget_ratio"),
            "status": status,
            "note": res.get("note"),
        })
    n = len(details)
    total_remaining = round(total_budget - total_current, 2)
    return {
        "total": n,
        "total_budget": round(total_budget, 2),
        "total_current_cost": round(total_current, 2),
        "total_remaining": total_remaining,
        "status_count": status_count,
        "summary": {
            "项目数": "%d 个" % n,
            "预算金额合计": "¥%s" % format(round(total_budget), ','),
            "当前成本合计": "¥%s" % format(round(total_current), ','),
            "剩余成本合计": "¥%s" % format(round(total_remaining), ','),
            "超支项目": status_count.get("超支", 0),
            "预警项目": status_count.get("预警", 0),
        },
        "rows": details,
    }
