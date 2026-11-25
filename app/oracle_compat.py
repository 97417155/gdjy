# -*- coding: utf-8 -*-
"""Oracle 11g 方言适配层。

现场数据库是 Oracle 11g（12c 之前的版本），存在几个真实约束：
  * 没有 FETCH FIRST / OFFSET，分页只能靠 ROWNUM 子查询；
  * 没有 LIMIT，日期格式化只能用 TO_CHAR / TO_DATE；
  * 没有 IFNULL / NOW() / DATE_FORMAT；
  * 集合差用 MINUS 而非 EXCEPT，标识符不带反引号；
  * GROUP BY 不能引用 SELECT 别名。

大模型默认会吐 MySQL 方言，所以这里做三件事：
  1. lint()        —— 静态检查，指出与 11g 不兼容的写法（用于提示词约束与修复回路）
  2. rewrite()     —— 把常见 MySQL 写法自动改写为 11g 写法
  3. to_sqlite()   —— 把 11g 写法转译成 SQLite 可执行形式（本地演示执行引擎）

生产环境把 to_sqlite 换成 cx_Oracle 直连即可，其余两层逻辑完全复用。
"""
from __future__ import annotations

import re
from typing import List, Tuple

# (正则, 说明, 建议)
LINT_RULES: List[Tuple[str, str, str]] = [
    (r"\bFETCH\s+FIRST\b", "FETCH FIRST 是 12c+ 语法", "改用 SELECT * FROM (...) WHERE ROWNUM <= n"),
    (r"\bOFFSET\s+\d+\s+ROWS\b", "OFFSET ... ROWS 是 12c+ 语法", "改用 ROWNUM 双层子查询"),
    (r"\bLIMIT\s+\d+", "LIMIT 属于 MySQL/PostgreSQL", "改用 ROWNUM"),
    (r"\bIFNULL\s*\(", "Oracle 无 IFNULL", "改用 NVL(col, 0)"),
    (r"\bISNULL\s*\(", "Oracle 无 ISNULL 函数", "改用 NVL"),
    (r"\bDATE_FORMAT\s*\(", "Oracle 无 DATE_FORMAT", "改用 TO_CHAR(col,'YYYY-MM')"),
    (r"\bSTRFTIME\s*\(", "SQLite 函数", "改用 TO_CHAR"),
    (r"\bNOW\s*\(\s*\)", "Oracle 无 NOW()", "改用 SYSDATE"),
    (r"\bCURDATE\s*\(\s*\)", "Oracle 无 CURDATE()", "改用 TRUNC(SYSDATE)"),
    (r"\bILIKE\b", "Oracle 无 ILIKE", "改用 UPPER(col) LIKE UPPER('%x%')"),
    (r"\bEXCEPT\b", "Oracle 无 EXCEPT", "改用 MINUS"),
    (r"\bAUTO_INCREMENT\b", "Oracle 无自增列", "使用 SEQUENCE + 触发器"),
    (r"`", "反引号是 MySQL 标识符", "改用双引号或不加引号"),
    (r"\bJSON_EXTRACT\b", "Oracle 11g 无 JSON 函数", "调整存储结构"),
    (r"\bTOP\s+\d+", "TOP 是 SQL Server 语法", "改用 ROWNUM"),
]

# MySQL 函数 / 格式串 -> Oracle
_FORMAT_MAP = [
    ("%Y-%m-%d", "YYYY-MM-DD"),
    ("%Y-%m", "YYYY-MM"),
    ("%Y", "YYYY"),
    ("%m", "MM"),
    ("%d", "DD"),
]


