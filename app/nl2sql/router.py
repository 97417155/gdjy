# -*- coding: utf-8 -*-
"""多分支意图路由 + 回答编排。

三分支：项目档案检索 / 自然语言取数 / 知识库问答，另加"多轮追问"与"指标下钻"。
执行顺序刻意设计为：
  规则判意图 -> 规划器出 SQL -> 修复回路执行 -> 权限注入 -> 格式化回答 + 图表
任何一环失败都降级到下一层（LLM -> 规则引擎 -> 指标宽表），不向用户抛异常。
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from app import db, kb, metrics as M, permission
from app.nl2sql import lexicon as L, llm, planner, prompts, repair

_SESSIONS: Dict[str, Dict[str, Any]] = {}

DATA_WORDS = r"(多少|几个|几家|排名|趋势|占比|同比|环比|最高|最低|最多|最少|合计|总计|情况|完成率|平均|哪些|列出|清单|明细)"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _fmt(v: Any, unit: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if unit == "%":
        return "%.2f%%" % f
    if unit in ("个", "人", "个/人", "万元/个"):
        return ("%s %s" % (("{:,.2f}".format(f)).rstrip("0").rstrip("."), unit)).strip()
    return "{:,.2f}".format(f)


def _fmt_cell(v: Any, unit: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        if float(v).is_integer() and unit in ("个", "人"):
            return "{:,}".format(int(v))
        return "{:,.2f}".format(float(v))
    return str(v)


def _table_md(columns: List[str], rows: List[Dict[str, Any]], unit: str = "",
              limit: int = 15) -> str:
    if not rows:
        return "_（无数据）_"
    cols = columns or list(rows[0].keys())
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    body = []
    for r in rows[:limit]:
        body.append("| " + " | ".join(_fmt_cell(r.get(c), unit) for c in cols) + " |")
    return "\n".join([head, sep] + body)


def _chart_from_rows(columns: List[str], rows: List[Dict[str, Any]], unit: str,
                     kind: str, title: str,
                     value_col: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not rows or len(rows) < 2:
        return None
    label_col = next((c for c in columns if c.startswith("D_")), columns[0])
    # 占比问题会额外补一列"占比(%)"，取数时必须显式指定数值列，否则会画成百分比
    value_col = value_col or ("VAL" if "VAL" in columns else columns[-1])
    labels, values = [], []
    for r in rows[:15]:
        labels.append(str(r.get(label_col)))
        try:
            values.append(round(float(r.get(value_col) or 0), 2))
        except (TypeError, ValueError):
            values.append(0)
    return {
        "type": {"share": "pie", "trend": "line"}.get(kind, "bar"),
        "title": title,
        "labels": labels,
        "series": [{"name": title, "data": values}],
        "unit": unit,
        "highlight": 0,
    }


def _log(user: Dict[str, Any], question: str, intent: str, sql: Optional[str],
         rows: int, cost: int, status: str) -> None:
    try:
        lid = "LOG%d" % int(time.time() * 1000)
        db.execute_write(
            "INSERT INTO FACT_QUERY_LOG (LOG_ID, USER_ID, QUESTION, INTENT, SQL_TEXT, ROW_CNT, "
            "COST_MS, STATUS, SCOPE_DESC, CREATE_TIME) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (lid, user["user_id"], question[:300], intent, (sql or "")[:1200], rows, cost,
             status, permission.scope_desc(user), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 意图判定
# ---------------------------------------------------------------------------

def detect_intent(q: str, session: Optional[dict] = None) -> Dict[str, Any]:
    session = session or {}
    projs = planner.find_projects(q)
    kb_like = L.has_kb_intent(q)
    data_like = bool(re.search(DATA_WORDS, q))
    drill = L.has_drill_intent(q) and session.get("last_kpi")

    if planner.is_lag_question(q) or planner.is_risk_question(q):
        return {"intent": "data", "reason": "命中复杂分析模板"}
    if projs and (L.has_archive_intent(q) or not data_like):
        return {"intent": "archive", "projects": projs, "reason": "命中项目名称或档案类关键词"}
    if kb_like and not data_like:
        return {"intent": "kb", "reason": "命中制度/口径/流程类关键词"}
    if re.search(r"(口径|怎么算|如何计算|定义|公式|计算方式)", q) and not re.search(
            r"(是多少|多少|几个|排名|趋势|占比)", q):
        return {"intent": "kb", "reason": "问的是口径或计算方式"}
    if not (projs or kb_like or data_like or L.find_kpi(q)):
        return {"intent": "chat", "reason": "未命中业务要素，按闲聊引导"}
    if kb_like and not data_like and L.find_kpi(q) and not re.search(r"(是多少|多少|几个)", q):
        return {"intent": "kb", "reason": "问的是口径规定而非数值"}
    if drill:
        return {"intent": "data", "drill": True, "reason": "承接上一轮的指标做下钻/换维度"}
    if L.find_kpi(q) or data_like:
        return {"intent": "data", "reason": "命中已登记指标或取数指令"}
    if projs:
        return {"intent": "archive", "projects": projs, "reason": "命中项目名称"}
    return {"intent": "clarify", "reason": "未能识别明确意图"}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _emit(hooks, kind: str, payload: Any) -> None:
    """向 SSE 通道推送阶段信息；任何异常都不影响主流程。"""
    if not hooks:
        return
    try:
        hooks(kind, payload)
    except Exception:
        pass


def ask(question: str, user: Dict[str, Any], session_id: str = "default",
        hooks=None) -> Dict[str, Any]:
    t0 = time.time()
    question = (question or "").strip()
    session = _SESSIONS.setdefault(session_id, {})
    det = detect_intent(question, session)
    intent = det["intent"]
    _emit(hooks, "stage", {"name": "router", "text": "意图识别：%s" % {
        "data": "自然语言取数", "archive": "项目档案检索",
        "kb": "制度与口径问答", "clarify": "需要澄清", "chat": "非业务问题引导",
    }.get(intent, intent)})

    if intent == "chat":
        payload = _answer_chat(question)
    elif intent == "archive":
        payload = _answer_archive(det["projects"][0], question)
    elif intent == "kb":
        payload = _answer_kb(question)
    elif intent == "data":
        payload = _answer_data(question, user, session, drill=det.get("drill", False), hooks=hooks)
    else:
        payload = _answer_clarify(question, session)

    payload["intent"] = intent
    payload["latency_ms"] = int((time.time() - t0) * 1000)
    payload["scope"] = permission.scope_desc(user)
    payload["user"] = {"name": user["name"], "role": user["role"]}
    _log(user, question, intent, payload.get("sql"), len(payload.get("rows") or []),
         payload["latency_ms"], "ok" if intent != "clarify" else "clarify")
    return payload


def _answer_data(question: str, user: Dict[str, Any], session: dict, drill: bool = False,
                 hooks=None) -> Dict[str, Any]:
    used_llm = False
    # 1) 有模型时优先让模型生成 SQL（提示词含方言、口径、样例）
    if llm.available() and not drill:
        schema = db.schema_doc(db.get_conn())
        prompt = prompts.nl2sql_prompt(question, schema, permission.scope_desc(user))
        text = llm.chat([{"role": "user", "content": prompt}], temperature=0.1)
        sql = llm.extract_sql(text)
        if sql:
            try:
                res, trace = repair.run_with_repair(sql, user)
            except PermissionError as e:
                res, trace = None, {"status": "rejected", "attempts": [{"error": str(e)}]}
            if res is not None:
                used_llm = True
                _emit(hooks, "stage", {"name": "plan", "text": "大模型已生成 SQL，正在做 11g 方言校验"})
                _emit(hooks, "sql", sql)
                kpi = L.find_kpi(question)
                payload = _format_generic(res, question, kpi, user, used_llm)
                payload["repair"] = trace
                payload["explain"] = "大模型生成 SQL 后经方言改写与权限注入执行"
                _update_session(session, question, kpi, None, None, None)
                return payload

    # 2) 规则引擎规划
    if drill or (session.get("last_kpi") and not L.find_kpi(question)):
        plan = _plan_with_session(question, session, drill)
    else:
        plan = _plan_any(question)

    if plan["kind"] == "unsupported":
        return _answer_clarify(question, session, extra=plan.get("reason"))

    _emit(hooks, "stage", {"name": "plan", "text": planner.compose_explain(plan)})
    _emit(hooks, "sql", plan["sql"])

    try:
        res, trace = repair.run_with_repair(plan["sql"], user)
    except PermissionError as e:
        return {"answer": "**查询被拒绝**：%s" % e, "sql": plan.get("sql"), "rows": [],
                "chart": None, "degraded": False, "explain": planner.compose_explain(plan)}

    if res is None:
        _emit(hooks, "stage", {"name": "degrade", "text": "SQL 修复失败，降级为指标宽表口径"})
        # 3) 降级：指标宽表
        dg = repair.degrade(plan.get("kpi", ""), plan["period"]["start"])
        note = dg["message"]
        if dg["ok"]:
            ans = ("**已降级返回**：%s\n\n本期全院 **%s** 为 **%s %s**（取自指标宽表，期间 %s）。"
                   % (note, dg["name"], _fmt(dg["value"]), dg["unit"], plan["period"]["label"]))
        else:
            ans = "查询未能完成：%s。建议缩小时间范围或补充维度条件。" % note
        _update_session(session, question, plan.get("kpi"), plan["period"],
                        plan.get("dims"), plan.get("filters"))
        return {"answer": ans, "sql": plan.get("sql"), "rows": [], "chart": None,
                "degraded": True, "explain": planner.compose_explain(plan), "repair": trace}

    _emit(hooks, "stage", {"name": "exec", "text": "执行完成：%d 行 / %d ms（%s）" % (
        len(res.rows), res.cost_ms,
        "一次通过" if not trace.get("attempts") or len(trace["attempts"]) == 1 else "修复后通过")})
    payload = _format_plan(plan, res, user, used_llm, question)
    payload["repair"] = trace
    _update_session(session, question, plan.get("kpi"), plan["period"],
                    plan.get("dims"), plan.get("filters"))
    return payload


def _plan_any(question: str) -> Dict[str, Any]:
    if planner.is_lag_question(question):
        period = L.parse_time(question)
        return planner.plan_lag(period, [(d, op, v) for d, op, v in L.detect_filters(question)
                                         if not d.startswith("__")])
    if planner.is_risk_question(question):
        return planner.plan_risk(L.parse_time(question))
    return planner.plan_metric(question)


def _plan_with_session(question: str, session: dict, drill: bool) -> Dict[str, Any]:
    """多轮下钻：沿用上一轮指标，替换维度或期间。"""
    kpi = L.find_kpi(question) or session.get("last_kpi")
    if not kpi:
        return {"kind": "unsupported", "reason": "未能确定要查询的指标"}
    period = L.parse_time(question)
    if not re.search(r"(月|年|季|近|上|本|当)", question) and session.get("last_period"):
        period = session["last_period"]
    filters = [(d, op, v) for d, op, v in L.detect_filters(question) if not d.startswith("__")]
    dims: List[str] = []
    if re.search(r"(按|分|各).{0,4}(分公司|单位)", question):
        dims = ["ORG"]
    elif re.search(r"(按|分|各).{0,4}(工程类型|板块|专业)", question):
        dims = ["ENG_TYPE"]
    elif re.search(r"(按|分|各).{0,4}(业主|客户)", question):
        dims = ["CUSTOMER"]
    elif re.search(r"(按|分|各).{0,4}(部门)", question):
        dims = ["DEPT"]
    elif re.search(r"(明细|哪些项目|按项目)", question):
        dims = ["PROJ"]
    elif re.search(r"(按|分|各).{0,4}(地市|城市)", question):
        dims = ["CITY"]
    elif drill:
        dims = [d for d in L.find_dims(question) if d not in ("PROVINCE",)]

    ctx = M.period_ctx(period["start"], period["end"])
    shape = L.find_shape(question)
    limit = L.find_topn(question) or (10 if shape == "rank" else None)
    sql = M.metric_sql(kpi, ctx, dims, filters, limit, order_desc=planner.detect_order(question))
    return {
        "kind": "metric", "sql": sql, "kpi": kpi, "kpi_name": M.METRICS[kpi]["name"],
        "unit": M.METRICS[kpi]["unit"], "dims": dims,
        "dim_names": [L.DIM_NAMES.get(d, d) for d in dims], "filters": filters,
        "period": period, "shape": shape, "limit": limit,
        "order_desc": planner.detect_order(question),
    }


def _update_session(session: dict, question: str, kpi: Optional[str], period: Optional[dict],
                    dims, filters) -> None:
    if kpi:
        session["last_kpi"] = kpi
    if period:
        session["last_period"] = period
    if dims is not None:
        session["last_dims"] = dims
    if filters is not None:
        session["last_filters"] = filters
    session["last_question"] = question


# ---------------------------------------------------------------------------
# 回答格式化
# ---------------------------------------------------------------------------

def _format_plan(plan: Dict[str, Any], res, user: Dict[str, Any], used_llm: bool,
                 question: str = "") -> Dict[str, Any]:
    rows = res.rows
    unit = plan.get("unit", "")
    kpi = plan.get("kpi")
    columns = list(rows[0].keys()) if rows else []

    # 列级脱敏：利润类指标对非财务岗位一律脱敏（无论是否有值）
    from app.config import FIN_ROLES, MASK_TEXT
    if kpi and M.METRICS.get(kpi, {}).get("cat") == "CAT_PROFIT" and user["role"] not in FIN_ROLES:
        rows = [dict(r, VAL=MASK_TEXT) for r in rows]
        columns = list(rows[0].keys()) if rows else columns

    explain = planner.compose_explain(plan)
    related = _related(kpi, plan.get("dims"), plan.get("period"))

    if plan["kind"] == "trend":
        out = _format_trend(plan, rows, unit, user)
        out["related"] = related
        return out
    if plan["kind"] in ("lag", "risk"):
        out = _format_table_plan(plan, res, user)
        out["related"] = related
        return out
    if plan["kind"] == "archive":
        out = _format_archive(plan, rows, user)
        out["related"] = related
        return out

    if not rows:
        return {"answer": "查询未返回数据：%s。可能是该期间无业务发生，或过滤条件过严。\n\n可以试试放宽时间范围，或去掉部分筛选条件。"
                          % explain,
                "sql": plan["sql"], "rows": [], "chart": None, "explain": explain,
                "degraded": False, "unit": unit, "related": related}

    # 单值
    if not plan.get("dims"):
        v = rows[0].get("VAL")
        text = _single_answer(plan, v, unit, user, question)
        return {"answer": text, "sql": plan["sql"], "rows": rows, "columns": columns,
                "chart": None, "explain": explain, "degraded": False, "unit": unit,
                "kpi": kpi, "related": related}

    # 分组：占比形态补一列
    if plan.get("shape") == "share" and "VAL" in rows[0]:
        total = sum(float(r.get("VAL") or 0) for r in rows) or 1
        rows = [dict(r, SHARE=round(float(r.get("VAL") or 0) / total * 100, 2)) for r in rows]

    value_name = "%s(%s)" % (plan["kpi_name"], unit) if unit else plan["kpi_name"]
    rows = [{(value_name if k == "VAL" else "占比(%)" if k == "SHARE" else k): v
             for k, v in _rename_dims(r).items()} for r in rows]
    columns = list(rows[0].keys()) if rows else columns
    dim_label = "、".join(plan.get("dim_names") or ["维度"])
    chart_kind = "pie" if plan.get("shape") == "share" else "bar"
    chart = _chart_from_rows(columns, rows, unit,
                             "share" if chart_kind == "pie" else "bar",
                             "%s（按%s）" % (plan["kpi_name"], dim_label),
                             value_col=value_name)
    top = rows[0]
    label_col = columns[0]
    head = "**%s**期间，按%s看 **%s**：**%s** 为 **%s %s**，居首。" % (
        plan["period"]["label"], dim_label, plan["kpi_name"],
        top.get(label_col), _fmt(top.get("VAL") if "VAL" in top else list(top.values())[1]), unit)
    if len(rows) > 1:
        vkey = list(top.keys())[1]
        first_v = float(top.get(vkey) or 0)
        last_v = float(rows[-1].get(vkey) or 0)
        if abs(first_v - last_v) < 1e-9:
            head += "\n各%s数量接近，差异不大。" % dim_label
        else:
            head += "\n末位是 **%s**（%s %s），首末差 %s %s。" % (
                rows[-1].get(label_col), _fmt(last_v), unit, _fmt(first_v - last_v), unit)
    table = _table_md(columns, rows, unit)
    return {"answer": head + "\n\n" + table, "sql": plan["sql"], "rows": rows,
            "columns": columns, "chart": chart, "explain": explain, "degraded": False,
            "unit": unit, "kpi": kpi, "related": related}

def _rename_dims(row: Dict[str, Any]) -> Dict[str, Any]:
    """把 D_ORG / D_PROJ 这类内部列名换成业务列名。"""
    out = {}
    for k, v in row.items():
        if k.startswith("D_"):
            dim = k[2:]
            out[L.DIM_NAMES.get(dim, dim)] = v
        else:
            out[k] = v
    return out


def _single_answer(plan: Dict[str, Any], value: Any, unit: str, user: Dict[str, Any],
                   question: str = "") -> str:
    kpi = plan.get("kpi")
    period = plan["period"]
    masked = isinstance(value, str)
    mom = yoy = None
    if kpi and not masked and not M.METRICS.get(kpi, {}).get("no_compare"):
        try:
            p_months = L._months_between(period["start"][:7], period["end"][:7])
            if p_months:
                pm = L._months_between(
                    L._shift(int(period["start"][:4]), int(period["start"][5:7]), -1),
                    L._shift(int(period["end"][:4]), int(period["end"][5:7]), -1))
                prev_ctx = M.period_ctx(pm[0] + "-01", planner._month_end(pm[-1]))
                mom = M.pct_change(float(value), M.metric_value(kpi, prev_ctx))
                lm = [m.replace(m[:4], str(int(m[:4]) - 1)) for m in p_months]
                last_ctx = M.period_ctx(lm[0] + "-01", planner._month_end(lm[-1]))
                yoy = M.pct_change(float(value), M.metric_value(kpi, last_ctx))
        except Exception:
            mom = yoy = None

    scope_txt = "全院" if not plan.get("filters") else "所选范围"
    lines = ["**%s**，%s **%s** 为 **%s %s**。" % (
        period["label"], scope_txt, plan["kpi_name"], _fmt(value), unit)]

    seg = []
    if mom is not None:
        seg.append("环比 %s%.2f%%" % ("+" if mom >= 0 else "", mom))
    if yoy is not None:
        seg.append("同比 %s%.2f%%" % ("+" if yoy >= 0 else "", yoy))
    if seg:
        order = seg
        if "同比" in question and len(seg) > 1:
            order = [x for x in seg if "同比" in x] + [x for x in seg if "同比" not in x]
        lines.append("（%s）。" % "，".join(order))
    if masked:
        lines.append("\n_当前岗位（%s）无利润类指标查看权限，已按权限中心规则脱敏。_" % user["role"])
    lines.append("\n口径：%s" % _kpi_caliber(kpi))
    return "".join(lines)


def _related(kpi: Optional[str], dims: Optional[List[str]], period: Optional[dict]) -> List[str]:
    """根据当前问题推荐三个可继续追问的方向（前端做成快捷按钮）。"""
    if not kpi or kpi not in M.METRICS:
        return ["2026年10月各分公司新签合同额排名", "近6个月营业收入趋势", "两金压降有什么要求"]
    name = M.METRICS[kpi]["name"]
    out = []
    if not dims or "ORG" not in (dims or []):
        out.append("%s按分公司拆分" % name)
    if not dims or "ENG_TYPE" not in (dims or []):
        out.append("%s按工程类型看" % name)
    out.append("近6个月%s趋势" % name)
    out.append("%s同比是多少" % name)
    return out[:3]

def _kpi_caliber(kpi: Optional[str]) -> str:
    if not kpi:
        return "—"
    conn = db.get_conn()
    row = conn.execute("""SELECT K.DEFINITION, C.CALIBER_NAME FROM DIM_KPI K
                          LEFT JOIN DIM_CALIBER C ON C.CALIBER_ID = K.CALIBER_ID
                          WHERE K.KPI_ID = ?""", (kpi,)).fetchone()
    conn.close()
    if row:
        return row["DEFINITION"] or row["CALIBER_NAME"] or ""
    return M.METRICS.get(kpi, {}).get("name", "")


def _format_table_plan(plan: Dict[str, Any], res, user: Dict[str, Any]) -> Dict[str, Any]:
    """滞后 / 风险清单类计划：直接展示明细表，并按关键列排序出图。"""
    rows = res.rows
    if not rows:
        return {"answer": "未发现符合条件的记录。", "sql": res.sql_oracle, "rows": [],
                "chart": None, "explain": planner.compose_explain(plan), "degraded": False}
    columns = list(rows[0].keys())
    value_col = next((c for c in ("缺口_万元", "完成率_百分比", "持续天数", "VAL") if c in columns),
                     columns[-1])
    label_col = next((c for c in ("项目名称", "项目", "分公司") if c in columns), columns[0])
    unit = "万元" if "万元" in value_col else ("%" if "百分比" in value_col else "")
    sort_rows = sorted(rows, key=lambda r: (r.get(value_col) or 0), reverse=True)
    chart = {
        "type": "bar", "title": plan.get("kpi_name", "清单"),
        "labels": [str(r.get(label_col)) for r in sort_rows[:10]],
        "series": [{"name": value_col, "data": [round(float(r.get(value_col) or 0), 2)
                                                for r in sort_rows[:10]]}],
        "unit": unit, "highlight": 0,
    }
    if plan["kind"] == "lag":
        head = ("**%s**，在建项目中实际产值低于计划 95%% 的有 **%d** 个，缺口最大的三个是："
                % (plan["period"]["label"], len(rows)))
        top3 = "、".join("%s（缺 %s 万元）" % (r.get("项目名称"), _fmt_cell(r.get("缺口_万元")))
                        for r in sort_rows[:3])
        head += top3 + "。"
    else:
        head = "当前仍在跟踪的风险事项共 **%d** 项，按持续天数排序如下（数据截至 %s）。" % (
            len(rows), plan["period"]["end"])
    return {"answer": head + "\n\n" + _table_md(columns, sort_rows, unit),
            "sql": res.sql_oracle, "rows": sort_rows, "columns": columns,
            "chart": chart, "explain": planner.compose_explain(plan), "degraded": False}


def _format_trend(plan: Dict[str, Any], rows, unit: str, user: Dict[str, Any]) -> Dict[str, Any]:
    points = plan["points"]
    vals = [(p["label"], p["value"]) for p in points if p["value"] is not None]
    if not vals:
        return {"answer": "该期间无可用趋势数据。", "sql": plan["sql"], "rows": [], "chart": None,
                "explain": planner.compose_explain(plan), "degraded": False}
    first, last = vals[0], vals[-1]
    peak = max(vals, key=lambda x: x[1])
    low = min(vals, key=lambda x: x[1])
    text = ("**%s** 期间 **%s** 逐月走势：%s 为 **%s %s**，%s 为 **%s %s**，累计变动 %s%%。"
            % (plan["period"]["label"], plan["kpi_name"], first[0], _fmt(first[1]), unit,
               last[0], _fmt(last[1]), unit,
               "%.2f" % ((last[1] - first[1]) / abs(first[1]) * 100) if first[1] else "—"))
    text += "\n月度峰值出现在 %s（%s %s），低点在 %s（%s %s）。" % (
        peak[0], _fmt(peak[1]), unit, low[0], _fmt(low[1]), unit)
    chart = {
        "type": "line", "title": "%s 月度趋势" % plan["kpi_name"],
        "labels": [v[0] for v in vals], "unit": unit,
        "series": [{"name": plan["kpi_name"], "data": [round(v[1], 2) for v in vals]}],
        "highlight": len(vals) - 1,
    }
    return {"answer": text, "sql": plan["sql"], "rows": [{"月份": v[0], "数值": v[1]} for v in vals],
            "columns": ["月份", "数值"], "chart": chart,
            "explain": planner.compose_explain(plan), "degraded": False, "unit": unit}


def _format_archive(plan: Dict[str, Any], rows, user: Dict[str, Any]) -> Dict[str, Any]:
    proj = plan["project"]
    if not rows:
        return {"answer": "未找到该项目档案。", "sql": plan["sql"], "rows": [], "chart": None,
                "explain": planner.compose_explain(plan), "degraded": False}
    r = rows[0]
    stats_txt = "；".join("%s %s %s" % (s["kpi"], _fmt(s["value"]), s["unit"]) for s in plan["stats"])
    text = ("### %s（%s）\n\n"
            "- **所属单位**：%s　**项目经理**：%s\n"
            "- **业主**：%s　**工程类型**：%s\n"
            "- **项目等级**：%s 类　**状态**：%s\n"
            "- **工期**：%s 至 %s　**地点**：%s %s\n"
            "- **合同额**：%s 万元　**装机/电压**：%s\n\n"
            "**2026 年 1-10 月经营情况**：%s"
            % (r.get("项目名称"), r.get("项目编码"), r.get("所属分公司"), r.get("项目经理"),
               r.get("业主"), r.get("工程类型"), r.get("项目等级"), r.get("项目状态"),
               r.get("开工日期"), r.get("计划完工"), r.get("省份"), r.get("地市"),
               _fmt_cell(r.get("合同额_万元")),
               ("%s MW" % r.get("装机容量_MW")) if r.get("装机容量_MW") else
               (("%s kV" % r.get("电压等级_kV")) if r.get("电压等级_kV") else "—"),
               stats_txt))
    return {"answer": text, "sql": plan["sql"], "rows": rows, "columns": list(r.keys()),
            "chart": None, "explain": planner.compose_explain(plan), "degraded": False}


def _format_generic(res, question: str, kpi: Optional[str], user: Dict[str, Any],
                    used_llm: bool) -> Dict[str, Any]:
    """大模型 SQL 的结果格式化（列名由模型给出）。"""
    rows = res.rows
    if not rows:
        return {"answer": "查询未返回数据，请调整时间范围或条件。", "sql": res.sql_oracle,
                "rows": [], "chart": None, "explain": "大模型生成 SQL", "degraded": False}
    columns = list(rows[0].keys())
    unit = M.METRICS.get(kpi, {}).get("unit", "") if kpi else ""
    text = ""
    if len(rows) == 1 and len(columns) == 1:
        v = rows[0][columns[0]]
        text = "结果为 **%s**。" % _fmt_cell(v, unit)
    else:
        text = _table_md(columns, rows, unit)
    chart = _chart_from_rows(columns, rows, unit, "bar",
                             M.METRICS.get(kpi, {}).get("name", "查询结果") if kpi else "查询结果")
    return {"answer": text, "sql": res.sql_oracle, "rows": rows, "columns": columns,
            "chart": chart, "explain": "大模型生成 SQL（已做 Oracle 11g 方言校验与权限注入）",
            "degraded": False, "llm_used": used_llm, "unit": unit, "kpi": kpi}


def _answer_kb(question: str) -> Dict[str, Any]:
    r = kb.answer(question)
    return {"answer": r["answer"], "sql": None, "rows": [], "chart": None,
            "sources": r["sources"], "explain": "知识库检索（BM25 字符二元组）",
            "degraded": False, "found": r["found"],
            "related": ["新签合同额的口径是什么", "两金压降有什么要求",
                        "经营分析报告的编制规范"]}


def _answer_chat(question: str) -> Dict[str, Any]:
    return {
        "answer": "我是广东院经营数据助手，能帮你做三件事：\n\n"
                  "- **取数**：各分公司 10 月新签合同额排名 / 近 6 个月营业收入趋势\n"
                  "- **查档案**：某个项目的合同额、工期、业主、产值与风险\n"
                  "- **查制度**：两金压降要求、指标口径、报告编制规范\n\n"
                  "直接说业务问题就行，不用写 SQL。",
        "sql": None, "rows": [], "chart": None, "explain": "闲聊引导",
        "degraded": False,
        "related": ["2026年10月各分公司新签合同额排名", "近6个月营业收入趋势", "两金压降有什么要求"],
    }


def _answer_clarify(question: str, session: dict, extra: str = "") -> Dict[str, Any]:
    """澄清：给出最接近的指标与可执行示例，而不是一句"没听懂"。"""
    import difflib
    names = [M.METRICS[k]["name"] for k in M.KPI_ORDER]
    guess = difflib.get_close_matches(question, names, n=3, cutoff=0.25)
    opts = ["2026年10月各分公司新签合同额排名",
            "2026年9月营业收入同比",
            "近6个月营业收入趋势",
            "危大工程数量最多的5个项目",
            "两金压降有什么要求"]
    head = "没太听明白：%s。" % (extra or "问题里没有可识别的指标或项目")
    if guess:
        head += "\n\n你要问的是不是：**%s**？" % "、".join(guess)
    head += "\n\n换个说法也可以，例如：\n%s" % "\n".join("- " + o for o in opts)
    return {"answer": head, "sql": None, "rows": [], "chart": None, "clarify": opts,
            "explain": "触发澄清反问", "degraded": False, "related": guess or opts[:3]}
