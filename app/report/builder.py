# -*- coding: utf-8 -*-
"""经营分析报告生成：指标抽取 -> 正文撰写 -> 落库。

正文撰写支持两种模式：
  * 有模型：把指标表 + 异常清单塞进报告范式提示词，让模型写（prompts.REPORT_SYSTEM），
    但要求它保留"文字 + 表格"混排结构，表格数量不足则退回内置引擎；
  * 无模型：走内置章节引擎（sections.py），每章「结论句 → 明细表 → 分析 → 措施」。

两种模式产出的报告都会过同一套校验脚本，口径和格式要求一致。
正文与表格里用到的指标快照随报告一起落库，校验时按报告自身口径复核，
避免"分公司报告拿全院口径去校验"的错配。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from app import db, metrics as M
from app.nl2sql import llm, prompts
from app.report import sections, validator
from app.report.sections import fmt_metric as _fmt
from app.report.sections import dir_text as _dir_text

CHAPTERS = [
    ("一、经营总览", ["HS_NEW_AMT", "SR_OPERATE", "LR_TOTAL", "HK_AMT"]),
    ("二、合同签约", ["HS_NEW_AMT", "HS_CHARGE_SIGN", "HS_SIGNIN", "HS_CHANGE_AMT", "HS_AVG_UNIT"]),
    ("三、收入与利润", ["SR_OPERATE", "SR_DESIGN", "SR_PER_STAFF", "LR_TOTAL", "LR_GROSS_RATE", "LR_PROJ_MARGIN"]),
    ("四、回款与两金", ["HK_AMT", "HK_RATE", "HK_AR_BAL", "HK_AR_OVER1Y", "HK_TWOGOLD"]),
    ("五、项目履约与产值", ["CZ_OUTPUT", "CZ_FINISH_RATE", "CZ_IMAGE_PROGRESS", "CZ_PROJ_ACTIVE"]),
    ("六、安全与风险", ["AQ_HAZARD_CNT", "AQ_HAZARD_FIX_RATE", "AQ_RISK_CNT", "AQ_OVERDUE_CNT"]),
    ("七、结论与建议", []),
]


def _ensure_columns() -> None:
    """老库迁移：补齐数据范围、指标快照、派生数字、生成轨迹四列。"""
    conn = db.get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(FACT_REPORT)")}
    adds = {
        "SCOPE_DESC": "TEXT DEFAULT '全院数据'",
        "METRICS_JSON": "TEXT",
        "EXTRA_JSON": "TEXT",
        "TRACE_JSON": "TEXT",
    }
    changed = False
    for name, ddl in adds.items():
        if name not in cols:
            conn.execute("ALTER TABLE FACT_REPORT ADD COLUMN %s %s" % (name, ddl))
            changed = True
    if changed:
        conn.commit()
    conn.close()


# 兼容旧调用
_ensure_scope_column = _ensure_columns


def period_label(start: str, end: str) -> str:
    return "%s年%s月" % (start[:4], int(start[5:7])) if start[:7] == end[:7] else "%s 至 %s" % (start, end)


def build(period_start: str, period_end: str, prev_start: str, prev_end: str,
          builder: str = "系统", filters: Optional[List] = None,
          scope_label: str = "全院", mask_profit: bool = False,
          role: str = "院长",
          hooks: Optional[Callable[[str, Any], None]] = None) -> Dict[str, Any]:
    """生成报告：宽表 -> 对比 -> 正文（文字+表格）-> 自检 -> 落库。

    filters 为岗位数据范围过滤条件，范围同时决定抬头、正文口径与图表明细，
    保证分公司负责人拿到的报告只反映本单位数据。
    hooks(kind, payload) 用于把每一步的进度推给前端（SSE），同时也记入
    TRACE_JSON 供事后追溯：谁在什么时候、哪一步花了多久。
    """
    trace: List[Dict[str, Any]] = []
    t_start = time.monotonic()
    t_last = [t_start]

    def begin(name: str, title: str, text: str) -> Dict[str, Any]:
        rec = {"name": name, "title": title, "text": text, "status": "running",
               "ms": 0, "at": 0}
        trace.append(rec)
        if hooks:
            try:
                hooks("stage", dict(rec))      # 传副本：避免队列里两次事件指向同一对象
            except Exception:
                pass
        return rec

    def finish(rec: Dict[str, Any], text: Optional[str] = None, status: str = "ok") -> None:
        now = time.monotonic()
        rec["ms"] = int((now - t_last[0]) * 1000)
        rec["at"] = int((now - t_start) * 1000)
        rec["status"] = status
        t_last[0] = now
        if text:
            rec["text"] = text
        if hooks:
            try:
                hooks("stage", dict(rec))
            except Exception:
                pass

    step = begin("metrics", "指标抽取", "读取 %d 项指标的本期、上期与上年同期数据" % len(M.KPI_ORDER))
    M.build_wide(period_start, period_end)
    rows = M.compare(period_start, period_end, prev_start, prev_end, filters)
    if mask_profit:
        rows = [r for r in rows if r["category"] != "CAT_PROFIT"]
    label = period_label(period_start, period_end)
    value_map = {r["kpi_id"]: r for r in rows}
    finish(step, "%d 项指标已抽取（%s 至 %s，数据范围：%s）"
           % (len(rows), period_start, period_end, scope_label))

    step = begin("compare", "同比环比", "计算同比、环比并识别异常波动")
    exceptions = [r for r in rows if r["yoy"] is not None and abs(r["yoy"]) >= 30
                  and r["category"] != "CAT_EFF"]
    finish(step, "同比/环比计算完成，识别异常波动 %d 项（阈值 ±30%%）" % len(exceptions))

    step = begin("compose", "正文撰写", "按七章体例生成文字与数据表")
    content, extra_numbers = sections.build_sections(
        label, value_map, period_start, period_end, filters,
        scope_label, mask_profit, exceptions)
    used_llm = False

    if llm.available():
        text = llm.chat([
            {"role": "system", "content": prompts.REPORT_SYSTEM},
            {"role": "user", "content": prompts.report_prompt(
                label, _kpi_block(rows), _exception_block(exceptions))},
        ], temperature=0.3, max_tokens=2600)
        # 模型输出必须同样保持"文字 + 表格"混排，否则用内置引擎的版本
        if text and text.count("##") >= 5 and text.count("|---") >= 5:
            content = _normalize(text, label)
            used_llm = True
            extra_numbers = []
    tables = content.count("\n| ---")
    finish(step, "七章正文完成：%d 字 / %d 张数据表（%s）"
           % (len(content), tables, "模型撰写" if used_llm else "内置文案引擎"))

    step = begin("guard", "兜底校验", "按 10 条规则检查章节、单位、数值可追溯与安全红线")
    pre_check = validator.validate(content, rows, role, extra_numbers)
    finish(step, "校验得分 %.1f（%d/%d 条通过）%s"
           % (pre_check["score"], pre_check["passed_count"], pre_check["total"],
              "" if pre_check["passed"] else "，存在 %d 项阻断" % len(pre_check["blocking"])),
           status="ok" if pre_check["passed"] else "warn")

    step = begin("save", "报告落库", "写入报告表并登记生成轨迹")
    _ensure_columns()
    report_id = "RP%s" % datetime.now().strftime("%Y%m%d%H%M%S")
    title = "%s经营分析报告（%s）" % (
        "" if scope_label in ("全院数据", "全院") else scope_label, label)
    db.execute_write(
        "INSERT INTO FACT_REPORT (REPORT_ID, PERIOD_START, PERIOD_END, TITLE, STATUS, BUILDER, "
        "CONTENT_MD, VALIDATE_JSON, CREATE_TIME, SCOPE_DESC, METRICS_JSON, EXTRA_JSON, TRACE_JSON) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (report_id, period_start, period_end, title, "草稿", builder, content, "",
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"), scope_label,
         json.dumps(rows, ensure_ascii=False, default=str),
         json.dumps(extra_numbers),
         json.dumps({"steps": trace, "total_ms": int((time.monotonic() - t_start) * 1000)},
                    ensure_ascii=False)))
    finish(step, "报告编号 %s，状态：草稿，可进入校验与审批" % report_id)
    db.execute_write("UPDATE FACT_REPORT SET TRACE_JSON=? WHERE REPORT_ID=?",
                     (json.dumps({"steps": trace,
                                  "total_ms": int((time.monotonic() - t_start) * 1000)},
                                 ensure_ascii=False), report_id))

    return {
        "report_id": report_id,
        "title": title,
        "label": label,
        "content_md": content,
        "metrics": rows,
        "exceptions": exceptions,
        "llm_used": used_llm,
        "tables": tables,
        "trace": {"steps": trace, "total_ms": int((time.monotonic() - t_start) * 1000)},
        "pre_check": pre_check,
    }


def _kpi_block(rows: List[Dict[str, Any]]) -> str:
    lines = []
    for r in rows:
        lines.append("%s（%s）：%s %s，同比 %s，环比 %s" % (
            r["kpi_name"], r["category_name"], _fmt(r["value"], r["unit"]), r["unit"],
            _fmt(r["yoy"], "%") if r["yoy"] is not None else "无基期",
            _fmt(r["mom"], "%") if r["mom"] is not None else "无基期"))
    return "\n".join(lines)


def _exception_block(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    return "\n".join("- %s 同比 %s，波动超过 30%%，需说明原因" % (r["kpi_name"], _fmt(r["yoy"], "%"))
                     for r in rows)


def _normalize(text: str, label: str) -> str:
    text = text.strip()
    if not text.startswith("#"):
        text = "# %s经营分析报告\n\n%s" % (label, text)
    return text


def prev_period(period_start: str, period_end: str) -> tuple:
    """上一期：按期间长度等长前移。"""
    months = M.month_list(period_start, period_end)
    n = len(months)
    y, m = int(period_start[:4]), int(period_start[5:7])
    total = y * 12 + (m - 1) - n
    ps = "%04d-%02d-01" % (total // 12, total % 12 + 1)
    py, pm = int(period_end[:4]), int(period_end[5:7])
    total2 = py * 12 + (pm - 1) - n
    from calendar import monthrange
    pe = "%04d-%02d-%02d" % (total2 // 12, total2 % 12 + 1,
                             monthrange(total2 // 12, total2 % 12 + 1)[1])
    return ps, pe


def build_metrics_snapshot(period_start: str, period_end: str) -> List[Dict[str, Any]]:
    ps, pe = prev_period(period_start, period_end)
    return M.compare(period_start, period_end, ps, pe)


def report_basis(report: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[float]]:
    """取报告自身的校验基准：优先用落库快照，老报告退回全院快照。"""
    try:
        rows = json.loads(report.get("METRICS_JSON") or "[]")
    except Exception:
        rows = []
    if not rows:
        rows = build_metrics_snapshot(report["PERIOD_START"], report["PERIOD_END"])
    try:
        extra = [float(x) for x in json.loads(report.get("EXTRA_JSON") or "[]")]
    except Exception:
        extra = []
    return rows, extra


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM FACT_REPORT WHERE REPORT_ID = ?", (report_id,)).fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(k, str) and k.isupper():
            d[k.lower()] = v
    d["approvals"] = [dict(r) for r in conn.execute(
        "SELECT * FROM FACT_APPROVAL WHERE REPORT_ID = ? ORDER BY OP_TIME", (report_id,))]
    d["push"] = [dict(r) for r in conn.execute(
        "SELECT * FROM FACT_PUSH_LOG WHERE REPORT_ID = ? ORDER BY PUSH_TIME", (report_id,))]
    conn.close()
    try:
        d["validate"] = json.loads(d["VALIDATE_JSON"]) if d["VALIDATE_JSON"] else None
    except Exception:
        d["validate"] = None
    try:
        d["trace"] = json.loads(d["TRACE_JSON"]) if d.get("TRACE_JSON") else None
    except Exception:
        d["trace"] = None
    return d


def latest(limit: int = 10) -> List[Dict[str, Any]]:
    conn = db.get_conn()
    _ensure_columns()
    rows = [dict(r) for r in conn.execute(
        "SELECT REPORT_ID, TITLE, STATUS, BUILDER, CREATE_TIME, SCOPE_DESC, "
        "PERIOD_START, PERIOD_END FROM FACT_REPORT ORDER BY CREATE_TIME DESC LIMIT ?", (limit,))]
    conn.close()
    return rows