def lint(sql: str) -> List[dict]:
    """静态检查，返回违规项列表。"""
    issues = []
    upper = sql.upper()
    for pattern, msg, fix in LINT_RULES:
        m = re.search(pattern, sql, re.IGNORECASE)
        if m:
            issues.append({
                "rule": pattern,
                "hit": m.group(0),
                "message": msg,
                "suggestion": fix,
            })
    # GROUP BY 引用 SELECT 别名是 11g 的常见坑（无法静态判定全部，只做粗筛）
    if re.search(r"\bORDER\s+BY\s+\d+", upper) and "ROWNUM" not in upper:
        issues.append({
            "rule": "ORDER BY ordinal",
            "hit": "ORDER BY <序号>",
            "message": "按序号排序在部分 11g 环境不稳定",
            "suggestion": "改为按列名或别名排序",
        })
    return issues


def rewrite(sql: str) -> Tuple[str, List[str]]:
    """把常见 MySQL 写法改写为 Oracle 11g 写法，返回 (新SQL, 改写记录)。"""
    log: List[str] = []
    s = sql.strip().rstrip(";")

    # 1) 反引号 -> 去掉（列名均为大写字母下划线，无需引号）
    if "`" in s:
        s = s.replace("`", "")
        log.append("去除反引号")

    # 2) IFNULL / ISNULL -> NVL
    if re.search(r"\bIFNULL\s*\(", s, re.I):
        s = re.sub(r"\bIFNULL\s*\(", "NVL(", s, flags=re.I)
        log.append("IFNULL -> NVL")
    if re.search(r"\bISNULL\s*\(", s, re.I):
        s = re.sub(r"\bISNULL\s*\(", "NVL(", s, flags=re.I)
        log.append("ISNULL -> NVL")

    # 3) NOW() / CURDATE()
    if re.search(r"\bNOW\s*\(\s*\)", s, re.I):
        s = re.sub(r"\bNOW\s*\(\s*\)", "SYSDATE", s, flags=re.I)
        log.append("NOW() -> SYSDATE")
    if re.search(r"\bCURDATE\s*\(\s*\)", s, re.I):
        s = re.sub(r"\bCURDATE\s*\(\s*\)", "TRUNC(SYSDATE)", s, flags=re.I)
        log.append("CURDATE() -> TRUNC(SYSDATE)")

    # 4) DATE_FORMAT(col,'%Y-%m') -> TO_CHAR(col,'YYYY-MM')
    def _df(m):
        expr, fmt = m.group(1), m.group(2)
        for k, v in _FORMAT_MAP:
            fmt = fmt.replace(k, v)
        return "TO_CHAR(%s,'%s')" % (expr, fmt)
    if re.search(r"DATE_FORMAT\s*\(", s, re.I):
        s = re.sub(r"DATE_FORMAT\s*\(\s*([^,]+?)\s*,\s*'([^']+)'\s*\)", _df, s, flags=re.I)
        log.append("DATE_FORMAT -> TO_CHAR")

    # 5) STRFTIME('%Y-%m', col) -> TO_CHAR(col,'YYYY-MM')
    def _sf(m):
        fmt, expr = m.group(1), m.group(2)
        for k, v in _FORMAT_MAP:
            fmt = fmt.replace(k, v)
        return "TO_CHAR(%s,'%s')" % (expr, fmt)
    if re.search(r"STRFTIME\s*\(", s, re.I):
        s = re.sub(r"STRFTIME\s*\(\s*'([^']+)'\s*,\s*([^)]+?)\s*\)", _sf, s, flags=re.I)
        log.append("STRFTIME -> TO_CHAR")

    # 6) EXCEPT -> MINUS
    if re.search(r"\bEXCEPT\b", s, re.I):
        s = re.sub(r"\bEXCEPT\b", "MINUS", s, flags=re.I)
        log.append("EXCEPT -> MINUS")

    # 7) ILIKE -> UPPER() LIKE UPPER()
    if re.search(r"\bILIKE\b", s, re.I):
        s = re.sub(r"(\w+(?:\.\w+)?)\s+ILIKE\s+('[^']*')",
                   r"UPPER(\1) LIKE UPPER(\2)", s, flags=re.I)
        log.append("ILIKE -> UPPER() LIKE")

    # 8) LIMIT n / FETCH FIRST n ROWS ONLY -> ROWNUM 外层包裹
    m = re.search(r"\bLIMIT\s+(\d+)\s*$", s, re.I)
    if not m:
        m = re.search(r"\bFETCH\s+FIRST\s+(\d+)\s+ROWS\s+ONLY\s*$", s, re.I)
    if m:
        n = m.group(1)
        body = s[: m.start()].strip()
        s = "SELECT * FROM (\n%s\n) WHERE ROWNUM <= %s" % (body, n)
        log.append("LIMIT/FETCH -> ROWNUM <= %s" % n)

    return s, log


