# -*- coding: utf-8 -*-
"""权限中心对接（模拟）：岗位决定可见组织范围，行级隔离通过项目白名单实现。

设计要点
--------
* 院内权限中心下发的是"人员 -> 岗位 -> 数据范围"三元关系，本模块只做映射；
* 行级隔离不依赖应用层过滤，而是把范围翻译成 SQL 谓词注入到查询里，
  即使大模型生成了错误的 JOIN，也不会越权（最坏是查不到数据）；
* 列级隔离单独一层：利润类指标对非财务岗位脱敏。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app import db
from app.config import ROLE_SCOPE, FIN_ROLES, MASK_TEXT

_USERS: List[Dict[str, Any]] = []


def _pick(conn, role_job: str, org_id: Optional[str] = None,
          busiest: bool = False) -> Optional[dict]:
    """取一个演示账号；PROJ 类岗位取参与项目最多的，保证看板有数据。"""
    if busiest:
        row = conn.execute("""
            SELECT S.*, COUNT(B.PROJ_CODE) AS N FROM DIM_STAFF S
            LEFT JOIN BRIDGE_PROJECT_STAFF B ON B.STAFF_ID = S.STAFF_ID
            WHERE S.ROLE_JOB = ? GROUP BY S.STAFF_ID ORDER BY N DESC, S.STAFF_ID LIMIT 1
        """, (role_job,)).fetchone()
        return dict(row) if row else None
    sql = "SELECT * FROM DIM_STAFF WHERE ROLE_JOB = ?"
    args: List[Any] = [role_job]
    if org_id:
        sql += " AND ORG_ID = ?"
        args.append(org_id)
    row = conn.execute(sql + " ORDER BY STAFF_ID LIMIT 1", args).fetchone()
    return dict(row) if row else None


def init_users() -> List[Dict[str, Any]]:
    """构建演示用账号（真实环境由权限中心同步）。"""
    global _USERS
    if _USERS:
        return _USERS
    conn = db.get_conn()
    spec = [
        ("院长", None, "全院院领导，可见全部经营数据"),
        ("分公司负责人", "O103", "新能源分公司负责人"),
        ("部门负责人", "O10101", "电网分公司设计部负责人"),
        ("项目经理", None, "项目经理，仅见参与项目"),
        ("设计工程师", None, "设计工程师，仅见参与项目"),
        ("财务专员", None, "财务部，可见全部数据"),
    ]
    users = []
    for i, (role, org, desc) in enumerate(spec, 1):
        st = _pick(conn, role, org, busiest=(role in ("项目经理", "设计工程师")))
        if not st:
            continue
        org_row = conn.execute("SELECT ORG_NAME FROM DIM_ORG WHERE ORG_ID=?",
                               (st["ORG_ID"],)).fetchone()
        users.append({
            "user_id": "U%03d" % i,
            "staff_id": st["STAFF_ID"],
            "name": st["STAFF_NAME"],
            "role": role,
            "org_id": st["ORG_ID"],
            "org_name": org_row["ORG_NAME"] if org_row else st["ORG_ID"],
            "scope_type": ROLE_SCOPE.get(role, "PROJ"),
            "desc": desc,
        })
    conn.close()
    _USERS = users
    return _USERS


def get_user(user_id: Optional[str]) -> Dict[str, Any]:
    users = init_users()
    for u in users:
        if u["user_id"] == user_id:
            return u
    return users[0]


def scope_orgs(user: Dict[str, Any]) -> List[str]:
    """返回可见的组织 ID 列表（含下级）。"""
    conn = db.get_conn()
    if user["scope_type"] == "ALL":
        ids = [r["ORG_ID"] for r in conn.execute("SELECT ORG_ID FROM DIM_ORG")]
    elif user["scope_type"] == "ORG":
        ids = [r["ORG_ID"] for r in conn.execute(
            "SELECT ORG_ID FROM DIM_ORG WHERE ORG_ID = ? OR PARENT_ID = ?",
            (user["org_id"], user["org_id"]))]
    elif user["scope_type"] == "DEPT":
        ids = [user["org_id"]]
    else:
        ids = []
    conn.close()
    return ids


def visible_projects(user: Dict[str, Any]) -> List[str]:
    conn = db.get_conn()
    st = user["staff_id"]
    if user["scope_type"] == "ALL":
        rows = conn.execute("SELECT PROJ_CODE FROM DIM_PROJECT").fetchall()
    elif user["scope_type"] in ("ORG", "DEPT"):
        ids = scope_orgs(user)
        ph = ",".join("?" * len(ids)) or "''"
        rows = conn.execute(
            "SELECT PROJ_CODE FROM DIM_PROJECT WHERE ORG_ID IN (%s)" % ph, ids).fetchall()
    else:
        rows = conn.execute(
            "SELECT PROJ_CODE FROM DIM_PROJECT WHERE PM_STAFF_ID = ? "
            "UNION SELECT PROJ_CODE FROM BRIDGE_PROJECT_STAFF WHERE STAFF_ID = ?",
            (st, st)).fetchall()
    conn.close()
    return [r["PROJ_CODE"] for r in rows]


def scope_predicate(user: Dict[str, Any], column: str = "PROJ_CODE") -> Optional[str]:
    """把数据范围翻译成 SQL 谓词（注入到 WHERE 中使用）。"""
    if user["scope_type"] == "ALL":
        return None
    if user["scope_type"] in ("ORG", "DEPT"):
        ids = scope_orgs(user)
        if not ids:
            return "%s IN ('__NONE__')" % column
        ph = ",".join("'%s'" % i for i in ids)
        return "%s IN (SELECT PROJ_CODE FROM DIM_PROJECT WHERE ORG_ID IN (%s))" % (column, ph)
    return ("%s IN (SELECT PROJ_CODE FROM DIM_PROJECT WHERE PM_STAFF_ID = '%s' "
            "UNION SELECT PROJ_CODE FROM BRIDGE_PROJECT_STAFF WHERE STAFF_ID = '%s')"
            % (column, user["staff_id"], user["staff_id"]))


def scope_filters(user: Dict[str, Any]) -> List[Tuple[str, str, object]]:
    """把数据范围转换为指标引擎可用的过滤条件（看板、报告复用）。"""
    t = user["scope_type"]
    if t == "ALL":
        return []
    if t == "ORG":
        return [("ORG", "=", user["org_id"])]
    if t == "DEPT":
        return [("DEPT", "=", user["org_id"])]
    codes = visible_projects(user)
    if not codes:
        return [("PROJ", "in", ["__NONE__"])]
    return [("PROJ", "in", codes[:400])]


def scope_desc(user: Dict[str, Any]) -> str:
    t = user["scope_type"]
    if t == "ALL":
        return "全院数据"
    if t == "ORG":
        return user["org_name"]
    if t == "DEPT":
        return "%s" % user["org_name"]
    n = len(visible_projects(user))
    return "参与项目（%d 个）" % n


def _top_level_marks(sql: str) -> Dict[str, int]:
    """括号深度为 0 的 WHERE / GROUP BY / ORDER BY 位置（避免命中子查询内部）。"""
    marks = {"where": -1, "group": -1, "order": -1}
    depth, i, n = 0, 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0:
            head = sql[i:i + 10].upper()
            if head.startswith(" WHERE "):
                marks["where"] = i
            elif head.startswith(" GROUP BY "):
                marks["group"] = i
            elif head.startswith(" ORDER BY "):
                marks["order"] = i
        i += 1
    return marks


def inject_row_scope(sql_oracle: str, user: Dict[str, Any]) -> Tuple[str, str]:
    """在 SQL 的顶层 WHERE 中注入行级权限谓词，返回 (SQL, 说明)。"""
    import re
    if user["scope_type"] == "ALL":
        return sql_oracle, "全院数据，无行级限制"

    aliases = re.findall(r"(\w+)\.PROJ_CODE\b", sql_oracle)
    column = ("%s.PROJ_CODE" % aliases[0]) if aliases else "PROJ_CODE"
    pred = scope_predicate(user, column)
    if not pred:
        return sql_oracle, "无限制"

    if not (aliases or re.search(r"\bPROJ_CODE\b", sql_oracle.upper())):
        raise PermissionError("查询未包含项目维度，无法完成行级权限校验，已拒绝执行")

    marks = _top_level_marks(sql_oracle)
    cut = len(sql_oracle)
    for k in ("group", "order"):
        if marks[k] > 0:
            cut = min(cut, marks[k])
    body, tail = sql_oracle[:cut], sql_oracle[cut:]
    if marks["where"] > 0 and marks["where"] < cut:
        body = body.rstrip() + " AND " + pred + " "
    else:
        body = body.rstrip() + " WHERE " + pred + " "
    return body + tail, "已注入行级范围：%s" % scope_desc(user)


def mask_rows(rows: List[Dict[str, Any]], kpi_ids: List[str],
              user: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], bool]:
    """列级脱敏：利润类指标对非财务岗位置为脱敏文本。"""
    from app.config import MASK_TEXT
    from app.metrics import METRICS
    if user["role"] in FIN_ROLES:
        return rows, False
    masked = False
    profit_keys = {k for k in kpi_ids if METRICS.get(k, {}).get("cat") == "CAT_PROFIT"}
    if not profit_keys:
        return rows, False
    for r in rows:
        for k in list(r.keys()):
            if k in profit_keys and r[k] not in (None, ""):
                r[k] = MASK_TEXT
                masked = True
    return rows, masked
