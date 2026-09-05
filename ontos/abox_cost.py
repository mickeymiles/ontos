# -*- coding: utf-8 -*-
"""本体 ABox 成本适配层（共享：9006 固化页面 与 9007 智能体同一入口）。

═══ 分层原则 ═══
- ``domain_business.py``：TBox 纯函数（零 DB / 零 app 耦合，可单测）。
- ``本模块``         ：ABox 适配层——读物理表 md_contract → 构造 Project 成本事实 →
  调 F-project-cost-warning。★物理列绑定一律取 COST_FORMULA_POLICY['abox_adapter']
  声明（单一真相），本模块不另行硬编码列名；切源只改声明块。
- 调用方（9006 backend / 9007 gateway）    ：薄壳，只负责注入 DB（sqlite3 连接或文件路径）。

═══ 同源契约（2026-09-05 用户拍板）═══
本体的计算供 9006 与 9007 共用：任何一侧都**不得**绕开本层自建取数 SQL，也**不得**
经对方 HTTP API 取数（此前的网关转发 9006 /api/ontos/compute 已按此废弃），杜绝口径漂移。
9006 成本预警页面、9007 智能体问答的数据与判定均出自「本模块 + domain_business 纯函数」。

用法（两端一致）：
    from ontos import abox_cost
    abox_cost.cost_warning_portfolio(db_path='/path/to/contract_compare.db')      # 全量
    abox_cost.cost_warning_portfolio(db_path='...', contract_no='DFSY1410017C')  # 单项目
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Union

from .domain_business import COST_FORMULA_POLICY, functions

#: ABox 物理列绑定（单一真相：COST_FORMULA_POLICY.abox_adapter，勿直接改本常量）
ABOX_ADAPTER: Dict[str, str] = COST_FORMULA_POLICY["abox_adapter"]


def _num(v) -> Optional[float]:
    """转 float；None/非数值 → None（缺失即缺失，不当 0 处理）。"""
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def project_cost_facts(conn: sqlite3.Connection,
                        contract_no: Optional[str] = None) -> List[Dict[str, Any]]:
    """读 md_contract → Project 成本事实列表。

    - 预算/当前成本取 abox_adapter 声明的 impl_source 加工列
      （累计实施成本预估 / 累计实施成本实际，≡ COST_FORMULA_POLICY 分量和，已实测等价）。
    - 合同号为空 / 等于列名文本（表头混入数据的脏行）/ 重复 → 跳过（保留首行）。
    - project_no：源表无独立项目号列（205 列实测），缺省 = 合同编号（合同:项目 = 1:1）。
    """
    table = ABOX_ADAPTER["table"]
    wanted = [ABOX_ADAPTER["key"], ABOX_ADAPTER["name"],
              ABOX_ADAPTER["budget"], ABOX_ADAPTER["current_cost"]]
    try:
        cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    except sqlite3.Error:
        return []
    if ABOX_ADAPTER["key"] not in cols:
        return []          # 表不存在或缺关键列 → 无事实（调用方按空数据降级）
    fields = ','.join('"%s"' % c for c in wanted if c in cols)
    sql = f'SELECT {fields} FROM "{table}"'
    args: tuple = ()
    if contract_no:
        sql += f' WHERE "{ABOX_ADAPTER["key"]}" = ?'
        args = (contract_no,)
    cur = conn.execute(sql, args)
    sel_cols = [d[0] for d in cur.description]     # 不依赖调用方的 row_factory
    rows = [dict(zip(sel_cols, r)) for r in cur.fetchall()]

    facts: List[Dict[str, Any]] = []
    seen = set()
    for r in rows:
        cno = str(r.get(ABOX_ADAPTER["key"]) or '').strip()
        if not cno or cno == ABOX_ADAPTER["key"] or cno in seen:
            continue
        seen.add(cno)
        facts.append({
            'project_no': cno,                                   # 缺省=合同编号（1:1）
            'contract_no': cno,
            'name': str(r.get(ABOX_ADAPTER["name"]) or '') if ABOX_ADAPTER["name"] in r else '',
            'budget': _num(r.get(ABOX_ADAPTER["budget"])),
            'current_cost': _num(r.get(ABOX_ADAPTER["current_cost"])),
        })
    return facts


def cost_warning_portfolio(db: Union[str, sqlite3.Connection],
                           contract_no: Optional[str] = None) -> Dict[str, Any]:
    """全量成本预警：读 ABox 事实 → 逐项目调 F-project-cost-warning 判定 → 汇总。

    ★9006 /api/core/metrics/cost-warning 与 9007 ontology_compute(cost_warning_portfolio)
    共用的唯一实现（同源入口）。

    db          : sqlite3 连接 或 SQLite 文件路径（调用方注入；9007 在同机直读同一份文件，只读）。
    contract_no : 指定则只算该合同（单项目查询）。

    返回（页面契约，与 9006 原 cost_warning_all 同构）：
    {total, total_budget, total_current_cost, total_est_cost, total_remaining,
     status_count, summary, rows:[{project_no, contract_no, name, estimate,
     est_cost, effective_cost, budget, current_cost, remaining, budget_ratio,
     status, note}]}
    - estimate(概算) 恒 None：四算数据未接入，仅展示、不参与判定（见 RESERVED_FIELDS）。
    - est_cost(工单预估) 恒 0：F-workorder-cost-rollup 聚合源未落地，退化为滞后口径。
    - 仅纳入具备任一数据（预算 or 当前成本>0）的业务单元。
    """
    own = False
    if isinstance(db, sqlite3.Connection):
        conn = db
    else:
        conn = sqlite3.connect(db)
        own = True
    try:
        facts = project_cost_facts(conn, contract_no=contract_no)
    finally:
        if own:
            conn.close()

    details: List[Dict[str, Any]] = []
    total_budget = total_current = total_est = 0.0
    status_count: Dict[str, int] = {'正常': 0, '预警': 0, '超支': 0}
    for f in facts:
        budget = f['budget']
        current_cost = round(f['current_cost'] or 0.0, 2)
        if budget is None and current_cost <= 0:
            continue
        # ★判定统一走本体 F-project-cost-warning（与纯函数/智能体同一份算法）
        res = functions.call(
            "F-project-cost-warning",
            budget=budget,
            current_cost=current_cost,
            wo_est_cost=0.0,          # 工单预估聚合源未落地（RESERVED_FIELDS），接入后此处改读
        )
        woe = float(res.get('wo_est_cost') or 0.0)
        status_count[res['status']] = status_count.get(res['status'], 0) + 1
        total_current += current_cost
        total_est += woe
        if budget is not None:
            total_budget += budget
        details.append({
            'project_no': f['project_no'],
            'contract_no': f['contract_no'],
            'name': f['name'],
            'estimate': None,                    # 概算 ⌛预留（非判定入参）
            'est_cost': woe,                     # PMO 预估成本（= ontos wo_est_cost）
            'effective_cost': res['effective_cost'],
            'budget': budget,
            'current_cost': current_cost,
            'remaining': res['remaining_cost'],
            'budget_ratio': res['budget_ratio'],
            'status': res['status'],
            'note': res['note'],
        })
    n = len(details)
    total_est = round(total_est, 2)
    total_remaining = round(total_budget - total_current - total_est, 2)
    return {
        'total': n,
        'total_budget': round(total_budget, 2),
        'total_current_cost': round(total_current, 2),
        'total_est_cost': total_est,
        'total_remaining': total_remaining,
        'status_count': status_count,
        'summary': {
            '项目数': '%d 个' % n,
            '预算金额合计': '¥%s' % format(round(total_budget), ','),
            '当前成本合计': '¥%s' % format(round(total_current), ','),
            '预估成本合计': '¥%s' % format(round(total_est), ','),
            '剩余成本合计': '¥%s' % format(round(total_remaining), ','),
            '超支项目': status_count.get('超支', 0),
            '预警项目': status_count.get('预警', 0),
        },
        'rows': details,
    }
