# -*- coding: utf-8 -*-
"""离线规划器：把问题解析为查询计划（不依赖大模型也能给出正确 SQL）。

三种计划：
  metric    —— 指标型问题，走"指标元数据 + 维度 + 过滤"组合
  trend     —— 趋势型问题，按月中循环取数组成序列
  archive   —— 项目档案，多块结构化信息
  lag/risk  —— 复杂分析模板（进度滞后、风险项目）
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app import db, metrics as M
from app.config import DB_PATH
from app.nl2sql import lexicon as L

_PROJECTS: List[Dict[str, Any]] = []


def load_projects(force: bool = False) -> List[Dict[str, Any]]:
    global _PROJECTS
    if _PROJECTS and not force:
        return _PROJECTS
    conn = db.get_conn()
    rows = conn.execute("""
        SELECT P.PROJ_CODE, P.PROJ_NAME, P.ORG_ID, O.ORG_NAME, P.PM_STAFF_ID, S.STAFF_NAME AS PM_NAME,
               P.PROJ_TYPE, P.PROJ_STATUS, P.START_DATE, P.END_DATE, P.CITY, P.PROVINCE,
               P.CONTRACT_AMT, E.ENG_TYPE, E.CAPACITY_MW, E.VOLTAGE_KV, E.IS_EPC,
               CU.CUSTOMER_NAME, P.CUSTOMER_ID
        FROM DIM_PROJECT P
        LEFT JOIN DIM_ORG O ON O.ORG_ID = SUBSTR(P.ORG_ID, 1, 4)
        LEFT JOIN DIM_STAFF S ON S.STAFF_ID = P.PM_STAFF_ID
        LEFT JOIN DIM_PROJECT_EXT E ON E.PROJ_CODE = P.PROJ_CODE
        LEFT JOIN DIM_CUSTOMER CU ON CU.CUSTOMER_ID = P.CUSTOMER_ID
    """).fetchall()
    conn.close()
    _PROJECTS = [dict(r) for r in rows]
    return _PROJECTS


def find_projects(q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """在问题中识别项目：编码 > 全名 > 名称长片段 > 城市+专业组合。"""
    projects = load_projects()
    # 1) 项目编码
    m = re.search(r"(GD\d{4}-\d{4})", q, re.I)
    if m:
        code = m.group(1).upper()
        return [p for p in projects if p["PROJ_CODE"] == code]
    # 2) 全名包含
    hits = [p for p in projects if p["PROJ_NAME"] in q]
    if hits:
        return hits[:limit]
    # 3) 名称片段（≥6 字）
    hits = []
    for p in projects:
        name = p["PROJ_NAME"]
        for size in (10, 8, 6):
            frag = name[:size]
            if len(frag) >= 6 and frag in q:
                hits.append(p)
                break
    if hits:
        return hits[:limit]
    # 4) 城市 + 专业
    city = next((c for c in L.CITIES if c in q), None)
    eng = next((e for e in L.ENG_TYPES if e in q), None)
    if city and eng:
        hits = [p for p in projects if p["CITY"] == city and p["ENG_TYPE"] == eng]
        if hits:
            return sorted(hits, key=lambda p: len(p["PROJ_NAME"]))[:limit]
    return []


def detect_order(q: str) -> bool:
    """True = 降序（最高/最多），False = 升序（最低/最少）。"""
    return not bool(re.search(r"(最低|最少|最差|倒数|垫底)", q))


def is_lag_question(q: str) -> bool:
    return bool(re.search(r"(进度滞后|滞后|延期|拖期|落后|偏差大|未达计划)", q))


def is_risk_question(q: str) -> bool:
    return bool(re.search(r"(风险项目|高风险|风险事项.*项目|超期.*项目)", q))


def plan_metric(q: str, user: Optional[dict] = None) -> Dict[str, Any]:
    """指标型问题的查询计划。"""
    kpi = L.find_kpi(q)
    if not kpi:
        return {"kind": "unsupported", "reason": "未识别到已登记的指标"}

    period = L.parse_time(q)
    ctx = M.period_ctx(period["start"], period["end"])
    shape = L.find_shape(q)
    filters = [(d, op, v) for d, op, v in L.detect_filters(q) if not d.startswith("__")]
    dims = [d for d in L.find_dims(q) if d not in ("PROVINCE",)]
    if kpi == "CZ_PROJ_ACTIVE" and "PROJ" in dims:
        dims.remove("PROJ")

    # 维度与过滤互斥：已按某分公司过滤时，不再按分公司分组
    for d, _, _ in filters:
        if d in dims:
            dims.remove(d)

    limit = None
    order_desc = detect_order(q)
    if shape == "rank":
        if not dims:
            # "危大工程最多的5个项目" 这类问题按项目排序，而非按分公司
            dims = ["PROJ"] if (re.search(r"项目|工程", q) and kpi != "CZ_PROJ_ACTIVE") else ["ORG"]
        limit = L.find_topn(q) or 10
    elif shape == "share" and not dims:
        dims = ["ORG"]
    elif shape == "list":
        if re.search(r"项目|工程", q) and "ORG" not in dims and "DEPT" not in dims:
            dims = ["PROJ"]
        elif not dims:
            dims = ["ORG"]
        limit = limit or 20
    elif shape == "trend":
        return plan_trend(q, kpi, period, filters)

    # "各分公司"未显式写成"按分公司"时补维度
    if not dims and re.search(r"(各|按|分)分公司", q):
        dims = ["ORG"]

    sql = M.metric_sql(kpi, ctx, dims, filters, limit, order_desc=order_desc)
    return {
        "kind": "metric",
        "sql": sql,
        "kpi": kpi,
        "kpi_name": M.METRICS[kpi]["name"],
        "unit": M.METRICS[kpi]["unit"],
        "dims": dims,
        "dim_names": [L.DIM_NAMES.get(d, d) for d in dims],
        "filters": filters,
        "period": period,
        "shape": shape,
        "limit": limit,
        "order_desc": order_desc,
    }


def plan_trend(q: str, kpi: str, period: dict, filters: List[Tuple]) -> Dict[str, Any]:
    """趋势：逐月取数，组成时间序列（月度事实口径）。"""
    months = period["months"]
    if len(months) < 2:
        months = L._months_between("2026-05", "2026-10")
    points = []
    for m in months:
        try:
            v = M.metric_value(kpi, M.period_ctx(m + "-01", _month_end(m)), filters)
        except Exception:
            v = None
        points.append({"label": m, "value": v})
    sql = M.metric_sql(kpi, M.period_ctx(months[0] + "-01", _month_end(months[-1])), [], filters)
    return {
        "kind": "trend",
        "sql": sql,
        "kpi": kpi,
        "kpi_name": M.METRICS[kpi]["name"],
        "unit": M.METRICS[kpi]["unit"],
        "points": points,
        "dims": [],
        "dim_names": [],
        "filters": filters,
        "period": {"start": months[0] + "-01", "end": _month_end(months[-1]),
                   "label": "至".join([months[0], months[-1]]), "months": months, "kind": "trend"},
        "shape": "trend",
    }


def _month_end(ym: str) -> str:
    from calendar import monthrange
    y, m = int(ym[:4]), int(ym[5:7])
    return "%s-%02d" % (ym, monthrange(y, m)[1])


def plan_archive(proj: Dict[str, Any]) -> Dict[str, Any]:
    """项目档案：主档 + 指标聚合，一次返回结构化卡片。"""
    code = proj["PROJ_CODE"]
    sql = ("SELECT P.PROJ_CODE AS 项目编码, P.PROJ_NAME AS 项目名称, O.ORG_NAME AS 所属分公司, "
           "S.STAFF_NAME AS 项目经理, CU.CUSTOMER_NAME AS 业主, P.PROJ_TYPE AS 项目等级, "
           "P.PROJ_STATUS AS 项目状态, P.START_DATE AS 开工日期, P.END_DATE AS 计划完工, "
           "P.PROVINCE AS 省份, P.CITY AS 地市, P.CONTRACT_AMT AS 合同额_万元, "
           "E.ENG_TYPE AS 工程类型, E.CAPACITY_MW AS 装机容量_MW, E.VOLTAGE_KV AS 电压等级_kV, "
           "E.IS_EPC AS 是否总承包 "
           "FROM DIM_PROJECT P "
           "LEFT JOIN DIM_ORG O ON O.ORG_ID = SUBSTR(P.ORG_ID,1,4) "
           "LEFT JOIN DIM_STAFF S ON S.STAFF_ID = P.PM_STAFF_ID "
           "LEFT JOIN DIM_CUSTOMER CU ON CU.CUSTOMER_ID = P.CUSTOMER_ID "
           "LEFT JOIN DIM_PROJECT_EXT E ON E.PROJ_CODE = P.PROJ_CODE "
           "WHERE P.PROJ_CODE = '%s'" % code)
    ctx = M.period_ctx("2026-01-01", "2026-10-31")
    stats = []
    for kpi in ("SR_OPERATE", "HK_AMT", "HK_AR_BAL", "CZ_OUTPUT", "AQ_HAZARD_CNT"):
        try:
            stats.append({"kpi": M.METRICS[kpi]["name"], "unit": M.METRICS[kpi]["unit"],
                          "value": M.metric_value(kpi, ctx, [("PROJ", "=", code)])})
        except Exception:
            pass
    return {"kind": "archive", "sql": sql, "project": proj, "stats": stats,
            "period": {"label": "2026年1-10月", "start": "2026-01-01", "end": "2026-10-31",
                       "months": [], "kind": "year"}}


def plan_lag(period: dict, filters: List[Tuple]) -> Dict[str, Any]:
    """进度滞后项目：实际产值显著低于计划产值。"""
    ctx = M.period_ctx(period["start"], period["end"])
    conds = ""
    for d, op, v in filters:
        if d in ("PROVINCE", "CITY", "ORG", "ENG_TYPE", "PROJ_TYPE"):
            expr = M.DIMS[d]["expr"]
            if op == "!=":
                conds += " AND %s <> '%s'" % (expr, v)
            else:
                conds += " AND %s = '%s'" % (expr, v)
    ext = " LEFT JOIN DIM_PROJECT_EXT E ON E.PROJ_CODE = P.PROJ_CODE" \
        if "ENG_TYPE" in [d for d, _, _ in filters] else ""
    sql = """SELECT * FROM (
  SELECT P.PROJ_NAME AS 项目名称, O.ORG_NAME AS 分公司, P.PROJ_TYPE AS 等级,
         ROUND(G.OUT,2) AS 实际产值_万元, ROUND(G.PLAN,2) AS 计划产值_万元,
         ROUND(100*G.OUT/NULLIF(G.PLAN,0),1) AS 完成率_百分比,
         ROUND(G.PLAN-G.OUT,2) AS 缺口_万元
  FROM (SELECT PROJ_CODE, SUM(OUTPUT_AMT) AS OUT, SUM(PLAN_OUTPUT_AMT) AS PLAN
        FROM FACT_PROGRESS WHERE PERIOD BETWEEN '%s'
        GROUP BY PROJ_CODE) G
  JOIN DIM_PROJECT P ON P.PROJ_CODE = G.PROJ_CODE
  LEFT JOIN DIM_ORG O ON O.ORG_ID = SUBSTR(P.ORG_ID,1,4)%s
  WHERE P.PROJ_STATUS = '在建' AND G.OUT < G.PLAN * 0.95%s
  ORDER BY 缺口_万元 DESC
) WHERE ROWNUM <= 10""" % (ctx["mon"], ext, conds)
    return {"kind": "lag", "sql": sql, "kpi": "CZ_FINISH_RATE", "kpi_name": "产值完成率",
            "unit": "%", "dims": ["PROJ"], "dim_names": ["项目"], "filters": filters,
            "period": period, "shape": "rank"}


def plan_risk(period: dict) -> Dict[str, Any]:
    """高风险/超期项目清单。"""
    ctx = M.period_ctx(period["start"], period["end"])
    sql = """SELECT * FROM (
  SELECT P.PROJ_NAME AS 项目名称, O.ORG_NAME AS 分公司, R.RISK_TYPE AS 风险类型,
         R.RISK_LEVEL AS 风险等级, R.FOUND_DATE AS 发现日期, R.STATUS AS 状态,
         DAYS_BETWEEN('{end}', R.FOUND_DATE) AS 持续天数
  FROM FACT_RISK R
  JOIN DIM_PROJECT P ON P.PROJ_CODE = R.PROJ_CODE
  LEFT JOIN DIM_ORG O ON O.ORG_ID = SUBSTR(P.ORG_ID,1,4)
  WHERE R.STATUS = '跟踪中'
  ORDER BY 持续天数 DESC
) WHERE ROWNUM <= 10""".replace('{end}', ctx["end"])
    return {"kind": "risk", "sql": sql, "kpi": "AQ_RISK_CNT", "kpi_name": "风险事项数",
            "unit": "个", "dims": ["PROJ"], "dim_names": ["项目"], "filters": [],
            "period": period, "shape": "list"}


def compose_explain(plan: Dict[str, Any]) -> str:
    """把查询计划翻译成一句业务语言，用于向用户解释"我理解成了什么"。"""
    if plan["kind"] == "metric":
        dims = "、".join(plan["dim_names"]) or "全院合计"
        extra = ""
        if plan["filters"]:
            extra = "，过滤条件：" + "；".join(
                "%s%s%s" % (L.DIM_NAMES.get(d, d), "不包含" if op == "!=" else "=", v)
                for d, op, v in plan["filters"])
        return "指标：%s；维度：%s；期间：%s%s" % (
            plan["kpi_name"], dims, plan["period"]["label"], extra)
    if plan["kind"] == "trend":
        return "指标：%s；形态：逐月趋势（%s）" % (plan["kpi_name"], plan["period"]["label"])
    if plan["kind"] == "archive":
        return "项目档案：%s（%s）" % (plan["project"]["PROJ_NAME"], plan["project"]["PROJ_CODE"])
    if plan["kind"] == "lag":
        return "分析模板：在建项目产值完成率低于计划 5%% 的滞后项目；期间：%s" % plan["period"]["label"]
    if plan["kind"] == "risk":
        return "分析模板：当前仍在跟踪的风险事项（按时长排序）"
    return "未识别"
