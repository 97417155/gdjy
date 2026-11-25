# -*- coding: utf-8 -*-
"""SQL 执行修复回路：语法捕获 → 方言改写 → 重试 → 失败降级。

现场经验：大模型生成的 SQL 有 80% 的错误集中在四类——方言不对、列名大小写不符、
表名不存在、聚合语义冲突。所以修复策略按这四类排列，重试上限 3 次，
仍然失败则走"降级"：直接查已构建好的指标宽表，保证用户至少拿到正确数字。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, Optional, Tuple

from app import db, oracle_compat, permission
from app.metrics import METRICS, wide_row


def _strip_fences(sql: str) -> str:
    s = sql.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip().rstrip(";").strip()


def _catch_fix(sql: str, err: str) -> Tuple[str, str]:
    """根据数据库报错做定向修正，返回 (新SQL, 修正说明)。"""
    msg = err.lower()

    m = re.search(r"no such table: ([\w\.]+)", msg)
    if m:
        bad = m.group(1).split(".")[-1]
        fixed = bad.upper()
        return sql.replace(bad, fixed), "表名大小写修正：%s -> %s" % (bad, fixed)

    m = re.search(r"no such column: ([\w\.]+)", msg)
    if m:
        col = m.group(1).split(".")[-1]
        new_sql = re.sub(r"\b%s\b" % re.escape(col), col.upper(), sql)
        return new_sql, "列名大小写修正：%s -> %s" % (col, col.upper())

    if "misuse of aggregate" in msg or "aggregate" in msg:
        return oracle_compat.rewrite(sql)[0], "聚合语义冲突，重新套用方言改写"

    if "unrecognized token" in msg or "syntax error" in msg or "near" in msg:
        rewritten = oracle_compat.rewrite(sql)[0]
        if rewritten != sql:
            return rewritten, "语法错误，重新套用方言改写"
        return sql, ""

    if "no such function" in msg:
        return oracle_compat.rewrite(sql)[0], "函数不存在，套用 Oracle 方言改写"

    return sql, ""


def run_with_repair(sql: str, user: Optional[Dict[str, Any]] = None,
                    max_attempt: int = 3) -> Tuple[Optional[db.QueryResult], Dict[str, Any]]:
    """执行并修复，返回 (结果, 过程记录)。结果为空表示需要降级。"""
    trace: Dict[str, Any] = {"attempts": [], "status": "ok", "scope": "", "degraded": False}
    base = _strip_fences(sql)

    for i in range(1, max_attempt + 1):
        attempt = {"round": i, "sql": base, "error": None, "fix": None}
        exec_sql = base
        try:
            if user is not None:
                exec_sql, scope_note = permission.inject_row_scope(base, user)
                trace["scope"] = scope_note
            res = db.run_query(exec_sql)
            trace["attempts"].append(attempt)
            trace["status"] = "ok" if i == 1 else "repaired"
            trace["exec_sql"] = exec_sql
            return res, trace
        except PermissionError as e:
            attempt["error"] = str(e)
            trace["attempts"].append(attempt)
            trace["status"] = "rejected"
            raise
        except sqlite3.Error as e:
            attempt["error"] = str(e)
            fixed, note = _catch_fix(base, str(e))
            attempt["fix"] = note or "无可用自动修正规则"
            trace["attempts"].append(attempt)
            if fixed == base:
                break
            base = fixed
        except Exception as e:
            attempt["error"] = str(e)
            trace["attempts"].append(attempt)
            break

    trace["status"] = "failed"
    return None, trace


def degrade(kpi_id: str, period_start: str, org_id: str = "ALL",
            proj_type: str = "ALL") -> Dict[str, Any]:
    """降级：从已构建的指标宽表直接取数。"""
    row = wide_row(period_start, org_id, proj_type)
    meta = METRICS.get(kpi_id, {})
    if not row:
        return {"ok": False, "value": None, "unit": meta.get("unit", ""),
                "name": meta.get("name", kpi_id),
                "message": "指标宽表尚未构建，降级失败，请先执行宽表构建"}
    return {
        "ok": True,
        "value": row.get(kpi_id),
        "unit": meta.get("unit", ""),
        "name": meta.get("name", kpi_id),
        "message": "SQL 修复失败已降级：改由指标宽表（已对齐 BI 口径）返回结果",
    }
