# -*- coding: utf-8 -*-
"""业务服务层：HTTP 框架无关。

stdlib 服务器（app/api.py）与 FastAPI（server/fastapi_app.py）都只做协议适配，
真正的取数、问答、报告、权限逻辑全部在这里，换框架不需要改业务代码。
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Any, Dict, Generator, List, Optional

from app import dashboard, db, kb, metrics as M, permission
from app.config import CURRENT_PERIOD, FIN_ROLES
from app.nl2sql import llm, router
from app.report import builder, export as report_export_mod, workflow


# ---------------------------------------------------------------------------
# 基础信息
# ---------------------------------------------------------------------------

def meta() -> Dict[str, Any]:
    conn = db.get_conn()
    tables = db.list_tables(conn)
    conn.close()
    return {
        "users": permission.init_users(),
        "llm": llm.status(),
        "kb": kb.stats(),
        "tables": len(tables),
        "metrics": len(M.KPI_ORDER),
        "categories": M.CATEGORIES,
        "oracle_rules": "Oracle 11g 方言（ROWNUM / NVL / TO_CHAR）",
        "export": export_capabilities(),
    }


def periods() -> List[Dict[str, str]]:
    return [{"value": m, "label": "%s年%s月" % (m[:4], int(m[5:7]))}
            for m in M.month_list("2025-01", "2026-10")][::-1]


def dashboard_data(user_id: Optional[str], start: str, end: str) -> Dict[str, Any]:
    user = permission.get_user(user_id)
    return dashboard.build(user, start, end)


# ---------------------------------------------------------------------------
# 问答
# ---------------------------------------------------------------------------

def ask(user_id: Optional[str], question: str, session_id: str = "default") -> Dict[str, Any]:
    user = permission.get_user(user_id)
    if not question.strip():
        raise ValueError("问题不能为空")
    return router.ask(question, user, session_id or "default")


def _sse(event: str, data: Any) -> str:
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False, default=str))


def stream_ask(user_id: Optional[str], question: str,
               session_id: str = "default") -> Generator[str, None, None]:
    """SSE 流：阶段提示 -> SQL 逐字输出 -> 执行信息 -> 最终结果。

    router.ask 里通过 hooks 把阶段与 SQL 推到队列，生成器侧按节奏吐给前端，
    这样离线规则引擎也能呈现"模型正在写 SQL"的过程，接上真模型后 token 流替换即可。
    """
    user = permission.get_user(user_id)
    if not question.strip():
        yield _sse("error", {"message": "问题不能为空"})
        return

    q: "queue.Queue" = queue.Queue()
    state: Dict[str, Any] = {"sql": None}

    def hooks(kind: str, payload: Any) -> None:
        if kind == "sql":
            state["sql"] = payload
        q.put((kind, payload))

    def worker() -> None:
        try:
            payload = router.ask(question, user, session_id or "default", hooks=hooks)
            q.put(("result", payload))
        except Exception as e:  # noqa: BLE001
            q.put(("error", {"message": str(e)}))
        finally:
            q.put(("__end__", None))

    threading.Thread(target=worker, daemon=True).start()

    while True:
        try:
            kind, payload = q.get(timeout=90)
        except queue.Empty:
            yield _sse("error", {"message": "处理超时"})
            return
        if kind == "__end__":
            return
        if kind == "stage":
            yield _sse("stage", payload)
            time.sleep(0.06)
        elif kind == "sql":
            sql = str(payload or "")
            step = 24
            for i in range(0, len(sql), step):
                yield _sse("sql", {"chunk": sql[i:i + step], "done": False})
                # 节奏可配：默认 14ms/片，演示或录屏时可调大；接真模型后由 token 流替代
                time.sleep(float(os.environ.get("GDJY_STREAM_DELAY", "0.014")))
        elif kind == "result":
            yield _sse("sql", {"chunk": "", "done": True})
            yield _sse("result", payload)
        elif kind == "error":
            yield _sse("error", payload)


# ---------------------------------------------------------------------------
# 数据与元数据
# ---------------------------------------------------------------------------

def metrics_dict() -> List[Dict[str, Any]]:
    return M.dictionary()


def schema() -> List[Dict[str, Any]]:
    conn = db.get_conn()
    data = db.schema_json(conn)
    conn.close()
    return data


def table_detail(name: str) -> Dict[str, Any]:
    """单表详情：列定义、主键、行数、样例行、关联指标、关联表。"""
    conn = db.get_conn()
    tables = db.list_tables(conn)
    if name not in tables:
        conn.close()
        raise KeyError("表不存在：%s" % name)

    cols = db.table_columns(conn, name)
    total = conn.execute("SELECT COUNT(*) AS C FROM %s" % name).fetchone()["C"]
    samples = [dict(r) for r in conn.execute("SELECT * FROM %s LIMIT 3" % name)]

    # 该表参与哪些指标（按指标元数据里的 FROM 子句匹配）
    related_kpi = [{"kpi": k, "name": v["name"], "unit": v["unit"]}
                   for k, v in M.METRICS.items() if name in v["from"]]

    # 同库中与它有同名列的表（粗略的关联推荐）
    col_names = {c["name"] for c in cols}
    related_tables = []
    for t in tables:
        if t == name:
            continue
        other = {c["name"] for c in db.table_columns(conn, t)}
        shared = col_names & other
        if shared:
            related_tables.append({"table": t, "shared": sorted(shared)[:4]})
    conn.close()
    related_tables.sort(key=lambda x: -len(x["shared"]))

    return {
        "table": name,
        "rows": total,
        "columns": cols,
        "samples": samples,
        "related_kpis": related_kpi,
        "related_tables": related_tables[:5],
    }


def kpi_wide(period: str) -> Dict[str, Any]:
    conn = db.get_conn()
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(FACT_KPI_WIDE)")]
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM FACT_KPI_WIDE WHERE PERIOD=? ORDER BY ORG_ID, PROJ_TYPE", (period,))]
    conn.close()
    return {"period": period, "columns": cols, "rows": rows}


def audit(limit: int = 50) -> List[Dict[str, Any]]:
    conn = db.get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM FACT_QUERY_LOG ORDER BY CREATE_TIME DESC LIMIT ?", (int(limit),))]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def report_build(user_id: Optional[str], start: str, end: str,
                 hooks=None) -> Dict[str, Any]:
    user = permission.get_user(user_id)
    ps, pe = start or CURRENT_PERIOD[0], end or CURRENT_PERIOD[1]
    prev = builder.prev_period(ps, pe)
    return builder.build(ps, pe, prev[0], prev[1], builder=user["name"],
                         filters=permission.scope_filters(user),
                         scope_label=permission.scope_desc(user),
                         mask_profit=user["role"] not in FIN_ROLES,
                         role=user["role"], hooks=hooks)


def stream_report_build(user_id: Optional[str], start: str, end: str
                        ) -> Generator[str, None, None]:
    """SSE：逐步推送报告生成进度（指标抽取 → 同比环比 → 正文 → 校验 → 落库）。

    每一步先发 running 再发 ok，前端按 name 就地更新，不必等整篇生成完。
    """
    q: "queue.Queue" = queue.Queue()

    def hooks(kind: str, payload: Any) -> None:
        q.put((kind, payload))

    def worker() -> None:
        try:
            payload = report_build(user_id, start, end, hooks=hooks)
            q.put(("result", payload))
        except Exception as e:  # noqa: BLE001
            q.put(("error", {"message": str(e)}))
        finally:
            q.put(("__end__", None))

    threading.Thread(target=worker, daemon=True).start()
    while True:
        try:
            kind, payload = q.get(timeout=180)
        except queue.Empty:
            yield _sse("error", {"message": "生成超时，请稍后重试"})
            return
        if kind == "__end__":
            return
        if kind == "stage":
            yield _sse("stage", payload)
            time.sleep(0.08)      # 让前端看得清步骤推进
        elif kind == "result":
            yield _sse("result", payload)
        elif kind == "error":
            yield _sse("error", payload)


def report_validate(user_id: Optional[str], report_id: str) -> Dict[str, Any]:
    user = permission.get_user(user_id)
    return workflow.submit_validate(report_id, user["role"])


def report_action(user_id: Optional[str], report_id: str, action: str,
                  comment: str = "") -> Dict[str, Any]:
    user = permission.get_user(user_id)
    return workflow.transition(report_id, action, user["name"], comment)


def report_list() -> List[Dict[str, Any]]:
    return builder.latest(20)


def report_get(report_id: str) -> Dict[str, Any]:
    rep = builder.get_report(report_id)
    if not rep:
        raise KeyError("报告不存在")
    rep["timeline"] = workflow.timeline(report_id)
    return rep


def report_export(report_id: str, fmt: str = "md") -> Dict[str, Any]:
    """导出报告：md / docx / pdf / html。返回二进制内容与文件名。"""
    rep = builder.get_report(report_id)
    if not rep:
        raise KeyError("报告不存在")
    fmt = (fmt or "md").lower()
    data, filename, ctype = report_export_mod.export(rep["content_md"], rep["TITLE"], fmt)
    return {"data": data, "filename": filename, "ctype": ctype, "fmt": fmt}


def export_capabilities() -> Dict[str, bool]:
    return report_export_mod.capabilities()
