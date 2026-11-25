# -*- coding: utf-8 -*-
"""BI 驾驶舱数据：卡片指标 + 图表规格（前端直接渲染，无需 ECharts）。"""
from __future__ import annotations

from typing import Any, Dict, List

from app import metrics as M, permission
from app.config import MASK_TEXT, FIN_ROLES

TOP = ["HS_NEW_AMT", "SR_OPERATE", "LR_TOTAL", "HK_RATE"]

CARDS = [
    ("CAT_CONTRACT", "HS_NEW_AMT"),
    ("CAT_REVENUE", "SR_OPERATE"),
    ("CAT_PROFIT", "LR_GROSS_RATE"),
    ("CAT_CASH", "HK_RATE"),
    ("CAT_OUTPUT", "CZ_FINISH_RATE"),
    ("CAT_RISK", "AQ_HAZARD_FIX_RATE"),
    ("CAT_EFF", "RL_STAFF_HOURS"),
]


def _shift_range(start: str, end: str, months: int) -> tuple:
    """把期间整体前移/后移 N 个月，返回 (start, end)。"""
    from calendar import monthrange
    def _mv(ym: str, delta: int) -> tuple:
        total = int(ym[:4]) * 12 + (int(ym[5:7]) - 1) + delta
        return total // 12, total % 12 + 1
    sy, sm = _mv(start, months)
    ey, em = _mv(end, months)
    return ("%04d-%02d-%02d" % (sy, sm, int(start[8:10])),
            "%04d-%02d-%02d" % (ey, em, monthrange(ey, em)[1]))


def build(user: Dict[str, Any], period_start: str, period_end: str) -> Dict[str, Any]:
    ctx = M.period_ctx(period_start, period_end)
    filters = permission.scope_filters(user)
    masked_role = user["role"] not in FIN_ROLES

    # 同比 / 环比（上一月、去年同月）
    y, m = int(period_end[:4]), int(period_end[5:7])
    pm = M.month_list(period_start, period_end)
    prev_ctx = M.period_ctx(*_shift_range(period_start, period_end, -len(pm)))
    yoy_ctx = M.period_ctx(*_shift_range(period_start, period_end, -12 * max(1, len(pm)) // max(1, len(pm))))

    def _delta(kpi: str) -> Dict[str, Any]:
        cur = M.metric_value(kpi, ctx, filters)
        mom = M.pct_change(cur, M.metric_value(kpi, prev_ctx, filters))
        yoy = M.pct_change(cur, M.metric_value(kpi, yoy_ctx, filters))
        return {"mom": mom, "yoy": yoy}

    top: List[Dict[str, Any]] = []
    for kpi in TOP:
        val = round(float(M.metric_value(kpi, ctx, filters)), 2)
        masked = masked_role and M.METRICS[kpi]["cat"] == "CAT_PROFIT"
        d = _delta(kpi) if not masked else {"mom": None, "yoy": None}
        top.append({
            "kpi": kpi, "name": M.METRICS[kpi]["name"], "unit": M.METRICS[kpi]["unit"],
            "value": MASK_TEXT if masked else val, "masked": masked,
            "mom": d["mom"], "yoy": d["yoy"],
        })

    cards: List[Dict[str, Any]] = []
    for cat, kpi in CARDS:
        val = M.metric_value(kpi, ctx, filters)
        try:
            val = round(float(val), 2)
        except (TypeError, ValueError):
            pass
        masked = masked_role and M.METRICS[kpi]["cat"] == "CAT_PROFIT"
        cards.append({
            "kpi": kpi,
            "category": cat,
            "category_name": M.CATEGORIES[cat],
            "name": M.METRICS[kpi]["name"],
            "value": MASK_TEXT if masked else val,
            "unit": M.METRICS[kpi]["unit"],
            "masked": masked,
        })

    # 图 1：分公司新签合同额
    rank = M.query_metric("HS_NEW_AMT", ctx, ["ORG"], filters, None)
    chart_rank = {
        "type": "bar", "title": "各分公司新签合同额（万元）",
        "labels": [r.get("D_ORG") for r in rank],
        "series": [{"name": "新签合同额", "data": [round(r.get("VAL") or 0, 2) for r in rank]}],
        "unit": "万元",
    }

    # 图 2：近 6 个月收入趋势
    months = M.month_list("2026-05", "2026-10")
    series = []
    for m in months:
        mm = M.period_ctx(m + "-01", m + "-28")
        series.append(round(M.metric_value("SR_OPERATE", mm, filters) or 0, 2))
    chart_trend = {
        "type": "line", "title": "近 6 个月营业收入（万元）",
        "labels": months, "series": [{"name": "营业收入", "data": series}], "unit": "万元",
    }

    # 图 3：工程类型收入结构
    eng = M.query_metric("SR_OPERATE", ctx, ["ENG_TYPE"], filters, None)
    chart_eng = {
        "type": "pie", "title": "营业收入结构（按工程类型）",
        "labels": [r.get("D_ENG_TYPE") for r in eng],
        "series": [{"name": "营业收入", "data": [round(r.get("VAL") or 0, 2) for r in eng]}],
        "unit": "万元",
    }

    # 风险清单
    from app.nl2sql import planner, repair
    lag = planner.plan_lag({"start": period_start, "end": period_end,
                            "label": "%s 至 %s" % (period_start, period_end),
                            "months": [period_start[:7]], "kind": "month"}, [])
    risk_rows = []
    try:
        res, _ = repair.run_with_repair(lag["sql"], user)
        risk_rows = (res.rows if res else [])[:6]
    except Exception:
        risk_rows = []

    return {
        "top": top,
        "period": {"start": period_start, "end": period_end,
                   "label": "%s 年 %s 月" % (period_end[:4], int(period_end[5:7]))},
        "cards": cards,
        "charts": [chart_rank, chart_trend, chart_eng],
        "risks": risk_rows,
        "scope": permission.scope_desc(user),
        "masked": masked_role,
        "user": {"name": user["name"], "role": user["role"], "org": user["org_name"]},
    }
