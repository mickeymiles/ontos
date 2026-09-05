# -*- coding: utf-8 -*-
"""ABox 成本适配层测试（ontos.abox_cost：9006 / 9007 同源入口）。

用临时 SQLite 模拟 md_contract（物理列取 COST_FORMULA_POLICY.abox_adapter 声明），
验证：事实构造（去重/脏行跳过/缺省 project_no）、组合计算（判定/汇总）、
单项目查询、容错（表缺失）。
"""
import os
import sys
import sqlite3
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ontos import abox_cost
from ontos.domain_business import COST_FORMULA_POLICY

AB = COST_FORMULA_POLICY["abox_adapter"]


@pytest.fixture
def db_path(tmp_path):
    """临时业务库：建 md_contract 并灌入覆盖各判定分支的数据。"""
    p = str(tmp_path / "biz.db")
    conn = sqlite3.connect(p)
    conn.execute(
        f'CREATE TABLE md_contract ("{AB["key"]}" TEXT, "{AB["name"]}" TEXT,'
        f' "{AB["budget"]}" REAL, "{AB["current_cost"]}" REAL)')
    rows = [
        # (合同编号, 项目描述, 预算, 当前成本)
        ('NORMAL001', '正常项目', 200000, 100000),   # 完成比 50% → 正常
        ('WARN001', '预警项目', 100000, 95000),      # 完成比 95% → 预警
        ('OVER001', '超支项目', 100000, 120000),     # 完成比 120% → 超支
        ('NOBUD001', '无预算有成本', None, 50000),   # 缺预算 → 正常(不可判)
        ('NODATA001', '无任何数据', None, None),     # 无预算且无成本 → 不纳入
        ('合同编号', '表头混入数据的脏行', 1, 1),     # 脏行 → 跳过
        ('NORMAL001', '重复合同首行保留', 999999, 999999),  # 重复 → 保留首行
        ('', '空合同号', 1, 1),                      # 空键 → 跳过
    ]
    conn.executemany(
        f'INSERT INTO md_contract ("{AB["key"]}", "{AB["name"]}", '
        f'"{AB["budget"]}", "{AB["current_cost"]}") VALUES (?,?,?,?)', rows)
    conn.commit()
    conn.close()
    return p


def test_facts_dedupe_and_dirty_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        facts = abox_cost.project_cost_facts(conn)
    finally:
        conn.close()
    nos = [f['contract_no'] for f in facts]
    # 脏行（表头文本/空号）跳过、重复保留首行、无数据行保留（纳入与否由组合层判）
    assert nos == ['NORMAL001', 'WARN001', 'OVER001', 'NOBUD001', 'NODATA001']
    first = facts[0]
    assert first['budget'] == 200000 and first['current_cost'] == 100000
    assert first['name'] == '正常项目'
    # 源表无独立项目号列 → project_no 缺省 = 合同编号
    assert first['project_no'] == 'NORMAL001'


def test_facts_missing_table(tmp_path):
    conn = sqlite3.connect(str(tmp_path / 'empty.db'))
    try:
        assert abox_cost.project_cost_facts(conn) == []
    finally:
        conn.close()


def test_portfolio(db_path):
    r = abox_cost.cost_warning_portfolio(db_path)
    # NODATA001（无预算无成本）不纳入 → total=4
    assert r['total'] == 4
    assert r['status_count'] == {'正常': 2, '预警': 1, '超支': 1}
    # 汇总：预算 = 200000+100000+100000（NOBUD001 无预算不计入）；成本 = 100000+95000+120000+50000
    assert r['total_budget'] == 400000
    assert r['total_current_cost'] == 365000
    assert r['total_remaining'] == 35000
    # 行契约（页面同构）
    row = next(x for x in r['rows'] if x['contract_no'] == 'OVER001')
    assert row['status'] == '超支'
    assert row['estimate'] is None          # 概算 ⌛预留
    assert row['est_cost'] == 0            # 工单预估未落地
    assert row['effective_cost'] == 120000
    assert row['remaining'] == -20000
    assert row['budget_ratio'] == 1.2
    # 重复行未污染（保留首行 200000/100000，而非 999999）
    normal = next(x for x in r['rows'] if x['contract_no'] == 'NORMAL001')
    assert normal['budget'] == 200000 and normal['current_cost'] == 100000
    # summary 中文键齐全
    assert set(r['summary']) == {'项目数', '预算金额合计', '当前成本合计',
                                 '预估成本合计', '剩余成本合计', '超支项目', '预警项目'}


