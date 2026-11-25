# -*- coding: utf-8 -*-
"""报告兜底校验脚本：正则 + 规则，防止"格式错乱、数值幻觉、指标异常"进生产。

三类校验：
  R 系列 —— 结构/格式（章节齐全、单位规范、数字格式、禁用模糊词）
  N 系列 —— 数值（指标值与宽表一致、报告内数字可追溯）
  B 系列 —— 业务异常（同比波动超阈值必须说明、整改率红线）
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

FORBIDDEN_UNITS = ["亿元", "美元", "元整"]
VAGUE_WORDS = ["大概", "可能", "或许", "估计", "差不多", "应该是"]
REQUIRED_CHAPTERS = ["经营总览", "合同签约", "收入与利润", "回款与两金",
                     "项目履约与产值", "安全与风险", "结论与建议"]


def _strip_noise(text: str) -> str:
    """去掉时间戳、日期、元信息行，避免把 15:52 之类当成指标数字。"""
    text = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)
    text = re.sub(r"\d{1,2}:\d{2}(:\d{2})?", " ", text)
    # 项目名里自带的编号（佛山220千伏、陆上风电2期、±800kV）不是指标值
    text = re.sub(r"[±\d.]+\s*(千伏|kV|KV|千乏|兆瓦|MW|万千瓦|期)", " ", text)
    text = "\n".join(l for l in text.split("\n") if not l.strip().startswith("> "))
    return text


def _scannable(text: str) -> str:
    """只扫描"会承载数值"的部分：表格跳过首列（项目名/分公司名里可能带 220千伏 这类数字）。"""
    out: List[str] = []
    for line in text.split("\n"):
        t = line.strip()
        if t.startswith("|") and t.endswith("|") and len(t) > 3:
            cells = t.strip("|").split("|")
            if len(cells) > 1:
                out.append(" ".join(cells[1:]))
            continue
        out.append(line)
    return "\n".join(out)


def _numbers(text: str) -> List[float]:
    out = []
    for m in re.finditer(r"-?\d[\d,]*\.?\d*", text):
        raw = m.group(0).replace(",", "")
        try:
            out.append(float(raw))
        except ValueError:
            pass
    return out


def _close(a: float, b: float, tol: float = 0.01) -> bool:
    if b == 0:
        return abs(a) < 1e-6
    return abs(a - b) / abs(b) <= tol


def validate(content: str, rows: List[Dict[str, Any]],
             role: str = "院长",
             extra_numbers: Optional[List[float]] = None) -> Dict[str, Any]:
    """执行全套校验。

    extra_numbers：明细表 / 派生占比里出现、但不在全院指标清单中的数字
    （分公司、项目维度的数值，以及合计、占比等），由报告生成器登记，
    避免明细表被误判为"数值幻觉"。
    """
    items: List[Dict[str, Any]] = []

    def add(rule: str, ok: bool, level: str, msg: str, detail: str = "") -> None:
        items.append({"rule": rule, "ok": ok, "level": level, "message": msg, "detail": detail})

    # ---------- R1 章节完整性 ----------
    missing = [c for c in REQUIRED_CHAPTERS if c not in content]
    add("R1 章节完整性", not missing, "error",
        "七个章节齐全" if not missing else "缺少章节：%s" % "、".join(missing))

    # ---------- R2 单位规范 ----------
    bad_units = [u for u in FORBIDDEN_UNITS if u in content]
    add("R2 单位规范", not bad_units, "error",
        "金额单位统一为万元" if not bad_units else "出现非规范单位：%s" % "、".join(bad_units))

    # ---------- R3 数字格式 ----------
    over_precision = re.findall(r"\d+\.\d{4,}", content)
    add("R3 数字格式", not over_precision, "warn",
        "小数位不超过两位" if not over_precision else "存在超精度数字：%s" % "、".join(over_precision[:3]))

    # ---------- R4 禁用模糊表述 ----------
    hits = [w for w in VAGUE_WORDS if w in content]
    add("R4 表述严谨性", not hits, "warn",
        "无模糊表述" if not hits else "出现模糊词：%s" % "、".join(hits))

    # ---------- R5 章节篇幅 ----------
    sections = re.split(r"\n## ", content)
    short = []
    for sec in sections[1:]:
        title = sec.split("\n")[0].strip()
        body = re.sub(r"[#>*\-\s]", "", sec[len(title):])
        if title in REQUIRED_CHAPTERS and len(body) < 100:
            short.append(title)
    add("R5 章节篇幅", not short, "warn",
        "各章篇幅充足" if not short else "篇幅不足：%s" % "、".join(short))

    # ---------- N1 指标值与宽表一致性 ----------
    body = content.split("## 附")[0]          # 附录是同比波动说明，不参与主体数值比对
    mismatches = []
    checked = 0
    for r in rows:
        name = r["kpi_name"]
        if name not in body:
            continue
        checked += 1
        value = float(r["value"] or 0)
        unit = r["unit"]
        hit = False
        first_cand: Optional[float] = None
        for m in re.finditer(re.escape(name), body):
            tail = body[m.end(): m.end() + 24]
            nm = re.search(r"-?\d[\d,]*\.?\d*", tail)
            if not nm:
                continue
            cand = float(nm.group(0).replace(",", ""))
            after = tail[nm.end(): nm.end() + 1]
            if first_cand is None:
                first_cand = cand
            # 百分比指标才允许取百分号后面的数值
            if after == "%" and unit != "%":
                continue
            if _close(cand, value, 0.01):
                hit = True
                break
        if not hit and first_cand is not None:
            mismatches.append("%s 报告值 %.2f ≠ 宽表值 %.2f" % (name, first_cand, value))
    add("N1 指标一致性", not mismatches, "error",
        "文中指标值与宽表一致（核对 %d 项）" % checked if not mismatches
        else "数值与宽表不一致：%s" % "；".join(mismatches[:3]))

    # ---------- N2 数值可追溯（幻觉检测）----------
    allowed: List[float] = []
    for r in rows:
        for k in ("value", "prev_value", "last_year_value", "yoy", "mom"):
            v = r.get(k)
            if isinstance(v, (int, float)):
                allowed += [float(v), round(float(v), 2), round(float(v), 1), round(float(v))]
                # 正文常写"同比下降 12.34%"，用绝对值比对
                allowed += [abs(float(v)), round(abs(float(v)), 2), round(abs(float(v)), 1)]
    # 派生占比：任意两个指标值的比值
    vals = [float(r["value"]) for r in rows if isinstance(r.get("value"), (int, float))]
    for a in vals[:12]:
        for b in vals[:12]:
            if b:
                allowed.append(round(a / b * 100, 1))
                allowed.append(round(a / b * 100, 2))
    allowed += [float(y) for y in range(2020, 2030)]
    allowed += [float(m) for m in range(1, 13)]
    allowed += [95.0, 90.0, 30.0, 20.0, 45.0, 100.0]
    for v in extra_numbers or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        allowed += [f, round(f, 2), round(f, 1)]

    suspect = []
    for n in _numbers(_strip_noise(_scannable(content))):
        if abs(n) < 50:          # 小数字（月份、个数、页数）不参与幻觉判定
            continue
        if any(_close(n, a, 0.006) for a in allowed):
            continue
        suspect.append(n)
    add("N2 数值可追溯", not suspect, "error",
        "所有金额类数字均可追溯至指标宽表" if not suspect
        else "疑似幻觉数字：%s" % "、".join("%.2f" % s for s in suspect[:5]))

    # ---------- B1 异常波动必须说明 ----------
    exceptions = [r for r in rows if r["yoy"] is not None and abs(r["yoy"]) >= 30
                  and r["category"] != "CAT_EFF"]
    appendix = content.split("## 附")[1] if "## 附" in content else ""
    unexplained = []
    for r in exceptions:
        if r["kpi_name"] in appendix and re.search(r"(波动|异常|核实)", appendix):
            continue
        if r["kpi_name"] not in content:
            unexplained.append(r["kpi_name"] + "（未提及）")
            continue
        idx = content.find(r["kpi_name"])
        near = content[max(0, idx - 150): idx + 220]
        if not re.search(r"(波动|异常|原因|核实|差异|需说明)", near):
            unexplained.append(r["kpi_name"])
    add("B1 异常波动说明", not unexplained, "error",
        "异常波动指标均已说明" if not unexplained
        else "波动超 30%% 未说明：%s" % "、".join(unexplained[:3]))

    # ---------- B2 安全红线 ----------
    fix_rate = next((r["value"] for r in rows if r["kpi_id"] == "AQ_HAZARD_FIX_RATE"), None)
    ok_b2 = True
    if fix_rate is not None and float(fix_rate) < 90:
        ok_b2 = bool(re.search(r"(挂牌|督办|整改|限期)", content))
    add("B2 安全红线", ok_b2, "error",
        "隐患整改率红线处理得当" if ok_b2 else "整改率低于 90% 但未提出督办要求")

    # ---------- B3 结论与建议 ----------
    has_advice = bool(re.search(r"建议", content)) and len(
        re.findall(r"(建议|一是|二是|1）|2）)", content)) >= 1
    add("B3 结论与建议", has_advice, "warn",
        "报告含明确建议" if has_advice else "缺少可执行建议")

    total = len(items)
    passed = sum(1 for i in items if i["ok"])
    score = round(passed / total * 100, 1)
    return {
        "passed": passed == total,
        "total": total,
        "passed_count": passed,
        "score": score,
        "items": items,
        "blocking": [i for i in items if not i["ok"] and i["level"] == "error"],
    }
