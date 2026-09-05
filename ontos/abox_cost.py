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

import os
import sqlite3
from typing import Any, Dict, List, Optional, Union

from .domain_business import COST_FORMULA_POLICY, functions

#: ABox 物理列绑定（单一真相：COST_FORMULA_POLICY.abox_adapter，勿直接改本常量）
ABOX_ADAPTER: Dict[str, str] = COST_FORMULA_POLICY["abox_adapter"]


def _available_columns(conn: sqlite3.Connection, table: str) -> set:
    """物理表实际存在的列名集合（表不存在 → 空集）。"""
    try:
        return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    except sqlite3.Error:
        return set()


def _query_rows(conn: sqlite3.Connection, table: str, wanted: List[str],
                where_col: Optional[str] = None, where_val: Optional[str] = None,
                limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """按「实际存在的列」组装查询并返回 dict 列表（不依赖调用方 row_factory）。"""
    cols = _available_columns(conn, table)
    fields = [c for c in wanted if c in cols]
    if not fields:
        return []
    sql = 'SELECT %s FROM "%s"' % (','.join('"%s"' % c for c in fields), table)
    args: List[Any] = []
    if where_col and where_col in cols and where_val:
        sql += ' WHERE "%s" = ?' % where_col
        args.append(where_val)
    if limit:
        sql += ' LIMIT ?'
        args.append(limit)
    cur = conn.execute(sql, tuple(args))
    sel = [d[0] for d in cur.description]
    return [dict(zip(sel, r)) for r in cur.fetchall()]


def _num(v) -> Optional[float]:
    """转 float；None/非数值 → None（缺失即缺失，不当 0 处理）。"""
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def not_available(domain: str) -> Dict[str, Any]:
    """⌛未接入数据域的标准响应（★红线：禁止用假数据兜底——宁可说没有，不可编）。

    智能体侧据此如实告知用户「该数据尚未接入」，而不是用演示数据冒充真实业务数据
    （历史教训：P-2026-* 假项目被当成真实项目，连成本分析结论都是错的）。
    """
    na = ABOX_ADAPTER.get("not_available") or {}
    blocked = na.get(domain, f'{domain} 数据源未接入')
    return {
        'available': False,
        'domain': domain,
        'blocked_by': blocked,
        'message': f'本体中尚无「{domain}」数据（{blocked}）。不做估算、不返回演示数据；'
                   f'数据源接入后本工具自动可用。',
    }


def _profile_columns() -> List[str]:
    """项目档案 + 预算/成本 的物理列清单（取 abox_adapter 声明）。"""
    prof = ABOX_ADAPTER.get("profile") or {}
    cols = [ABOX_ADAPTER["key"], ABOX_ADAPTER["budget"], ABOX_ADAPTER["current_cost"]]
    cols += [c for c in prof.values() if isinstance(c, str)]
    return cols


def _load_project_rows(db: Union[str, sqlite3.Connection],
                       contract_no: Optional[str] = None) -> List[Dict[str, Any]]:
    """读 md_contract 项目行（去重、跳过脏行），返回【全量】行。

    ★不在此处 limit：调用方需要基于全量统计（总数/预警分布），
      截断只影响最终返回条数，绝不污染 total 与 status_count。
    """
    own = False
    if isinstance(db, sqlite3.Connection):
        conn = db
    else:
        conn = sqlite3.connect(db)
        own = True
    try:
        return _query_rows(conn, ABOX_ADAPTER["table"], _profile_columns(),
                           where_col=ABOX_ADAPTER["key"], where_val=contract_no)
    finally:
        if own:
            conn.close()


def project_facts(db: Union[str, sqlite3.Connection],
                  contract_no: Optional[str] = None,
                  limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """项目档案 + 预算/成本 + 本体预警判定（★9006 与 9007 同源）。

    智能体（项目管理专家）的「项目画像」数据源：读 md_contract 档案列（部门/责任人/
    区域/合同状态/签约额…）+ 预算/成本加工列，再逐项目调 F-project-cost-warning。
    返回字段名兼顾智能体既有工具契约：project_id = 合同编号（源表无独立项目号列）。

    ⚠ 需要「总数 / 是否截断 / 全量预警分布」请用 project_portfolio：
       本函数只返回列表，调用方无法区分「样本」与「全集」（曾导致智能体把
       前 19 条当成全部 629 个项目作答）。
    """
    prof = ABOX_ADAPTER.get("profile") or {}
    rows = _load_project_rows(db, contract_no=contract_no)
    rollup = workorder_cost_by_project(db)    # 按项目工单预估（补滞后口径）

    out: List[Dict[str, Any]] = []
    seen = set()
    for r in rows:
        cno = str(r.get(ABOX_ADAPTER["key"]) or '').strip()
        if not cno or cno == ABOX_ADAPTER["key"] or cno in seen:
            continue
        seen.add(cno)
        budget = _num(r.get(ABOX_ADAPTER["budget"]))
        current_cost = round(_num(r.get(ABOX_ADAPTER["current_cost"])) or 0.0, 2)
        woe = float(rollup.get(cno, 0.0) or 0.0)
        warn = functions.call("F-project-cost-warning", budget=budget,
                              current_cost=current_cost, wo_est_cost=woe)
        out.append({
            'project_id': cno,                 # 兼容智能体工具契约（= 合同编号）
            'contract_no': cno,
            'name': str(r.get(prof.get('name', '') or '') or ''),
            'dept': r.get(prof.get('dept', '') or '') or '',
            'owner': r.get(prof.get('owner', '') or '') or '',
            'region': r.get(prof.get('region', '') or '') or '',
            'status': r.get(prof.get('status', '') or '') or '',
            'sign_date': r.get(prof.get('sign_date', '') or '') or '',
            'amount': _num(r.get(prof.get('amount', '') or '')),
            'customer': r.get(prof.get('customer', '') or '') or '',
            'year': r.get(prof.get('year', '') or '') or '',
            'industry': r.get(prof.get('industry', '') or '') or '',
            'budget': budget,
            'current_cost': current_cost,
            'est_cost': woe,                         # PMO 工单预估（F-workorder-cost-rollup，2026-09-06 接入）
            'budget_ratio': warn['budget_ratio'],
            'remaining_cost': warn['remaining_cost'],
            'cost_status': warn['status'],           # 正常 / 预警 / 超支（本体判定）
            'cost_note': warn['note'],
            # ⌛四算未接入：不得用假值填充（见 abox_adapter.not_available）
            'four_calc': {'available': False,
                          'blocked_by': (ABOX_ADAPTER.get('not_available') or {}).get(
                              'four_calc', '四算审批流数据未接入')},
        })
    return out[:limit] if limit else out


def project_portfolio(db: Union[str, sqlite3.Connection],
                      contract_no: Optional[str] = None,
                      status: Optional[str] = None,
                      limit: Optional[int] = 20,
                      offset: int = 0) -> Dict[str, Any]:
    """项目组合查询（★推荐入口）：返回条目 + **全库总数/截断标记/全量预警分布**。

    ★设计要点（2026-09-05 事故修复）：必须区分「样本」与「全集」。此前工具只返回
      limit 截断后的条目，智能体据此回答「共 19 个项目、其中 3 个超支」——
      实际全库 629 个项目、68 个超支，结论严重失真。
      故本函数：total / status_count 一律基于**全量**计算，truncated 明确告知是否截断，
      并给出翻页提示（offset）。

    status : '正常' / '预警' / '超支'（本体 F-project-cost-warning 判定值）筛选。
    limit  : 返回条数（None 表示不限）。offset：偏移量，用于翻页遍历。
    返回  : {'items', 'total'(筛选后全量), 'total_all'(全库), 'returned',
             'offset', 'truncated', 'next_offset', 'status_count'(全库分布)}
    """
    items = project_facts(db, contract_no=contract_no)         # 全量（不截断）
    total_all = len(items)
    status_count_all: Dict[str, int] = {}
    for it in items:
        s = it.get('cost_status')
        status_count_all[s] = status_count_all.get(s, 0) + 1

    if status:
        items = [x for x in items if x.get('cost_status') == status]
    total = len(items)

    page = items[offset:]
    if limit:
        page = page[:limit]
    truncated = (offset + len(page)) < total
    return {
        'items': page,
        'total': total,                    # 筛选后的全量条数
        'total_all': total_all,            # 全库条数（不受筛选影响）
        'returned': len(page),             # 本次实际返回条数
        'offset': offset,
        'truncated': truncated,
        'next_offset': (offset + len(page)) if truncated else None,
        'status_count': status_count_all,  # ★全库分布（非本页分布）
        'filter': {'contract_no': contract_no, 'status': status},
    }


def project_cost_detail(db: Union[str, sqlite3.Connection],
                        contract_no: Optional[str] = None,
                        limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """成本明细：预算三分量 / 成本六分量 + 合计 + 本体预警（★与 9006 同源）。

    分量列名取 COST_FORMULA_POLICY 的 budget.columns / cost.columns（单一真相）。

    ⚠ limit 只截断返回条目；需要「总数/是否截断」请用 project_cost_detail_page。
    """
    return project_cost_detail_page(db, contract_no=contract_no, limit=limit)['items']


def project_cost_detail_page(db: Union[str, sqlite3.Connection],
                             contract_no: Optional[str] = None,
                             limit: Optional[int] = 20,
                             offset: int = 0) -> Dict[str, Any]:
    """成本明细（带 total/truncated 元信息）——同 project_portfolio 的防误判设计。"""
    budget_cols = COST_FORMULA_POLICY["budget"]["columns"]
    cost_cols = COST_FORMULA_POLICY["cost"]["columns"]
    wanted = [ABOX_ADAPTER["key"], ABOX_ADAPTER["name"],
              ABOX_ADAPTER["budget"], ABOX_ADAPTER["current_cost"]]
    wanted += list(budget_cols.values()) + list(cost_cols.values())

    own = False
    if isinstance(db, sqlite3.Connection):
        conn = db
    else:
        conn = sqlite3.connect(db)
        own = True
    try:
        rows = _query_rows(conn, ABOX_ADAPTER["table"], wanted,
                           where_col=ABOX_ADAPTER["key"], where_val=contract_no)
        rollup = workorder_cost_by_project(conn)    # 按项目工单预估（补滞后口径）
    finally:
        if own:
            conn.close()

    out: List[Dict[str, Any]] = []
    seen = set()
    for r in rows:
        cno = str(r.get(ABOX_ADAPTER["key"]) or '').strip()
        if not cno or cno == ABOX_ADAPTER["key"] or cno in seen:
            continue
        seen.add(cno)
        budget_items = {k: _num(r.get(col)) for k, col in budget_cols.items()}
        cost_items = {k: _num(r.get(col)) for k, col in cost_cols.items()}
        budget = _num(r.get(ABOX_ADAPTER["budget"]))
        current_cost = round(_num(r.get(ABOX_ADAPTER["current_cost"])) or 0.0, 2)
        woe = float(rollup.get(cno, 0.0) or 0.0)
        warn = functions.call("F-project-cost-warning", budget=budget,
                              current_cost=current_cost, wo_est_cost=woe)
        out.append({
            'project_id': cno,
            'contract_no': cno,
            'name': str(r.get(ABOX_ADAPTER["name"]) or ''),
            'budget_items': budget_items,        # 硬件集成费 / 服务预估成本 / 软件预估实施费
            'cost_items': cost_items,            # 六分量实际
            'budget': budget,
            'current_cost': current_cost,
            'est_cost': woe,                         # PMO 工单预估（F-workorder-cost-rollup，2026-09-06 接入）
            'budget_ratio': warn['budget_ratio'],
            'remaining_cost': warn['remaining_cost'],
            'cost_status': warn['status'],
            'cost_note': warn['note'],
        })
    total = len(out)
    page = out[offset:]
    if limit:
        page = page[:limit]
    truncated = (offset + len(page)) < total
    return {
        'items': page,
        'total': total,
        'returned': len(page),
        'offset': offset,
        'truncated': truncated,
        'next_offset': (offset + len(page)) if truncated else None,
    }


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
        rollup = workorder_cost_by_project(conn)   # 按项目工单预估（补主数据滞后口径）
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
        woe = float(rollup.get(f['project_no'], 0.0) or 0.0)
        # ★判定统一走本体 F-project-cost-warning（与纯函数/智能体同一份算法）
        res = functions.call(
            "F-project-cost-warning",
            budget=budget,
            current_cost=current_cost,
            wo_est_cost=woe,          # PMO 工单预估（F-workorder-cost-rollup 汇总，2026-09-06 接入）
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


def workorder_cost_by_project(db: Union[str, sqlite3.Connection]) -> Dict[str, float]:
    """读 plm_workorder → 按 project_no 汇总工单预估成本（Σ 自主+差旅+变动）。

    供成本预警把「预估成本」从恒 0 修正为真实 PMO 工单预估（补主数据滞后口径）。
    表/列不存在 → 返回空字典（调用方按 0 处理，退化为滞后口径，不报错）。
    列名取 COST_FORMULA_POLICY.abox_adapter.workorder（单一真相），切源只改声明块。
    """
    wo = COST_FORMULA_POLICY["abox_adapter"].get("workorder")
    if not wo:
        return {}
    own = False
    if isinstance(db, sqlite3.Connection):
        conn = db
    else:
        conn = sqlite3.connect(db)
        own = True
    try:
        table = wo["table"]
        cols = _available_columns(conn, table)
        req = ["project_no", "self_cost", "travel_cost", "variable_cost"]
        if not all(c in cols for c in req):
            return {}
        sql = ('SELECT "%s", COALESCE("%s",0)+COALESCE("%s",0)+COALESCE("%s",0) '
               'FROM "%s" WHERE "%s" IS NOT NULL AND "%s" != \'\''
               % (wo["project_no"], wo["self_cost"], wo["travel_cost"], wo["variable_cost"],
                  table, wo["project_no"], wo["project_no"]))
        out: Dict[str, float] = {}
        for pn, tot in conn.execute(sql).fetchall():
            pk = str(pn)
            out[pk] = round(out.get(pk, 0.0) + float(tot or 0.0), 2)
        return out
    except sqlite3.Error:
        return {}
    finally:
        if own:
            conn.close()


def workorder_cost_portfolio(conn: sqlite3.Connection) -> Dict[str, Any]:
    """F-workorder-cost-rollup 的 ABox 读取层：按项目汇总工单预估成本（供本体页函数运行弹窗）。"""
    rollup = workorder_cost_by_project(conn)
    rows = [{'project_no': pn, 'wo_est_cost': v} for pn, v in rollup.items()]
    total = round(sum(rollup.values()), 2)
    return {
        'total': len(rows),
        'status_count': {},
        'summary': {'项目数': '%d 个' % len(rows), '预估成本合计': '¥%s' % format(round(total), ',')},
        'rows': rows,
    }


#: 函数 → ABox 读取层 注册表（单一真相：只有在此登记的函数才有真实实例数据可读）。
#: 未登记的函数（毛利率 / 回款周期 / ROI …）按红线返回 ⌛未接入，绝不编演示数据。
FUNCTION_ABOX_READERS = {
    'F-project-cost-warning': cost_warning_portfolio,
    'F-workorder-cost-rollup': workorder_cost_portfolio,
}


def _function_abox_status() -> List[Dict[str, Any]]:
    """列出所有计算函数的 ABox 可用性，供前端「函数选择器」渲染。

    每个函数声明 produces_for（产出归属实体）；有读取层 → abox_available=True。
    """
    out: List[Dict[str, Any]] = []
    for fid in functions.ids():
        fn = functions.get(fid)
        if not fn:
            continue
        produces = getattr(fn, 'produces_for', None) or []
        out.append({
            'id': fid,
            'name': getattr(fn, 'name', fid),
            'category': getattr(fn, 'category', ''),
            'produces_for': list(produces),
            'entity': produces[0] if produces else None,
            'abox_available': fid in FUNCTION_ABOX_READERS,
        })
    return out


def function_abox_view(db: Union[str, sqlite3.Connection],
                       function_id: str) -> Dict[str, Any]:
    """某函数的 ABox 实例视图：读该函数作用的实体实例 → 逐条调本体函数 → 返回判定。

    - 有读取层（如 F-project-cost-warning）→ 跑全量实例，返回逐条 output + 分布。
    - 无读取层 → 按红线返回 available=False + 原因（不编数据）。
    """
    own = False
    if isinstance(db, sqlite3.Connection):
        conn = db
    else:
        conn = sqlite3.connect(db)
        own = True
    try:
        fn = functions.get(function_id)
        if not fn:
            return {'available': False, 'function': function_id,
                    'error': 'unknown_function', 'rows': []}
        produces = getattr(fn, 'produces_for', None) or []
        entity = produces[0] if produces else None
        reader = FUNCTION_ABOX_READERS.get(function_id)
        if not reader:
            return {
                'available': False,
                'function': function_id,
                'name': getattr(fn, 'name', function_id),
                'entity': entity,
                'reason': ('%s 的 ABox 读取层尚未接入（当前真实实例数据仅来自 md_contract，'
                           '仅成本预警类函数可用）。数据源接入后自动可用，不返回演示数据。'
                           % function_id),
                'rows': [],
            }
        pf = reader(conn)
        rows = [{
            'key': (r.get('contract_no') or r.get('project_no')),
            'label': (r.get('name') or r.get('contract_no') or r.get('project_no')),
            'inputs': {'budget': r.get('budget'), 'current_cost': r.get('current_cost')},
            'output': {k: r.get(k) for k in ('status', 'budget_ratio', 'remaining',
                                             'estimate', 'est_cost', 'effective_cost', 'note')},
        } for r in pf.get('rows', [])]
        return {
            'available': True,
            'function': function_id,
            'name': getattr(fn, 'name', function_id),
            'entity': entity,
            'total': pf.get('total'),
            'status_count': pf.get('status_count'),
            'summary': pf.get('summary'),
            'rows': rows,
        }
    finally:
        if own:
            conn.close()


def _list_tables(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """枚举业务库内全部数据表（不含 sqlite 内部表）：表名 / 行数 / 列数列表。

    用于 ABox 可观测：回答「库里到底有哪些表」，而非只盯 abox_adapter 声明的主表。
    """
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            " ORDER BY name").fetchall()]
    except sqlite3.Error:
        return []
    out: List[Dict[str, Any]] = []
    for t in names:
        try:
            rc = conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
        except sqlite3.Error:
            rc = 0
        cols = sorted(_available_columns(conn, t))
        out.append({'name': t, 'row_count': rc, 'column_count': len(cols), 'columns': cols})
    return out


def _base_sample(conn: sqlite3.Connection, table: str, limit: int) -> List[Dict[str, Any]]:
    """中性基底实例样本：仅取 abox_adapter 已映射的原始字段，**不含任何函数派生输出**。

    与 project_facts/cost_warning_portfolio 的区别：这里不调本体函数、不附 cost_status，
    纯粹呈现「ABox 基底个体长什么样」，避免把某一函数的派生结果固化进 ABox 总览。
    """
    prof = ABOX_ADAPTER.get('profile') or {}
    wanted = [ABOX_ADAPTER.get('key', ''), ABOX_ADAPTER.get('name', ''),
              ABOX_ADAPTER.get('budget', ''), ABOX_ADAPTER.get('current_cost', '')]
    wanted += [prof.get(k, '') for k in ('dept', 'owner', 'region', 'status', 'amount')]
    wanted = [w for w in wanted if w]
    rows = _query_rows(conn, table, wanted, limit=limit)
    key_c = ABOX_ADAPTER.get('key', '')
    name_c = ABOX_ADAPTER.get('name', '') or ''
    bud_c = ABOX_ADAPTER.get('budget', '')
    cur_c = ABOX_ADAPTER.get('current_cost', '')
    return [{
        'contract_no': str(r.get(key_c) or ''),
        'name': str(r.get(name_c) or ''),
        'dept': r.get(prof.get('dept', '') or '') or '',
        'owner': r.get(prof.get('owner', '') or '') or '',
        'region': r.get(prof.get('region', '') or '') or '',
        'status': r.get(prof.get('status', '') or '') or '',
        'amount': _num(r.get(prof.get('amount', '') or '')),
        'budget': _num(r.get(bud_c)),
        'current_cost': round(_num(r.get(cur_c)) or 0.0, 2),
    } for r in rows]


def abox_report(db: Union[str, sqlite3.Connection],
                function: Optional[str] = None,
                sample_limit: int = 20) -> Dict[str, Any]:
    """ABox 实例概览（★本体可观测）：把 TBox 实体绑定到物理表实例，给出可观测指标。

    回答「看得到 TBox 但看不到 ABox」——渲染**实例基座**（基底个体，独立于任何函数）：
    1) 全部数据表枚举（库里有哪些表、各自行数/列数）—— 不再只盯 abox_adapter 主表
    2) abox_adapter 绑定映射（本体属性→物理表.列，标存在性+非空率，按实体归属）—— 单一真相可视化
    3) 实体→字段映射浏览器所需数据（tables + bindings.entity）
    4) 中性基底实例样本（仅原始映射字段，**不含函数派生**）
    5) 未接入数据域（⌛not_available）

    ※ 函数派生结果（如成本预警判定）**不属于**本总览，改由 TBox 点函数「运行/预览」弹窗查看。
    纯读、无副作用；表不存在/库缺失时优雅返回 status(空) 而非 500。
    9006 本体页 /api/ontos/abox 与 9007 智能体共用同一份实现（同源）。
    """
    own = False
    if isinstance(db, sqlite3.Connection):
        conn = db
    else:
        conn = sqlite3.connect(db)
        own = True
    try:
        table = ABOX_ADAPTER["table"]
        cols = _available_columns(conn, table)
        table_exists = len(cols) > 0
        raw_count = 0
        if table_exists:
            raw_count = conn.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
        # 去重实例（与 project_facts 口径一致：跳过表头/空/重复）
        instances = _load_project_rows(conn)
        instance_count = len(instances)

        def _col_stat(col: str) -> Dict[str, Any]:
            exists = col in cols
            non_null = 0
            if exists:
                non_null = conn.execute(
                    'SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL AND "%s" != \'\''
                    % (table, col, col)).fetchone()[0]
            return {'col': col, 'exists': exists, 'non_null': non_null,
                    'non_null_rate': (round(non_null / raw_count, 4) if raw_count else 0.0)}

        # abox_adapter 绑定映射（单一真相可视化）：当前仅 Project（成本）实体有物理绑定
        bindings: List[Dict[str, Any]] = []
        def _add_binding(prop: str, col: str, entity: str = 'Project') -> None:
            if not col:
                return
            s = _col_stat(col)
            s['property'] = prop
            s['entity'] = entity
            bindings.append(s)
        _add_binding('key', ABOX_ADAPTER.get('key'))
        _add_binding('name', ABOX_ADAPTER.get('name'))
        _add_binding('budget', ABOX_ADAPTER.get('budget'))
        _add_binding('current_cost', ABOX_ADAPTER.get('current_cost'))
        _add_binding('project_no', ABOX_ADAPTER.get('project_no'))
        for fld, c in (ABOX_ADAPTER.get('profile') or {}).items():
            _add_binding('profile.' + fld, c)
        for fld, c in COST_FORMULA_POLICY["budget"]["columns"].items():
            _add_binding('budget.' + fld, c)
        for fld, c in COST_FORMULA_POLICY["cost"]["columns"].items():
            _add_binding('cost.' + fld, c)

        # 中性基底实例样本（仅原始映射字段，不含任何函数派生输出）
        base_sample: List[Dict[str, Any]] = _base_sample(conn, table, sample_limit)

        not_avail = ABOX_ADAPTER.get('not_available') or {}
        result = {
            'success': True,
            'source': 'ontos.abox_cost.abox_report',
            'db': {
                'path': db if isinstance(db, str) else '(connection)',
                'file_exists': (isinstance(db, str) and os.path.exists(db)),
                'table': table,
                'table_exists': table_exists,
                'raw_row_count': raw_count,
                'instance_count': instance_count,
            },
            'tables': _list_tables(conn),
            'bindings': bindings,
            'base_sample': base_sample,
            'base_sample_limit': sample_limit,
            'not_available': [{'domain': k, 'reason': v} for k, v in not_avail.items()],
            # 函数选择器数据源：列出所有计算函数及其 ABox 可用性（驱动 TBox 函数运行弹窗）
            'functions': _function_abox_status(),
        }
        if function:
            result['function_view'] = function_abox_view(conn, function)
        return result
    finally:
        if own:
            conn.close()
