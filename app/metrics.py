# -*- coding: utf-8 -*-
"""指标层：7 大类 28 个经营指标的口径定义 + 动态 SQL 抽取 + 指标宽表构建。

每个指标登记三样东西：
  EXPR  —— 聚合表达式（Oracle 11g 语法）
  FROM  —— 取数涉及的表与连接
  WHERE —— 期间与业务过滤条件

宽表 FACT_KPI_WIDE 的一列对应一个指标，由 ensure_wide_columns() 动态扩展，
因此"新增一个指标"只需要登记元数据，不需要改表结构和抽取代码。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from app import db
from app.config import DB_PATH

CATEGORIES = {
    "CAT_CONTRACT": "合同类",
    "CAT_REVENUE": "收入类",
    "CAT_PROFIT": "利润类",
    "CAT_CASH": "回款与两金类",
    "CAT_OUTPUT": "产值履约类",
    "CAT_RISK": "安全风险类",
    "CAT_EFF": "效率人力类",
}

# 维度登记表：expr 用于 GROUP BY，label 用于展示，join 为附加连接
DIMS: Dict[str, Dict[str, str]] = {
    "ORG": {"name": "分公司", "expr": "SUBSTR(P.ORG_ID,1,4)",
            "join": "JOIN DIM_ORG O ON O.ORG_ID = SUBSTR(P.ORG_ID,1,4)", "label": "O.ORG_NAME"},
    "DEPT": {"name": "部门", "expr": "P.ORG_ID",
             "join": "JOIN DIM_ORG O2 ON O2.ORG_ID = P.ORG_ID", "label": "O2.ORG_NAME"},
    "PROJ_TYPE": {"name": "项目等级", "expr": "P.PROJ_TYPE", "join": "", "label": "P.PROJ_TYPE"},
    "ENG_TYPE": {"name": "工程类型", "expr": "E.ENG_TYPE", "join": "",
                 "label": "E.ENG_TYPE"},
    "CUSTOMER": {"name": "业主", "expr": "P.CUSTOMER_ID",
                 "join": "LEFT JOIN DIM_CUSTOMER CU ON CU.CUSTOMER_ID = P.CUSTOMER_ID",
                 "label": "CU.CUSTOMER_NAME"},
    "CITY": {"name": "地市", "expr": "P.CITY", "join": "", "label": "P.CITY"},
    "PROVINCE": {"name": "省份", "expr": "P.PROVINCE", "join": "", "label": "P.PROVINCE"},
    "PM": {"name": "项目经理", "expr": "P.PM_STAFF_ID",
           "join": "LEFT JOIN DIM_STAFF SM ON SM.STAFF_ID = P.PM_STAFF_ID",
           "label": "SM.STAFF_NAME"},
    "STATUS": {"name": "项目状态", "expr": "P.PROJ_STATUS", "join": "", "label": "P.PROJ_STATUS"},
    "PROJ": {"name": "项目", "expr": "P.PROJ_CODE", "join": "", "label": "P.PROJ_NAME"},
}

_EXT_JOIN = "LEFT JOIN DIM_PROJECT_EXT E ON E.PROJ_CODE = P.PROJ_CODE"
_REV = ("(SELECT PROJ_CODE, PERIOD, SUM(AMT) AS AMT FROM FACT_REVENUE "
        "WHERE PERIOD BETWEEN '{mon}' GROUP BY PROJ_CODE, PERIOD) V")
_COST = ("(SELECT PROJ_CODE, PERIOD, SUM(AMT) AS AMT FROM FACT_COST "
         "GROUP BY PROJ_CODE, PERIOD) K")
_PROFIT_FROM = ("{rev} LEFT JOIN {cost} ON K.PROJ_CODE = V.PROJ_CODE AND K.PERIOD = V.PERIOD "
                "JOIN DIM_PROJECT P ON P.PROJ_CODE = V.PROJ_CODE")

METRICS: Dict[str, Dict[str, Any]] = {
    # ---------------- 合同类 ----------------
    "HS_NEW_AMT": {
        "name": "新签合同额", "cat": "CAT_CONTRACT", "unit": "万元",
        "expr": "NVL(SUM(C.AMT),0)", "fmt": "amount",
        "from": "FACT_CONTRACT C JOIN DIM_PROJECT P ON P.PROJ_CODE = C.PROJ_CODE",
        "where": "C.SIGN_DATE BETWEEN TO_DATE('{start}','YYYY-MM-DD') AND TO_DATE('{end}','YYYY-MM-DD') AND NVL(C.CHANGE_FLAG,0)=0",
    },
    "HS_CHARGE_SIGN": {
        "name": "收费合同签订额", "cat": "CAT_CONTRACT", "unit": "万元",
        "expr": "NVL(SUM(C.AMT),0)", "fmt": "amount",
        "from": "FACT_CONTRACT C JOIN DIM_PROJECT P ON P.PROJ_CODE = C.PROJ_CODE",
        "where": "C.SIGN_DATE BETWEEN TO_DATE('{start}','YYYY-MM-DD') AND TO_DATE('{end}','YYYY-MM-DD') AND C.IS_CHARGE = 1",
    },
    "HS_SIGNIN": {
        "name": "签入合同额", "cat": "CAT_CONTRACT", "unit": "万元",
        "expr": "NVL(SUM(C.AMT),0)", "fmt": "amount",
        "from": "FACT_CONTRACT C JOIN DIM_PROJECT P ON P.PROJ_CODE = C.PROJ_CODE",
        "where": "C.SIGN_DATE BETWEEN TO_DATE('{start}','YYYY-MM-DD') AND TO_DATE('{end}','YYYY-MM-DD') AND C.IS_SIGNIN = 1",
    },
    "HS_CHANGE_AMT": {
        "name": "合同变更额", "cat": "CAT_CONTRACT", "unit": "万元",
        "expr": "NVL(SUM(C.AMT),0)", "fmt": "amount",
        "from": "FACT_CONTRACT C JOIN DIM_PROJECT P ON P.PROJ_CODE = C.PROJ_CODE",
        "where": "C.SIGN_DATE BETWEEN TO_DATE('{start}','YYYY-MM-DD') AND TO_DATE('{end}','YYYY-MM-DD') AND C.CHANGE_FLAG = 1",
    },
    "HS_AVG_UNIT": {
        "name": "单体合同均值", "cat": "CAT_CONTRACT", "unit": "万元/个",
        "expr": "ROUND(NVL(SUM(C.AMT),0) / NULLIF(COUNT(*),0), 2)", "fmt": "amount",
        "from": "FACT_CONTRACT C JOIN DIM_PROJECT P ON P.PROJ_CODE = C.PROJ_CODE",
        "where": "C.SIGN_DATE BETWEEN TO_DATE('{start}','YYYY-MM-DD') AND TO_DATE('{end}','YYYY-MM-DD') AND NVL(C.CHANGE_FLAG,0)=0",
    },
    # ---------------- 收入类 ----------------
    "SR_OPERATE": {
        "name": "营业收入", "cat": "CAT_REVENUE", "unit": "万元",
        "expr": "NVL(SUM(V.AMT),0)", "fmt": "amount",
        "from": _REV + " JOIN DIM_PROJECT P ON P.PROJ_CODE = V.PROJ_CODE",
        "where": "1=1",
    },
    "SR_DESIGN": {
        "name": "设计咨询收入", "cat": "CAT_REVENUE", "unit": "万元",
        "expr": "NVL(SUM(R2.AMT),0)", "fmt": "amount",
        "from": ("(SELECT PROJ_CODE, PERIOD, SUM(AMT) AS AMT FROM FACT_REVENUE "
                 "WHERE REV_TYPE = '设计收入' AND PERIOD BETWEEN '{mon}' GROUP BY PROJ_CODE, PERIOD) R2 "
                 "JOIN DIM_PROJECT P ON P.PROJ_CODE = R2.PROJ_CODE"),
        "where": "1=1",
    },
    "SR_PER_STAFF": {
        "name": "人均营业收入", "cat": "CAT_REVENUE", "unit": "万元/人",
        "expr": "ROUND(NVL(SUM(V.AMT),0) / NULLIF((SELECT COUNT(*) FROM DIM_STAFF WHERE STATUS='在职'),0), 2)",
        "fmt": "amount",
        "from": _REV + " JOIN DIM_PROJECT P ON P.PROJ_CODE = V.PROJ_CODE",
        "where": "1=1",
    },
    # ---------------- 利润类 ----------------
    "LR_TOTAL": {
        "name": "利润总额", "cat": "CAT_PROFIT", "unit": "万元",
        "expr": "NVL(SUM(V.AMT),0) - NVL(SUM(K.AMT),0)", "fmt": "amount",
        "from": _PROFIT_FROM, "where": "1=1",
    },
    "LR_COST": {
        "name": "营业成本", "cat": "CAT_PROFIT", "unit": "万元",
        "expr": "NVL(SUM(K.AMT),0)", "fmt": "amount",
        "from": "{cost} JOIN DIM_PROJECT P ON P.PROJ_CODE = K.PROJ_CODE", "where": "1=1",
    },
    "LR_GROSS_RATE": {
        "name": "毛利率", "cat": "CAT_PROFIT", "unit": "%",
        "expr": "ROUND(100 * (NVL(SUM(V.AMT),0) - NVL(SUM(K.AMT),0)) / NULLIF(SUM(V.AMT),0), 2)",
        "fmt": "percent", "from": _PROFIT_FROM, "where": "1=1",
    },
    "LR_PROJ_MARGIN": {
        "name": "项目平均毛利率", "cat": "CAT_PROFIT", "unit": "%",
        "expr": "ROUND(AVG(100 * (NVL(V.AMT,0) - NVL(K.AMT,0)) / NULLIF(V.AMT,0)), 2)",
        "fmt": "percent", "from": _PROFIT_FROM, "where": "1=1",
    },
    # ---------------- 回款与两金 ----------------
    "HK_AMT": {
        "name": "回款额", "cat": "CAT_CASH", "unit": "万元",
        "expr": "NVL(SUM(H.AMT),0)", "fmt": "amount",
        "from": ("(SELECT PROJ_CODE, PERIOD, SUM(AMT) AS AMT FROM FACT_COLLECTION "
                 "WHERE PERIOD BETWEEN '{mon}' GROUP BY PROJ_CODE, PERIOD) H "
                 "JOIN DIM_PROJECT P ON P.PROJ_CODE = H.PROJ_CODE"),
        "where": "1=1",
    },
    "HK_RATE": {
        "name": "回款率", "cat": "CAT_CASH", "unit": "%",
        "expr": "ROUND(100 * NVL(SUM(H.AMT),0) / NULLIF(SUM(V.AMT),0), 2)", "fmt": "percent",
        "from": ("(SELECT PROJ_CODE, PERIOD, SUM(AMT) AS AMT FROM FACT_COLLECTION "
                 "WHERE PERIOD BETWEEN '{mon}' GROUP BY PROJ_CODE, PERIOD) H "
                 "LEFT JOIN (SELECT PROJ_CODE, PERIOD, SUM(AMT) AS AMT FROM FACT_REVENUE "
                 "WHERE PERIOD BETWEEN '{mon}' GROUP BY PROJ_CODE, PERIOD) V "
                 "ON V.PROJ_CODE = H.PROJ_CODE AND V.PERIOD = H.PERIOD "
                 "JOIN DIM_PROJECT P ON P.PROJ_CODE = H.PROJ_CODE"),
        "where": "1=1",
    },
    "HK_AR_BAL": {
        "name": "应收账款余额", "cat": "CAT_CASH", "unit": "万元",
        "expr": "NVL(SUM(A.BAL_AMT),0)", "fmt": "amount",
        "from": ("(SELECT PROJ_CODE, SUM(BAL_AMT) AS BAL_AMT FROM FACT_AR "
                 "WHERE PERIOD = '{last}' GROUP BY PROJ_CODE) A "
                 "JOIN DIM_PROJECT P ON P.PROJ_CODE = A.PROJ_CODE"),
        "where": "1=1",
    },
    "HK_AR_OVER1Y": {
        "name": "长账龄应收占比", "cat": "CAT_CASH", "unit": "%",
        "expr": "ROUND(100 * NVL(SUM(CASE WHEN A.AGE_BUCKET = '1年以内' THEN 0 ELSE A.BAL_AMT END),0) "
                "/ NULLIF(SUM(A.BAL_AMT),0), 2)", "fmt": "percent",
        "from": ("(SELECT PROJ_CODE, AGE_BUCKET, SUM(BAL_AMT) AS BAL_AMT FROM FACT_AR "
                 "WHERE PERIOD = '{last}' GROUP BY PROJ_CODE, AGE_BUCKET) A "
                 "JOIN DIM_PROJECT P ON P.PROJ_CODE = A.PROJ_CODE"),
        "where": "1=1",
    },
    "HK_TWOGOLD": {
        "name": "两金占用", "cat": "CAT_CASH", "unit": "万元",
        "expr": "NVL(SUM(A.BAL_AMT),0) + NVL(SUM(CASE WHEN NVL(G.OUT,0) - NVL(V.AMT,0) > 0 "
                "THEN NVL(G.OUT,0) - NVL(V.AMT,0) ELSE 0 END),0)", "fmt": "amount",
        "from": ("(SELECT PROJ_CODE, SUM(BAL_AMT) AS BAL_AMT FROM FACT_AR "
                 "WHERE PERIOD = '{last}' GROUP BY PROJ_CODE) A "
                 "JOIN DIM_PROJECT P ON P.PROJ_CODE = A.PROJ_CODE "
                 "LEFT JOIN (SELECT PROJ_CODE, SUM(OUTPUT_AMT) AS OUT FROM FACT_PROGRESS "
                 "WHERE PERIOD BETWEEN '{mon}' GROUP BY PROJ_CODE) G ON G.PROJ_CODE = A.PROJ_CODE "
                 "LEFT JOIN (SELECT PROJ_CODE, SUM(AMT) AS AMT FROM FACT_REVENUE "
                 "WHERE PERIOD BETWEEN '{mon}' GROUP BY PROJ_CODE) V ON V.PROJ_CODE = A.PROJ_CODE"),
        "where": "1=1",
    },
    # ---------------- 产值履约 ----------------
    "CZ_OUTPUT": {
        "name": "在建项目产值", "cat": "CAT_OUTPUT", "unit": "万元",
        "expr": "NVL(SUM(G.OUTPUT_AMT),0)", "fmt": "amount",
        "from": ("(SELECT PROJ_CODE, SUM(OUTPUT_AMT) AS OUTPUT_AMT FROM FACT_PROGRESS "
                 "WHERE PERIOD BETWEEN '{mon}' GROUP BY PROJ_CODE) G "
                 "JOIN DIM_PROJECT P ON P.PROJ_CODE = G.PROJ_CODE"),
        "where": "1=1",
    },
    "CZ_FINISH_RATE": {
        "name": "产值完成率", "cat": "CAT_OUTPUT", "unit": "%",
        "expr": "ROUND(100 * NVL(SUM(G.OUTPUT_AMT),0) / NULLIF(SUM(G.PLAN_OUTPUT_AMT),0), 2)",
        "fmt": "percent",
        "from": ("(SELECT PROJ_CODE, SUM(OUTPUT_AMT) AS OUTPUT_AMT, SUM(PLAN_OUTPUT_AMT) AS PLAN_OUTPUT_AMT "
                 "FROM FACT_PROGRESS WHERE PERIOD BETWEEN '{mon}' GROUP BY PROJ_CODE) G "
                 "JOIN DIM_PROJECT P ON P.PROJ_CODE = G.PROJ_CODE"),
        "where": "1=1",
    },
    "CZ_IMAGE_PROGRESS": {
        "name": "平均形象进度", "cat": "CAT_OUTPUT", "unit": "%",
        "expr": "ROUND(AVG(G.IMAGE_PROGRESS), 2)", "fmt": "percent",
        "from": ("(SELECT PROJ_CODE, MAX(IMAGE_PROGRESS) AS IMAGE_PROGRESS FROM FACT_PROGRESS "
                 "WHERE PERIOD BETWEEN '{mon}' GROUP BY PROJ_CODE) G "
                 "JOIN DIM_PROJECT P ON P.PROJ_CODE = G.PROJ_CODE"),
        "where": "P.PROJ_STATUS = '在建'",
    },
    "CZ_PROJ_ACTIVE": {
        "name": "在建项目数", "cat": "CAT_OUTPUT", "unit": "个",
        "expr": "COUNT(DISTINCT P.PROJ_CODE)", "fmt": "count", "no_compare": True,
        "from": "DIM_PROJECT P", "where": "P.PROJ_STATUS = '在建'",
    },
    # ---------------- 安全风险 ----------------
    "AQ_HAZARD_CNT": {
        "name": "危大工程数", "cat": "CAT_RISK", "unit": "个",
        "expr": "COUNT(*)", "fmt": "count",
        "from": "FACT_HAZARD Z JOIN DIM_PROJECT P ON P.PROJ_CODE = Z.PROJ_CODE",
        "where": "Z.HAZARD_TYPE = '危大工程' AND Z.FOUND_DATE BETWEEN TO_DATE('{start}','YYYY-MM-DD') AND TO_DATE('{end}','YYYY-MM-DD')",
    },
    "AQ_HAZARD_FIX_RATE": {
        "name": "隐患整改率", "cat": "CAT_RISK", "unit": "%",
        "expr": "ROUND(100 * SUM(CASE WHEN Z.STATUS = '已整改' THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 2)",
        "fmt": "percent",
        "from": "FACT_HAZARD Z JOIN DIM_PROJECT P ON P.PROJ_CODE = Z.PROJ_CODE",
        "where": "Z.HAZARD_TYPE = '隐患' AND Z.FOUND_DATE BETWEEN TO_DATE('{start}','YYYY-MM-DD') AND TO_DATE('{end}','YYYY-MM-DD')",
    },
    "AQ_RISK_CNT": {
        "name": "风险事项数", "cat": "CAT_RISK", "unit": "个",
        "expr": "COUNT(*)", "fmt": "count",
        "from": "FACT_RISK R JOIN DIM_PROJECT P ON P.PROJ_CODE = R.PROJ_CODE",
        "where": "R.FOUND_DATE BETWEEN TO_DATE('{start}','YYYY-MM-DD') AND TO_DATE('{end}','YYYY-MM-DD')",
    },
    "AQ_OVERDUE_CNT": {
        "name": "超期关键管理动作", "cat": "CAT_RISK", "unit": "个",
        "expr": "SUM(CASE WHEN R.STATUS = '跟踪中' AND R.FOUND_DATE < '{overdue}' THEN 1 ELSE 0 END)",
        "fmt": "count",
        "from": "FACT_RISK R JOIN DIM_PROJECT P ON P.PROJ_CODE = R.PROJ_CODE",
        "where": "R.FOUND_DATE <= TO_DATE('{end}','YYYY-MM-DD')",
    },
    # ---------------- 效率人力 ----------------
    "RL_STAFF_HOURS": {
        "name": "投入工时", "cat": "CAT_EFF", "unit": "小时",
        "expr": "NVL(SUM(W.HOURS),0)", "fmt": "number",
        "from": "FACT_STAFF_HOURS W JOIN DIM_PROJECT P ON P.PROJ_CODE = W.PROJ_CODE",
        "where": "W.PERIOD BETWEEN '{mon}'",
    },
    "RL_STAFF_CNT": {
        "name": "投入人数", "cat": "CAT_EFF", "unit": "人",
        "expr": "COUNT(DISTINCT W.STAFF_ID)", "fmt": "count",
        "from": "FACT_STAFF_HOURS W JOIN DIM_PROJECT P ON P.PROJ_CODE = W.PROJ_CODE",
        "where": "W.PERIOD BETWEEN '{mon}'",
    },
    "RL_PROJ_PER_PM": {
        "name": "人均在管项目", "cat": "CAT_EFF", "unit": "个/人",
        "expr": "ROUND(1.0 * SUM(CASE WHEN P.PROJ_STATUS = '在建' THEN 1 ELSE 0 END) "
                "/ NULLIF(COUNT(DISTINCT P.PM_STAFF_ID),0), 2)", "fmt": "number", "no_compare": True,
        "from": "DIM_PROJECT P", "where": "1=1",
    },
}

KPI_ORDER = list(METRICS.keys())


# ---------------------------------------------------------------------------
# 期间处理
# ---------------------------------------------------------------------------

def month_list(start: str, end: str) -> List[str]:
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def period_ctx(start: str, end: str) -> Dict[str, str]:
    from datetime import date, timedelta
    months = month_list(start, end)
    y, m, d = map(int, start.split("-"))
    overdue = (date(y, m, d) - timedelta(days=90)).isoformat()
    return {
        "start": start, "end": end,
        "mon": months[0] + "' AND '" + months[-1],
        "last": months[-1],
        "overdue": overdue,
        "label": "%s 至 %s" % (start, end),
    }


# ---------------------------------------------------------------------------
# SQL 组装
# ---------------------------------------------------------------------------

def _join_table(join_str: str) -> str:
    """从 "LEFT JOIN DIM_X A ON ..." 中取出表名，用于去重。"""
    m = re.search(r"JOIN\s+(\w+)", join_str)
    return m.group(1) if m else join_str


def _fill(tpl: str, ctx: Dict[str, str]) -> str:
    s = (tpl.replace("{start}", ctx["start"]).replace("{end}", ctx["end"])
            .replace("{mon}", ctx["mon"]).replace("{last}", ctx["last"])
            .replace("{overdue}", ctx["overdue"]))
    # 利润类指标引用的两个派生收入/成本子查询
    s = s.replace("{rev}", _REV.replace("{mon}", ctx["mon"]))
    s = s.replace("{cost}", _COST)
    return s


def metric_sql(kpi_id: str, ctx: Dict[str, str],
               group_dims: Optional[List[str]] = None,
               filters: Optional[List[Tuple[str, str, Any]]] = None,
               limit: Optional[int] = None,
               order_desc: bool = True) -> str:
    """按指标元数据组装一条 Oracle 11g 方言 SQL。"""
    m = METRICS[kpi_id]
    group_dims = group_dims or []
    need_ext = any(d in ("ENG_TYPE",) for d in group_dims) or any(
        d == "ENG_TYPE" for d, _, _ in (filters or []))
    from_clause = _fill(m["from"], ctx)
    if need_ext and "DIM_PROJECT_EXT" not in from_clause:
        from_clause += " " + _EXT_JOIN
    select_parts, group_parts, joins = [], [], []
    joined = {_join_table(j) for j in joins}
    if "DIM_PROJECT_EXT" in from_clause:
        joined.add("DIM_PROJECT_EXT")

    def ensure_join(spec: Dict[str, str]) -> None:
        if not spec["join"]:
            return
        tbl = _join_table(spec["join"])
        if tbl in from_clause or tbl in joined:
            return
        joins.append(spec["join"])
        joined.add(tbl)

    for d in group_dims:
        spec = DIMS[d]
        select_parts.append("%s AS D_%s" % (spec["label"], d))
        group_parts.append(spec["expr"])
        ensure_join(spec)

    where = _fill(m["where"], ctx)
    for d, op, val in (filters or []):
        spec = DIMS[d]
        ensure_join(spec)
        if op == "like":
            where += " AND %s LIKE '%%%s%%'" % (spec["expr"], val)
        elif op == "in":
            vals = ",".join("'%s'" % v for v in val)
            where += " AND %s IN (%s)" % (spec["expr"], vals)
        elif op == "!=":
            where += " AND %s <> '%s'" % (spec["expr"], val)
        elif op in ("=", ">=", "<=", ">", "<"):
            v = "'%s'" % val if isinstance(val, str) else str(val)
            where += " AND %s %s %s" % (spec["expr"], op, v)

    sql = "SELECT %s%s AS VAL FROM %s %s WHERE %s" % (
        (", ".join(select_parts) + ", ") if select_parts else "",
        m["expr"], from_clause, " ".join(joins), where)
    if group_parts:
        sql += " GROUP BY " + ", ".join(group_parts)
        sql += " ORDER BY VAL %s" % ("DESC" if order_desc else "ASC")
    if limit:
        sql = "SELECT * FROM (\n%s\n) WHERE ROWNUM <= %d" % (sql, limit)
    return sql


def query_metric(kpi_id: str, ctx: Dict[str, str],
                 group_dims: Optional[List[str]] = None,
                 filters: Optional[List[Tuple[str, str, Any]]] = None,
                 limit: Optional[int] = None) -> List[Dict[str, Any]]:
    sql = metric_sql(kpi_id, ctx, group_dims, filters, limit)
    return db.run_query(sql).rows


def metric_value(kpi_id: str, ctx: Dict[str, str],
                 filters: Optional[List[Tuple[str, str, Any]]] = None) -> float:
    rows = query_metric(kpi_id, ctx, [], filters)
    if not rows:
        return 0.0
    v = rows[0].get("VAL")
    return float(v) if v is not None else 0.0


# ---------------------------------------------------------------------------
# 指标宽表
# ---------------------------------------------------------------------------

def ensure_wide_columns(conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(FACT_KPI_WIDE)")}
    for kpi in KPI_ORDER:
        if kpi not in cols:
            conn.execute("ALTER TABLE FACT_KPI_WIDE ADD COLUMN %s REAL" % kpi)
    conn.commit()


def build_wide(period_start: str, period_end: str, verbose: bool = False) -> int:
    """构建结构化指标宽表：一行 = 期间 × 分公司 × 项目等级，一列 = 一个指标。"""
    ctx = period_ctx(period_start, period_end)
    conn = db.get_conn()
    ensure_wide_columns(conn)
    conn.execute("DELETE FROM FACT_KPI_WIDE WHERE PERIOD = ?", (period_start,))
    conn.execute("DELETE FROM FACT_KPI_SNAPSHOT WHERE PERIOD = ?", (period_start,))

    orgs = [r["ORG_ID"] for r in conn.execute(
        "SELECT ORG_ID FROM DIM_ORG WHERE ORG_LEVEL = 2 ORDER BY ORG_ID")]
    types = ["A", "B", "C", "D"]
    combos: List[Tuple[str, Optional[str]]] = [("ALL", None)]
    combos += [(o, None) for o in orgs]
    combos += [("ALL", t) for t in types]

    n = 0
    for org, ptype in combos:
        vals: Dict[str, Any] = {}
        filters: List[Tuple[str, str, Any]] = []
        if org != "ALL":
            filters.append(("ORG", "=", org))
        if ptype:
            filters.append(("PROJ_TYPE", "=", ptype))
        for kpi in KPI_ORDER:
            try:
                vals[kpi] = metric_value(kpi, ctx, filters)
            except Exception as e:  # 单个指标异常不阻断整体构建
                if verbose:
                    print("[宽表] %s 计算失败: %s" % (kpi, e))
                vals[kpi] = None
        org_name = "全院合计" if org == "ALL" else conn.execute(
            "SELECT ORG_NAME FROM DIM_ORG WHERE ORG_ID = ?", (org,)).fetchone()["ORG_NAME"]
        cols = ["PERIOD", "ORG_ID", "ORG_NAME", "PROJ_TYPE"] + KPI_ORDER
        ph = ",".join(["?"] * len(cols))
        conn.execute("INSERT INTO FACT_KPI_WIDE (%s) VALUES (%s)" % (",".join(cols), ph),
                     [period_start, org, org_name, ptype or "ALL"] + [vals[k] for k in KPI_ORDER])
        # 长表快照（供趋势查询）
        for kpi in KPI_ORDER:
            conn.execute(
                "INSERT INTO FACT_KPI_SNAPSHOT (PERIOD, ORG_ID, PROJ_TYPE, KPI_ID, VALUE, UNIT) "
                "VALUES (?,?,?,?,?,?)",
                (period_start, org, ptype or "ALL", kpi, vals[kpi], METRICS[kpi]["unit"]))
        n += 1
    conn.commit()
    conn.close()
    if verbose:
        print("[宽表] 期间 %s 生成 %d 行 × %d 指标" % (period_start, n, len(KPI_ORDER)))
    return n


def wide_row(period_start: str, org_id: str = "ALL", proj_type: str = "ALL") -> Dict[str, Any]:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM FACT_KPI_WIDE WHERE PERIOD=? AND ORG_ID=? AND PROJ_TYPE=?",
        (period_start, org_id, proj_type)).fetchone()
    conn.close()
    return dict(row) if row else {}


def compare(period_start: str, period_end: str,
            prev_start: str, prev_end: str,
            filters: Optional[List[Tuple]] = None) -> List[Dict[str, Any]]:
    """计算同比 / 环比，返回指标对比清单。filters 用于注入岗位数据范围。"""
    ctx, pctx = period_ctx(period_start, period_end), period_ctx(prev_start, prev_end)
    # 同比基期 = 本期整体前移 12 个月（上年同期），与环比基期无关
    yoy_ctx = period_ctx(_shift_date(period_start, -12), _end_of_month(_shift_date(period_end, -12)))
    out = []
    for kpi in KPI_ORDER:
        cur = metric_value(kpi, ctx, filters)
        mom = metric_value(kpi, pctx, filters)
        yoy = metric_value(kpi, yoy_ctx, filters)
        out.append({
            "kpi_id": kpi,
            "kpi_name": METRICS[kpi]["name"],
            "category": METRICS[kpi]["cat"],
            "category_name": CATEGORIES[METRICS[kpi]["cat"]],
            "unit": METRICS[kpi]["unit"],
            "value": cur,
            "mom": pct_change(cur, mom),
            "yoy": pct_change(cur, yoy),
            "prev_value": mom,
            "last_year_value": yoy,
        })
    return out


def _shift_date(d: str, months: int) -> str:
    total = int(d[:4]) * 12 + (int(d[5:7]) - 1) + months
    y, m = total // 12, total % 12 + 1
    return "%04d-%02d-%02d" % (y, m, int(d[8:10]))


def _end_of_month(d: str) -> str:
    from calendar import monthrange
    y, m = int(d[:4]), int(d[5:7])
    return "%04d-%02d-%02d" % (y, m, monthrange(y, m)[1])


def pct_change(cur: float, base: float) -> Optional[float]:
    try:
        if base in (None, 0):
            return None
        return round((cur - base) / abs(base) * 100, 2)
    except Exception:
        return None


def dictionary() -> List[Dict[str, Any]]:
    conn = db.get_conn()
    cal = {r["CALIBER_ID"]: dict(r) for r in conn.execute("SELECT * FROM DIM_CALIBER")}
    order = {c: i for i, c in enumerate(CATEGORIES.keys())}
    kpi_order = {k: i for i, k in enumerate(KPI_ORDER)}
    rows = []
    for r in sorted(conn.execute("SELECT * FROM DIM_KPI").fetchall(),
                    key=lambda x: (order.get(x["CATEGORY"], 99), kpi_order.get(x["KPI_ID"], 99),
                                   x["KPI_NAME"])):
        d = dict(r)
        d["category_name"] = CATEGORIES.get(d["CATEGORY"], d["CATEGORY"])
        d["in_engine"] = d["KPI_ID"] in METRICS
        d["caliber"] = cal.get(d["CALIBER_ID"], {}).get("DEFINITION", "")
        rows.append(d)
    conn.close()
    return rows