def test_portfolio_single_contract(db_path):
    r = abox_cost.cost_warning_portfolio(db_path, contract_no='WARN001')
    assert r['total'] == 1
    assert r['status_count'] == {'正常': 0, '预警': 1, '超支': 0}
    assert r['rows'][0]['status'] == '预警'
    assert r['rows'][0]['name'] == '预警项目'


def test_portfolio_accepts_conn(db_path):
    conn = sqlite3.connect(db_path)
    try:
        r = abox_cost.cost_warning_portfolio(conn)
    finally:
        conn.close()
    assert r['total'] == 4


def test_abox_adapter_declared_in_policy():
    # 物理列绑定必须在 COST_FORMULA_POLICY（单一真相）里声明
    for k in ('table', 'key', 'name', 'budget', 'current_cost'):
        assert AB.get(k), f'abox_adapter 缺 {k}'
    assert AB['table'] == 'md_contract'


# ── 项目档案 / 成本明细（智能体「项目管理专家」数据源）────────────


@pytest.fixture
def profile_db(tmp_path):
    """含档案列与成本分量列的临时库"""
    p = str(tmp_path / "profile.db")
    conn = sqlite3.connect(p)
    cols = [AB["key"], AB["name"], AB["budget"], AB["current_cost"],
            AB["profile"]["dept"], AB["profile"]["owner"], AB["profile"]["region"],
            AB["profile"]["status"], AB["profile"]["amount"]]
    cols += list(COST_FORMULA_POLICY["budget"]["columns"].values())
    cols += list(COST_FORMULA_POLICY["cost"]["columns"].values())
    conn.execute('CREATE TABLE md_contract (%s)' %
                 ','.join('"%s" TEXT' % c for c in cols))
    vals = {AB["key"]: 'CSZB2211422A', AB["name"]: '某集成项目',
            AB["budget"]: 100000, AB["current_cost"]: 120000,
            AB["profile"]["dept"]: '大客户部', AB["profile"]["owner"]: '张三',
            AB["profile"]["region"]: '华北', AB["profile"]["status"]: '执行中',
            AB["profile"]["amount"]: 500000}
    vals.update({c: 10000 for c in COST_FORMULA_POLICY["budget"]["columns"].values()})
    vals.update({c: 20000 for c in COST_FORMULA_POLICY["cost"]["columns"].values()})
    conn.execute('INSERT INTO md_contract (%s) VALUES (%s)' % (
        ','.join('"%s"' % c for c in cols), ','.join('?' * len(cols))),
        [vals[c] for c in cols])
    conn.commit()
    conn.close()
    return p


def test_project_facts(profile_db):
    rows = abox_cost.project_facts(profile_db)
    assert len(rows) == 1
    r = rows[0]
    # 兼容智能体工具契约：project_id = 合同编号
    assert r['project_id'] == 'CSZB2211422A' == r['contract_no']
    assert r['name'] == '某集成项目'
    assert r['dept'] == '大客户部' and r['owner'] == '张三' and r['region'] == '华北'
    assert r['status'] == '执行中' and r['amount'] == 500000
    # 预算/成本 + 本体预警判定
    assert r['budget'] == 100000 and r['current_cost'] == 120000
    assert r['cost_status'] == '超支' and r['budget_ratio'] == 1.2
    # ⌛四算未接入：不得用假值填充
    assert r['four_calc']['available'] is False
    assert '四算' in r['four_calc']['blocked_by']


def test_project_facts_single(profile_db):
    assert abox_cost.project_facts(profile_db, contract_no='NOPE') == []
    assert len(abox_cost.project_facts(profile_db, contract_no='CSZB2211422A')) == 1


def test_project_cost_detail(profile_db):
    rows = abox_cost.project_cost_detail(profile_db)
    r = rows[0]
    # 分量列名取 COST_FORMULA_POLICY（单一真相）
    assert set(r['budget_items']) == set(COST_FORMULA_POLICY["budget"]["columns"])
    assert set(r['cost_items']) == set(COST_FORMULA_POLICY["cost"]["columns"])
    assert all(v == 10000 for v in r['budget_items'].values())
    assert all(v == 20000 for v in r['cost_items'].values())
    assert r['cost_status'] == '超支'


def test_not_available_no_fake_data():
    """★红线：未接入的数据域必须显式声明未接入，不得返回演示/估算数据"""
    r = abox_cost.not_available('workhour')
    assert r['available'] is False
    assert r['domain'] == 'workhour'
    assert '工时' in r['blocked_by']
    assert '不做估算' in r['message']
    assert abox_cost.not_available('task')['available'] is False
