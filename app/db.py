# -*- coding: utf-8 -*-
"""数据库访问层：连接、元数据、Oracle 方言执行包装。"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from app import oracle_compat
from app.config import DB_PATH, DB_DIR


def get_conn() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
    return [{"name": r["name"], "type": r["type"], "pk": bool(r["pk"])} for r in rows]


def list_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'SCOPE_%' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def schema_doc(conn: sqlite3.Connection, tables: Optional[List[str]] = None) -> str:
    """生成给大模型看的紧凑 schema 描述（含列类型与主键）。"""
    lines = []
    for t in (tables or list_tables(conn)):
        cols = table_columns(conn, t)
        col_txt = ", ".join(
            "%s %s%s" % (c["name"], c["type"] or "TEXT", " PK" if c["pk"] else "")
            for c in cols
        )
        lines.append("%s(%s)" % (t, col_txt))
    return "\n".join(lines)


def schema_json(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    out = []
    for t in list_tables(conn):
        cnt = conn.execute("SELECT COUNT(*) AS C FROM %s" % t).fetchone()["C"]
        out.append({"table": t, "rows": cnt, "columns": table_columns(conn, t)})
    return out


class QueryResult:
    def __init__(self, rows: List[Dict[str, Any]], sql_final: str, sql_oracle: str,
                 cost_ms: int, rewrites: List[str], lint: List[dict]):
        self.rows = rows
        self.sql_final = sql_final      # 实际执行的 SQLite SQL
        self.sql_oracle = sql_oracle    # 面向 Oracle 11g 的 SQL（展示口径）
        self.cost_ms = cost_ms
        self.rewrites = rewrites
        self.lint = lint

    @property
    def columns(self) -> List[str]:
        return list(self.rows[0].keys()) if self.rows else []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rows": self.rows,
            "columns": self.columns,
            "row_count": len(self.rows),
            "sql_oracle": self.sql_oracle,
            "sql_exec": self.sql_final,
            "cost_ms": self.cost_ms,
            "rewrites": self.rewrites,
            "lint": self.lint,
        }


def run_query(sql_oracle: str, params: Tuple = (), conn: Optional[sqlite3.Connection] = None) -> QueryResult:
    """执行一条 Oracle 方言 SQL：守卫 -> 方言转译 -> 执行。"""
    own = conn is None
    conn = conn or get_conn()
    t0 = time.time()
    ok, msg = oracle_compat.guard_readonly(sql_oracle)
    if not ok:
        if own:
            conn.close()
        raise PermissionError(msg)
    lint = oracle_compat.lint(sql_oracle)
    sql_11g, rewrites = oracle_compat.rewrite(sql_oracle)
    sql_exec = oracle_compat.to_sqlite(sql_11g)
    try:
        cur = conn.execute(sql_exec, params)
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        cost = int((time.time() - t0) * 1000)
        if own:
            conn.close()
    return QueryResult(rows, sql_exec, sql_11g, cost, rewrites, lint)


def execute_write(sql: str, params: Tuple = (), conn: Optional[sqlite3.Connection] = None) -> int:
    own = conn is None
    conn = conn or get_conn()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid or cur.rowcount
    finally:
        if own:
            conn.close()