def to_sqlite(sql: str) -> str:
    """把 Oracle 11g 方言的 SQL 转译为 SQLite 可执行形式（仅用于本地演示库）。"""
    s = sql.strip().rstrip(";")

    # DAYS_BETWEEN(a, b)：Oracle 中日期相减即天数，SQLite 需 julianday
    s = re.sub(r"DAYS_BETWEEN\s*\(\s*([^,()]+?)\s*,\s*([^()]+?)\s*\)",
               r"CAST(JULIANDAY(\1) - JULIANDAY(\2) AS INTEGER)", s, flags=re.I)

    # 时间函数
    s = re.sub(r"TRUNC\s*\(\s*SYSDATE\s*,\s*'MM'\s*\)", "DATE('now','start of month')", s, flags=re.I)
    s = re.sub(r"TRUNC\s*\(\s*SYSDATE\s*\)", "DATE('now')", s, flags=re.I)
    s = re.sub(r"\bSYSDATE\b", "DATE('now')", s, flags=re.I)
    # TO_DATE('2026-01-01','YYYY-MM-DD') -> '2026-01-01'（库内日期以 ISO 文本存储）
    s = re.sub(r"TO_DATE\s*\(\s*('(?:[^']*)')\s*,\s*'[^']*'\s*\)", r"\1", s, flags=re.I)
    # TO_CHAR(col,'YYYY-MM') -> STRFTIME('%Y-%m', col)
    def _tc(m):
        expr, fmt = m.group(1), m.group(2)
        fmt = (fmt.replace("YYYY", "%Y").replace("MM", "%m")
                  .replace("DD", "%d").replace("HH24", "%H").replace("MI", "%M"))
        return "STRFTIME('%s',%s)" % (fmt, expr)
    s = re.sub(r"TO_CHAR\s*\(\s*([^,]+?)\s*,\s*'([^']+)'\s*\)", _tc, s, flags=re.I)
    # 数字格式化 TO_CHAR(x,'FM999,999,990.00') 直接丢弃格式，仅保留值
    s = re.sub(r"TO_CHAR\s*\(\s*([^,()]+?)\s*,\s*'FM[^']*'\s*\)", r"\1", s, flags=re.I)
    # NVL / DECODE
    s = re.sub(r"\bNVL\s*\(", "IFNULL(", s, flags=re.I)
    s = re.sub(r"\bMINUS\b", "EXCEPT", s, flags=re.I)
    # ROWNUM 外层包裹 -> LIMIT
    m = re.search(r"^SELECT\s+\*\s+FROM\s*\((.*)\)\s+WHERE\s+ROWNUM\s*<=\s*(\d+)\s*$", s, re.I | re.S)
    if m:
        s = "%s LIMIT %s" % (m.group(1).strip().rstrip(";"), m.group(2))
    return s


def guard_readonly(sql: str) -> Tuple[bool, str]:
    """只读守卫：只允许单条 SELECT/WITH 查询。"""
    s = sql.strip().rstrip(";")
    if not s:
        return False, "SQL 为空"
    if ";" in s:
        return False, "禁止多语句执行"
    head = s.lstrip("( \n\t").upper()
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        return False, "只允许 SELECT / WITH 查询"
    from app.config import FORBIDDEN_KEYWORDS
    upper = s.upper()
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(r"\b%s\b" % kw, upper):
            return False, "检测到写操作关键字：%s" % kw
    return True, ""
