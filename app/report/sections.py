# -*- coding: utf-8 -*-
"""报告章节构建器：把指标数据组装成"文字论述 + 数据表格"混排的正文。

设计要点：
  * 每一章都是「结论句 → 明细表 → 分析 → 措施」四段式，避免只有大段文字；
  * 表格数据全部来自指标引擎（带岗位过滤条件），不手工编数；
  * 表格内与正文里派生出来的数字都登记到 extra_numbers，供校验脚本做
    "数值可追溯"核对，否则分公司 / 项目维度的明细会被误判成幻觉数字。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app import metrics as M

# 越小越好的指标；未登记的默认按"增长为正向"处理
DOWN_IS_GOOD = {"AQ_HAZARD_CNT", "AQ_RISK_CNT", "AQ_OVERDUE_CNT",
                "HK_AR_BAL", "HK_TWOGOLD", "HK_AR_OVER1Y"}


def fmt_metric(v: Any, unit: str = "") -> str:
    """统一数字格式：金额两位小数、百分比两位、计数取整。"""
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
    if unit in ("个", "人"):
        return "{:,}".format(int(round(f)))
    return "{:,.2f}".format(f)


def dir_text(v: Optional[float]) -> str:
    if v is None:
        return "无可比基期"
    if abs(v) < 0.5:
        return "基本持平"
    return "%s %.2f%%" % ("增长" if v > 0 else "下降", abs(v))


def judge(kpi: str, yoy: Optional[float]) -> str:
    """把同比转成业务判断词，区分"越大越好"和"越小越好"的指标。"""
    if yoy is None:
        return "—"
    if abs(yoy) < 0.5:
        return "持平"
    positive = (yoy > 0) == (kpi not in DOWN_IS_GOOD)
    return "改善" if positive else "承压"


class Num:
    """带单位的数字单元：表格里不同列单位不同（万元 / % / 个），逐个标注。"""

    __slots__ = ("v", "unit")

    def __init__(self, v: Any, unit: str = "") -> None:
        self.v = v
        self.unit = unit


class Doc:
    """轻量 Markdown 累加器，顺带登记所有出现过的数字。"""

    def __init__(self) -> None:
        self.lines: List[str] = []
        self.nums: List[float] = []

    # ---------- 结构 ----------
    def title(self, text: str) -> None:
        self.lines += ["# %s" % text, ""]

    def quote(self, text: str) -> None:
        self.lines += ["> %s" % text, ""]

    def h2(self, text: str) -> None:
        self.lines += ["", "## %s" % text, ""]

    def h3(self, text: str) -> None:
        self.lines += ["", "**%s**" % text, ""]

    def p(self, text: str) -> None:
        self.lines += [text, ""]

    def bullets(self, items: Sequence[str]) -> None:
        for it in items:
            self.lines.append("- %s" % it)
        if items:
            self.lines.append("")

    def num(self, *vals: Any) -> None:
        """登记正文里的派生数字（合计、占比、缺口等），供校验追溯。"""
        for v in vals:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                self.nums.append(float(v))

    # ---------- 表格 ----------
    def table(self, headers: Sequence[str], rows: Sequence[Sequence[Any]],
              units: Optional[Sequence[str]] = None) -> None:
        units = list(units or [""] * len(headers))
        align = ["---" if not u else "---:" for u in units]
        self.lines.append("| " + " | ".join(headers) + " |")
        self.lines.append("| " + " | ".join(align) + " |")
        for row in rows:
            cells: List[str] = []
            for i, cell in enumerate(row):
                unit = units[i] if i < len(units) else ""
                if isinstance(cell, Num):
                    if isinstance(cell.v, (int, float)):
                        self.nums.append(float(cell.v))
                    cells.append(fmt_metric(cell.v, cell.unit))
                elif isinstance(cell, (int, float)) and not isinstance(cell, bool):
                    self.nums.append(float(cell))
                    cells.append(fmt_metric(cell, unit))
                else:
                    cells.append(str(cell) if cell is not None else "—")
            self.lines.append("| " + " | ".join(cells) + " |")
        self.lines.append("")

    def markdown(self) -> str:
        return "\n".join(self.lines).strip() + "\n"


# ---------------------------------------------------------------------------
# 取数工具
# ---------------------------------------------------------------------------

def _group(kpi: str, dim: str, ctx: Dict[str, str],
           filters: Optional[List] = None) -> List[Tuple[str, float]]:
    """按维度取指标值，返回 [(维度值, 数值)]，按数值降序。"""
    if kpi not in M.METRICS:
        return []
    try:
        rows = M.query_metric(kpi, ctx, [dim], filters, None)
    except Exception:
        return []
    key = "D_%s" % dim
    out = [(str(r.get(key) or "—"), float(r.get("VAL") or 0)) for r in rows]
    return sorted(out, key=lambda x: -x[1])


def _org_dim(filters: Optional[List]) -> Tuple[str, str]:
    """分公司负责人只看得到一家分支，此时下钻到部门维度才有信息量。"""
    for f in filters or []:
        if str(f[0]) == "ORG" and len(f) > 1 and f[1] == "=":
            return "DEPT", "部门"
    return "ORG", "分公司"


def _top(pairs: List[Tuple[str, float]], n: int = 6) -> List[Tuple[str, float, float]]:
    total = sum(v for _, v in pairs) or 1.0
    return [(k, v, v / total * 100) for k, v in pairs[:n]]


def _unit_of(vm: Dict[str, Dict[str, Any]], keys: Sequence[str]) -> str:
    for k in keys:
        if k in vm:
            return vm[k].get("unit", "")
    return ""


# ---------------------------------------------------------------------------
# 各章节
# ---------------------------------------------------------------------------

def _ch1_overview(d: Doc, vm: Dict[str, Dict[str, Any]], scope_word: str,
                  mask_profit: bool = False) -> None:
    g = lambda k: vm.get(k, {}).get("value")
    y = lambda k: vm.get(k, {}).get("yoy")
    m_ = lambda k: vm.get(k, {}).get("mom")

    d.h2("一、经营总览")
    lead = ("本期%s实现新签合同额 %s 万元，同比%s；实现营业收入 %s 万元，同比%s；"
            % (scope_word,
               fmt_metric(g("HS_NEW_AMT"), "万元"), dir_text(y("HS_NEW_AMT")),
               fmt_metric(g("SR_OPERATE"), "万元"), dir_text(y("SR_OPERATE"))))
    if not mask_profit:
        lead += "利润总额 %s 万元，同比%s；" % (fmt_metric(g("LR_TOTAL"), "万元"),
                                          dir_text(y("LR_TOTAL")))
    lead += "回款额 %s 万元，回款率 %s。整体经营%s。" % (
        fmt_metric(g("HK_AMT"), "万元"), fmt_metric(g("HK_RATE"), "%"),
        "保持稳中有进" if (y("SR_OPERATE") or 0) >= 0 else "承压运行")
    d.p(lead)

    keys = ["HS_NEW_AMT", "SR_OPERATE"] + ([] if mask_profit else
                                          ["LR_TOTAL", "LR_GROSS_RATE"]) + \
           ["HK_AMT", "HK_RATE", "CZ_OUTPUT", "CZ_FINISH_RATE"]
    rows = []
    for k in keys:
        if k not in vm:
            continue
        r = vm[k]
        rows.append([r["kpi_name"], Num(r.get("value"), r["unit"]),
                     Num(r.get("prev_value"), r["unit"]),
                     Num(r.get("yoy"), "%") if r.get("yoy") is not None else "—",
                     Num(r.get("mom"), "%") if r.get("mom") is not None else "—",
                     judge(k, r.get("yoy"))])
    if rows:
        d.table(["指标", "本期", "上期", "同比", "环比", "判断"], rows)

    # 按"改善程度"排序：逆向指标（越小越好）取相反的符号
    def score(item: Tuple[str, Dict[str, Any]]) -> float:
        k, r = item
        yoy = r.get("yoy") or 0
        return -yoy if k in DOWN_IS_GOOD else yoy

    ranked = sorted([(k, vm[k]) for k in vm if vm[k].get("yoy") is not None],
                    key=score, reverse=True)
    def line(k: str, r: Dict[str, Any]) -> str:
        # 带上本期值：既方便阅读，也让"指标名"后面紧跟的就是可核对的数
        return "%s %s，同比%s" % (r["kpi_name"], fmt_metric(r.get("value"), r["unit"]),
                                 dir_text(r["yoy"]))

    good = [line(k, r) for k, r in ranked[:2] if score((k, r)) > 0.5]
    bad = [line(k, r) for k, r in ranked[::-1][:2] if score((k, r)) < -0.5]
    if good:
        d.h3("主要亮点")
        d.bullets(good)
    if bad:
        d.h3("需要关注")
        d.bullets(bad)


def _ch2_contract(d: Doc, vm: Dict[str, Dict[str, Any]], ctx: Dict[str, str],
                  filters: Optional[List]) -> None:
    g = lambda k: vm.get(k, {}).get("value")
    y = lambda k: vm.get(k, {}).get("yoy")
    m_ = lambda k: vm.get(k, {}).get("mom")

    d.h2("二、合同签约")
    new_amt = g("HS_NEW_AMT") or 0
    charge = g("HS_CHARGE_SIGN") or 0
    ratio = charge / (new_amt or 1) * 100
    d.num(ratio)
    d.p("本期新签合同额 %s 万元，同比%s，环比%s；单体合同均值 %s 万元/个。"
        "收费合同签订额 %s 万元，占新签的 %.2f%%，%s。"
        % (fmt_metric(new_amt, "万元"), dir_text(y("HS_NEW_AMT")),
           dir_text(m_("HS_NEW_AMT")), fmt_metric(g("HS_AVG_UNIT"), "万元/个"),
           fmt_metric(charge, "万元"), ratio,
           "收费条款落实到位" if ratio > 70 else "收费条款落实不足，需加强合同评审"))

    dim, dim_name = _org_dim(filters)
    pairs = _group("HS_NEW_AMT", dim, ctx, filters)
    if pairs:
        d.h3("新签合同额按%s分布" % dim_name)
        d.table([dim_name, "新签合同额(万元)", "占比(%)"],
                [[k, v, s] for k, v, s in _top(pairs)], ["", "万元", "%"])
        total = sum(v for _, v in pairs) or 1
        top3 = sum(v for _, v in pairs[:3])
        share = top3 / total * 100
        first_share = pairs[0][1] / total * 100
        d.num(top3, share, first_share)
        d.p("从分布看，%s 居首，新签 %s 万元，占 %.2f%%；前三名合计 %s 万元，占 %.2f%%，"
            "集中度%s。"
            % (pairs[0][0], fmt_metric(pairs[0][1], "万元"), first_share,
               fmt_metric(top3, "万元"), share,
               "较高，需关注单一区域波动风险" if share > 99.5
               else ("较高" if share > 65 else "适中，结构相对均衡")))
    else:
        d.p("本期未取得%s维度的合同明细，分布分析从略。" % dim_name)

    eng = _group("HS_NEW_AMT", "ENG_TYPE", ctx, filters)
    if eng:
        d.h3("新签合同额按工程类型分布")
        d.table(["工程类型", "新签合同额(万元)", "占比(%)"],
                [[k, v, s] for k, v, s in _top(eng)], ["", "万元", "%"])
        eng_total = sum(v for _, v in eng) or 1
        ne = sum(v for k, v in eng if any(t in k for t in ("风电", "光伏", "储能")))
        d.num(ne, ne / eng_total * 100)
        d.p("业务结构上，%s 占比最高（%.2f%%）；新能源类（风电、光伏、储能）合计 %s 万元，"
            "占全部新签的 %.2f%%。"
            % (eng[0][0], eng[0][1] / eng_total * 100, fmt_metric(ne, "万元"),
               ne / eng_total * 100))


def _ch3_revenue(d: Doc, vm: Dict[str, Dict[str, Any]], ctx: Dict[str, str],
                 filters: Optional[List], mask_profit: bool) -> None:
    g = lambda k: vm.get(k, {}).get("value")
    y = lambda k: vm.get(k, {}).get("yoy")

    d.h2("三、收入与利润")
    if mask_profit:
        d.p("本期实现营业收入 %s 万元，其中设计咨询收入 %s 万元，收入同比%s。"
            "按《经营数据权限管理办法》，利润与成本类指标对当前岗位脱敏，本章仅列示收入侧数据。"
            % (fmt_metric(g("SR_OPERATE"), "万元"), fmt_metric(g("SR_DESIGN"), "万元"),
               dir_text(y("SR_OPERATE"))))
    else:
        d.p("本期实现营业收入 %s 万元，其中设计咨询收入 %s 万元；利润总额 %s 万元，"
            "毛利率 %s，项目平均毛利率 %s，人均营业收入 %s 万元/人。收入同比%s，%s。"
            % (fmt_metric(g("SR_OPERATE"), "万元"), fmt_metric(g("SR_DESIGN"), "万元"),
               fmt_metric(g("LR_TOTAL"), "万元"), fmt_metric(g("LR_GROSS_RATE"), "%"),
               fmt_metric(g("LR_PROJ_MARGIN"), "%"), fmt_metric(g("SR_PER_STAFF"), "万元/人"),
               dir_text(y("SR_OPERATE")),
               "盈利能力保持稳定" if (y("LR_GROSS_RATE") or 0) >= -1 else "毛利率有所下滑，需关注成本管控"))

    keys = ["SR_OPERATE", "SR_DESIGN"] + ([] if mask_profit else
                                         ["LR_TOTAL", "LR_GROSS_RATE", "LR_PROJ_MARGIN", "SR_PER_STAFF"])
    rows = []
    for k in keys:
        if k not in vm:
            continue
        r = vm[k]
        rows.append([r["kpi_name"], Num(r.get("value"), r["unit"]),
                     Num(r.get("prev_value"), r["unit"]),
                     Num(r.get("yoy"), "%") if r.get("yoy") is not None else "—",
                     judge(k, r.get("yoy"))])
    if rows:
        d.h3("收入与利润指标")
        d.table(["指标", "本期", "上年同期", "同比", "判断"], rows)

    eng = _group("SR_OPERATE", "ENG_TYPE", ctx, filters)
    if eng:
        d.h3("营业收入按工程类型分布")
        d.table(["工程类型", "营业收入(万元)", "占比(%)"],
                [[k, v, s] for k, v, s in _top(eng)], ["", "万元", "%"])
        eng_total = sum(v for _, v in eng) or 1
        head_share = eng[0][1] / eng_total * 100
        d.num(head_share)
        d.p("收入结构中 %s 贡献最大（%.2f%%），%s 次之。建议对高贡献板块保持资源倾斜，"
            "同时关注低毛利业务的占比变化。"
            % (eng[0][0], head_share, eng[1][0] if len(eng) > 1 else "其他板块"))

    if not mask_profit:
        grade = _group("LR_GROSS_RATE", "PROJ_TYPE", ctx, filters)
        if grade:
            d.h3("各项目等级毛利率")
            d.table(["项目等级", "毛利率(%)"], [[k, v] for k, v in grade], ["", "%"])
            a_rate = next((v for k, v in grade if k == "A"), None)
            d.p("A 类项目毛利率 %s，体现高等级项目的溢价能力，可作为后续投标结构调整的参照。"
                % fmt_metric(a_rate, "%"))


def _ch4_cash(d: Doc, vm: Dict[str, Dict[str, Any]], ctx: Dict[str, str],
              filters: Optional[List]) -> None:
    g = lambda k: vm.get(k, {}).get("value")
    y = lambda k: vm.get(k, {}).get("yoy")

    d.h2("四、回款与两金")
    d.p("本期回款 %s 万元，回款率 %s，同比%s。期末应收账款余额 %s 万元，两金占用 %s 万元，"
        "长账龄应收占比 %s。%s"
        % (fmt_metric(g("HK_AMT"), "万元"), fmt_metric(g("HK_RATE"), "%"), dir_text(y("HK_RATE")),
           fmt_metric(g("HK_AR_BAL"), "万元"), fmt_metric(g("HK_TWOGOLD"), "万元"),
           fmt_metric(g("HK_AR_OVER1Y"), "%"),
           "两金规模可控，符合年度压降目标。" if (g("HK_AR_OVER1Y") or 0) < 20
           else "长账龄占比偏高，需按“一笔一策”推进清收。"))

    keys = ["HK_AMT", "HK_RATE", "HK_AR_BAL", "HK_TWOGOLD", "HK_AR_OVER1Y"]
    rows = []
    for k in keys:
        if k not in vm:
            continue
        r = vm[k]
        rows.append([r["kpi_name"], Num(r.get("value"), r["unit"]),
                     Num(r.get("prev_value"), r["unit"]),
                     Num(r.get("yoy"), "%") if r.get("yoy") is not None else "—",
                     judge(k, r.get("yoy"))])
    if rows:
        d.table(["指标", "本期", "上期", "同比", "判断"], rows)

    dim, dim_name = _org_dim(filters)
    cash = dict(_group("HK_AMT", dim, ctx, filters))
    ar = dict(_group("HK_AR_BAL", dim, ctx, filters))
    two = dict(_group("HK_TWOGOLD", dim, ctx, filters))
    order = [k for k, _ in sorted(two.items(), key=lambda x: -x[1])][:6]
    if order:
        d.h3("%s回款与两金占用" % dim_name)
        d.table([dim_name, "回款额(万元)", "应收账款余额(万元)", "两金占用(万元)"],
                [[k, cash.get(k, 0), ar.get(k, 0), two.get(k, 0)] for k in order],
                ["", "万元", "万元", "万元"])
        top = order[0]
        share = two[top] / (sum(two.values()) or 1) * 100
        d.num(share)
        d.p("两金占用规模最大的是 %s，占用 %s 万元，占全部两金的 %.2f%%；该单位本期回款 %s 万元，"
            "%s。" % (top, fmt_metric(two[top], "万元"), share, fmt_metric(cash.get(top, 0), "万元"),
                      "对压降形成支撑" if cash.get(top, 0) > 0 else "回款滞后，需专项督办"))


def _ch5_output(d: Doc, vm: Dict[str, Dict[str, Any]], ctx: Dict[str, str],
                filters: Optional[List]) -> None:
    g = lambda k: vm.get(k, {}).get("value")
    y = lambda k: vm.get(k, {}).get("yoy")

    d.h2("五、项目履约与产值")
    d.p("本期在建项目 %s 个，完成产值 %s 万元，产值完成率 %s，平均形象进度 %s。"
        "产值完成率同比%s，%s。"
        % (fmt_metric(g("CZ_PROJ_ACTIVE"), "个"), fmt_metric(g("CZ_OUTPUT"), "万元"),
           fmt_metric(g("CZ_FINISH_RATE"), "%"), fmt_metric(g("CZ_IMAGE_PROGRESS"), "%"),
           dir_text(y("CZ_FINISH_RATE")),
           "履约总体受控" if (g("CZ_FINISH_RATE") or 0) >= 95 else "部分项目产值滞后于计划，需加强资源投入"))

    keys = ["CZ_OUTPUT", "CZ_FINISH_RATE", "CZ_IMAGE_PROGRESS", "CZ_PROJ_ACTIVE"]
    unit = _unit_of(vm, keys)
    rows = [[vm[k]["kpi_name"], Num(vm[k].get("value"), vm[k]["unit"]),
             Num(vm[k].get("prev_value"), vm[k]["unit"]),
             Num(vm[k].get("yoy"), "%") if vm[k].get("yoy") is not None else "—"]
            for k in keys if k in vm]
    if rows:
        d.table(["指标", "本期", "上期", "同比"], rows)

    dim, dim_name = _org_dim(filters)
    rate = _group("CZ_FINISH_RATE", dim, ctx, filters)
    out = dict(_group("CZ_OUTPUT", dim, ctx, filters))
    low = [x for x in rate if x[1] < 95][:6]
    if low:
        d.h3("产值完成率偏低的%s" % dim_name)
        d.table([dim_name, "产值完成率(%)", "完成产值(万元)"],
                [[k, v, out.get(k, 0)] for k, v in low], ["", "%", "万元"])

    proj_rate = _group("CZ_FINISH_RATE", "PROJ", ctx, filters)
    proj_out = dict(_group("CZ_OUTPUT", "PROJ", ctx, filters))
    lag = sorted([(k, v) for k, v in proj_rate if v < 95], key=lambda x: x[1])[:6]
    if lag:
        d.h3("产值滞后的在建项目")
        d.table(["项目名称", "产值完成率(%)", "完成产值(万元)"],
                [[k, v, proj_out.get(k, 0)] for k, v in lag], ["", "%", "万元"])
        d.p("上述 %d 个项目产值完成率低于 95%%，其中 %s 仅 %s，需逐项复核资源投入与节点计划，"
            "由项目管理部按周跟踪纠偏。" % (len(lag), lag[0][0], fmt_metric(lag[0][1], "%")))
    else:
        d.p("本期在建项目产值完成率均不低于 95%，履约节奏总体正常。")


def _ch6_risk(d: Doc, vm: Dict[str, Dict[str, Any]], ctx: Dict[str, str],
              filters: Optional[List]) -> None:
    g = lambda k: vm.get(k, {}).get("value")

    d.h2("六、安全与风险")
    d.p("本期新备案危大工程 %s 项，隐患整改率 %s；登记风险事项 %s 项，"
        "超期关键管理动作 %s 项。%s"
        % (fmt_metric(g("AQ_HAZARD_CNT"), "个"), fmt_metric(g("AQ_HAZARD_FIX_RATE"), "%"),
           fmt_metric(g("AQ_RISK_CNT"), "个"), fmt_metric(g("AQ_OVERDUE_CNT"), "个"),
           "安全生产形势总体平稳。" if (g("AQ_HAZARD_FIX_RATE") or 0) >= 90
           else "隐患整改率未达 90%，需挂牌督办、限期闭环。"))

    keys = ["AQ_HAZARD_CNT", "AQ_HAZARD_FIX_RATE", "AQ_RISK_CNT", "AQ_OVERDUE_CNT"]
    unit = _unit_of(vm, keys)
    rows = [[vm[k]["kpi_name"], Num(vm[k].get("value"), vm[k]["unit"]),
             Num(vm[k].get("prev_value"), vm[k]["unit"]),
             Num(vm[k].get("yoy"), "%") if vm[k].get("yoy") is not None else "—",
             judge(k, vm[k].get("yoy"))] for k in keys if k in vm]
    if rows:
        d.table(["指标", "本期", "上期", "同比", "判断"], rows)

    haz = _group("AQ_HAZARD_CNT", "PROJ", ctx, filters)
    if haz:
        top5 = _top(haz, 5)
        d.h3("危大工程数量居前的项目")
        d.table(["项目名称", "危大工程数(个)", "占比(%)"],
                [[k, v, s] for k, v, s in top5], ["", "个", "%"])
        cover = sum(s for _, _, s in top5)
        d.num(cover)
        d.p("危大工程集中于 %s 等项目，前 %d 个项目合计占全部备案方案的 %.2f%%，"
            "应作为专项检查与专家论证的重点对象。"
            % (haz[0][0], len(top5), cover))


def _ch7_advice(d: Doc, vm: Dict[str, Dict[str, Any]], mask_profit: bool) -> None:
    g = lambda k: vm.get(k, {}).get("value")
    y = lambda k: vm.get(k, {}).get("yoy")

    d.h2("七、结论与建议")
    d.p("综合来看，本期经营%s。主要矛盾集中在%s，建议按下表分工推进落实，"
        "并在下期经营例会上逐项复盘。"
        % ("稳中有进、结构持续优化" if (y("SR_OPERATE") or 0) >= 0 else "面临一定下行压力",
           "产值履约与两金压降" if ((g("CZ_FINISH_RATE") or 100) < 95
                                or (g("HK_AR_OVER1Y") or 0) > 20) else "市场开拓与收入转化"))

    items: List[List[Any]] = []

    def add(problem: str, action: str, dept: str) -> None:
        items.append([str(len(items) + 1), problem, action, dept])

    if (g("CZ_FINISH_RATE") or 100) < 95:
        add("在建项目产值完成率低于 95%", "逐项复核资源投入与节点计划，按月跟踪纠偏", "项目管理部")
    if (g("HK_AR_OVER1Y") or 0) > 20:
        add("长账龄应收占比超过 20%", "实行“一笔一策”清单管理，明确责任人与回收节点", "财务部")
    if (g("AQ_HAZARD_FIX_RATE") or 100) < 90:
        add("隐患整改率未达 90%", "未整改隐患挂牌督办，限期闭环并纳入安全考核", "安全质量部")
    if (y("HS_NEW_AMT") or 0) < 0:
        add("新签合同额同比下降", "加强重点区域市场布局与新能源业务投标力度", "市场商务部")
    if not mask_profit and (y("LR_GROSS_RATE") or 0) < -1:
        add("毛利率同比下滑", "复核分包与采购成本，压降非生产性支出", "财务部")
    if not items:
        add("各项指标总体符合预期", "保持现有经营节奏，重点跟踪边际下滑指标", "经营管理部")
    d.table(["序号", "问题", "措施", "责任部门"], items)


def _appendix(d: Doc, exceptions: List[Dict[str, Any]]) -> None:
    if not exceptions:
        return
    unit = exceptions[0].get("unit", "")
    d.h2("附：异常波动提示")
    d.p("下列指标同比波动超过 30%，已提请业务部门核实原因，核实结论随下期报告反馈。")
    d.table(["指标", "本期", "上年同期", "同比", "处理要求"],
            [[e["kpi_name"], Num(e.get("value"), e.get("unit", "")),
              Num(e.get("last_year_value"), e.get("unit", "")),
              Num(e.get("yoy"), "%"), "业务部门核实"] for e in exceptions])


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_sections(label: str, vm: Dict[str, Dict[str, Any]], period_start: str,
                   period_end: str, filters: Optional[List] = None,
                   scope_label: str = "全院", mask_profit: bool = False,
                   exceptions: Optional[List[Dict[str, Any]]] = None) -> Tuple[str, List[float]]:
    """组装完整报告正文，返回 (markdown, 出现过的所有数字)。"""
    from datetime import datetime

    ctx = M.period_ctx(period_start, period_end)
    scope_word = "全院" if scope_label in ("全院数据", "全院") else scope_label
    d = Doc()
    d.title("%s经营分析报告" % label)
    d.quote("数据来源：经营指标宽表（与 BI 平台 VW_FACT_KPI 口径对齐）｜数据范围：%s｜"
            "生成时间：%s" % (scope_label, datetime.now().strftime("%Y-%m-%d %H:%M")))

    _ch1_overview(d, vm, scope_word, mask_profit)
    _ch2_contract(d, vm, ctx, filters)
    _ch3_revenue(d, vm, ctx, filters, mask_profit)
    _ch4_cash(d, vm, ctx, filters)
    _ch5_output(d, vm, ctx, filters)
    _ch6_risk(d, vm, ctx, filters)
    _ch7_advice(d, vm, mask_profit)
    _appendix(d, exceptions or [])
    return d.markdown(), d.nums
