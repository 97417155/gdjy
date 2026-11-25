# -*- coding: utf-8 -*-
"""行业词表：指标同义词、维度关键词、时间表达式解析。

这一层是"同义词 & 指标口径知识库"的可执行部分：业务人员说的
"新签"、"两金"、"形象进度"都要能落到登记过的指标上。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# 指标同义词（越长优先级越高）
KPI_SYNONYMS: Dict[str, List[str]] = {
    "HS_NEW_AMT": ["新签合同额", "新签合同", "新签额", "新签", "合同签约额", "合同额"],
    "HS_CHARGE_SIGN": ["收费合同签订额", "收费合同", "收费签约"],
    "HS_SIGNIN": ["签入合同额", "签入合同", "签入额", "签入"],
    "HS_CHANGE_AMT": ["合同变更额", "合同变更", "变更额", "变更金额"],
    "HS_AVG_UNIT": ["单体合同均值", "平均合同额", "单均合同", "单体规模"],
    "SR_OPERATE": ["营业收入", "营业总收入", "营收", "收入"],
    "SR_DESIGN": ["设计咨询收入", "设计收入", "咨询收入", "设计费收入"],
    "SR_PER_STAFF": ["人均营业收入", "人均收入", "人均营收"],
    "LR_TOTAL": ["利润总额", "利润"],
    "LR_COST": ["营业成本", "成本"],
    "LR_GROSS_RATE": ["毛利率", "毛利率水平"],
    "LR_PROJ_MARGIN": ["项目平均毛利率", "项目毛利率"],
    "HK_AMT": ["回款额", "回款金额", "回款"],
    "HK_RATE": ["回款率", "回款比例"],
    "HK_AR_BAL": ["应收账款余额", "应收账款", "应收余额", "应收"],
    "HK_AR_OVER1Y": ["长账龄应收占比", "长账龄", "一年以上应收", "账龄结构"],
    "HK_TWOGOLD": ["两金占用", "两金", "两金规模"],
    "CZ_OUTPUT": ["在建项目产值", "产值"],
    "CZ_FINISH_RATE": ["产值完成率", "完成率"],
    "CZ_IMAGE_PROGRESS": ["平均形象进度", "形象进度", "进度"],
    "CZ_PROJ_ACTIVE": ["在建项目数", "在建数量", "在建个数", "在建项目有多少", "在建的项目数"],
    "AQ_HAZARD_CNT": ["危大工程数", "危大工程", "危大"],
    "AQ_HAZARD_FIX_RATE": ["隐患整改率", "整改率"],
    "AQ_RISK_CNT": ["风险事项数", "风险事项", "风险数量", "风险项目", "风险清单"],
    "AQ_OVERDUE_CNT": ["超期关键管理动作", "超期未关闭", "超期", "逾期"],
    "RL_STAFF_HOURS": ["投入工时", "工时"],
    "RL_STAFF_CNT": ["投入人数", "人数", "人员数量"],
    "RL_PROJ_PER_PM": ["人均在管项目", "人均项目"],
}

DIM_KEYWORDS: Dict[str, List[str]] = {
    "ORG": ["分公司", "各家", "各单位", "各经营单位", "按单位", "各二级单位"],
    "DEPT": ["部门", "各部门", "各科室"],
    "ENG_TYPE": ["工程类型", "业务类型", "业务板块", "板块", "专业类型", "各专业"],
    "PROJ_TYPE": ["项目等级", "按等级", "等级", "类别"],
    "CUSTOMER": ["业主", "客户", "业主单位", "甲方"],
    "CITY": ["地市", "城市", "各地市", "地区"],
    "PROVINCE": ["省份", "省内省外", "区域"],
    "PM": ["项目经理", "负责人"],
    "PROJ": ["项目", "工程", "各项目"],
    "STATUS": ["项目状态", "状态"],
}

DIM_NAMES = {
    "ORG": "分公司", "DEPT": "部门", "ENG_TYPE": "工程类型", "PROJ_TYPE": "项目等级",
    "CUSTOMER": "业主", "CITY": "地市", "PROVINCE": "省份", "PM": "项目经理",
    "PROJ": "项目", "STATUS": "项目状态",
}

ENG_TYPES = ["输变电", "配电网", "火电", "燃机", "风电", "光伏", "储能",
             "市政", "交通", "环境", "水务"]

BRANCH_ALIAS = {
    "电网分公司": "O101", "火电分公司": "O102", "新能源分公司": "O103",
    "市政交通分公司": "O104", "环境水务分公司": "O105", "国际工程分公司": "O106",
    "电网": "O101", "火电": "O102", "新能源": "O103", "市政交通": "O104",
    "环境水务": "O105", "国际工程": "O106",
}

CITIES = ["广州", "深圳", "珠海", "汕头", "佛山", "韶关", "湛江", "肇庆", "江门", "茂名",
          "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞", "中山", "潮州", "揭阳", "云浮"]

SHAPE_WORDS = {
    "trend": ["趋势", "走势", "变化", "逐月", "每个月", "近几个月", "走势图"],
    "rank": ["排名", "最高", "最低", "最多", "最少", "前三", "前五", "top", "前几", "排行", "领先"],
    "share": ["占比", "结构", "构成", "分布", "比例"],
    "list": ["明细", "清单", "列出", "有哪些", "哪些", "列表"],
}

REF_YEAR = 2026
REF_MONTH = 10


def _months_between(m1: str, m2: str) -> List[str]:
    y, m = int(m1[:4]), int(m1[5:7])
    ey, em = int(m2[:4]), int(m2[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _range_from_months(months: List[str], label: str, kind: str = "month") -> dict:
    start = months[0] + "-01"
    y, m = int(months[-1][:4]), int(months[-1][5:7])
    nm_y, nm_m = (y + 1, 1) if m == 12 else (y, m + 1)
    end = "%04d-%02d-01" % (nm_y, nm_m)
    from datetime import date, timedelta
    end = (date(nm_y, nm_m, 1) - timedelta(days=1)).isoformat()
    return {"start": start, "end": end, "months": months, "label": label, "kind": kind}


def parse_time(q: str) -> dict:
    """解析时间表达式，默认取当期（2026 年 10 月）。"""
    t = q.replace(" ", "")

    # 近 N 个月 / 近半年 / 近三个月
    m = re.search(r"近(\d+|[一二三四五六七八九十]+)个?月", t)
    if m:
        raw = m.group(1)
        cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
              "九": 9, "十": 10, "十一": 11, "十二": 12}
        n = int(raw) if raw.isdigit() else cn.get(raw, 6)
        months = _months_between(_shift(REF_YEAR, REF_MONTH, -(n - 1)), "%04d-%02d" % (REF_YEAR, REF_MONTH))
        return _range_from_months(months, "近%d个月" % n, "trend")
    if "近半年" in t or "最近半年" in t:
        months = _months_between("2026-05", "2026-10")
        return _range_from_months(months, "近半年", "trend")

    # 年份
    ym = re.search(r"(20\d{2})年(\d{1,2})月", t)
    if ym:
        y, mo = int(ym.group(1)), int(ym.group(2))
        return _range_from_months(["%04d-%02d" % (y, mo)], "%d年%d月" % (y, mo))
    if "去年" in t:
        return _range_from_months(_months_between("2025-01", "2025-12"), "2025年", "year")
    if "今年" in t or "本年度" in t:
        return _range_from_months(_months_between("2026-01", "2026-10"), "2026年1-10月", "year")
    if re.search(r"20\d{2}年$", t):
        y = int(re.search(r"(20\d{2})年", t).group(1))
        end_m = 10 if y == REF_YEAR else 12
        return _range_from_months(_months_between("%d-01" % y, "%d-%02d" % (y, end_m)), "%d年" % y, "year")

    if "三季度" in t or "Q3" in t.upper():
        return _range_from_months(["2026-07", "2026-08", "2026-09"], "2026年三季度", "quarter")
    if "二季度" in t or "Q2" in t.upper():
        return _range_from_months(["2026-04", "2026-05", "2026-06"], "2026年二季度", "quarter")
    if "上半年" in t:
        return _range_from_months(_months_between("2026-01", "2026-06"), "2026年上半年", "half")
    if "上月" in t or "上个月" in t:
        return _range_from_months(["2026-09"], "2026年9月")
    if "本月" in t or "当期" in t or "双周" in t or "这一期" in t:
        return _range_from_months(["2026-10"], "2026年10月")

    m = re.search(r"(\d{1,2})月", t)
    if m:
        mo = int(m.group(1))
        if 1 <= mo <= 12:
            y = REF_YEAR if mo <= REF_MONTH else REF_YEAR - 1
            return _range_from_months(["%04d-%02d" % (y, mo)], "%d年%d月" % (y, mo))

    return _range_from_months(["2026-10"], "2026年10月")


def _shift(y: int, m: int, delta: int) -> str:
    total = y * 12 + (m - 1) + delta
    return "%04d-%02d" % (total // 12, total % 12 + 1)


def find_kpi(q: str) -> Optional[str]:
    """最长匹配优先，避免"回款率"被误判为"回款"。"""
    best, best_len = None, 0
    for kpi, words in KPI_SYNONYMS.items():
        for w in words:
            if w in q and len(w) > best_len:
                best, best_len = kpi, len(w)
    return best


def find_dims(q: str) -> List[str]:
    dims = []
    for dim, words in DIM_KEYWORDS.items():
        if any(w in q for w in words):
            dims.append(dim)
    # "项目"过于常见，只有在出现明确的分组语气时才作为维度
    if "PROJ" in dims and not re.search(r"(各|按|每|分)项目", q):
        dims.remove("PROJ")
    # 排除互斥：有具体分公司过滤时不再按分公司分组
    if re.search(r"(按|分|各).{0,4}分公司", q) and "ORG" not in dims:
        dims.append("ORG")
    return dims


def find_shape(q: str) -> str:
    for shape, words in SHAPE_WORDS.items():
        if any(w in q for w in words):
            return shape
    return "single"


def find_topn(q: str) -> Optional[int]:
    cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
          "九": 9, "十": 10}
    m = re.search(r"(?:前|top|TOP)\s*(\d+)", q)
    if m:
        return int(m.group(1))
    m = re.search(r"(?:前|top|TOP)\s*([一二三四五六七八九十])", q)
    if m:
        return cn.get(m.group(1))
    m = re.search(r"(\d+)\s*个(?:项目|分公司|部门|单位|工程类型|板块)", q)
    if m:
        return int(m.group(1))
    m = re.search(r"([一二三四五六七八九十])\s*个(?:项目|分公司|部门|单位|工程类型|板块)", q)
    if m:
        return cn.get(m.group(1))
    return None


def detect_filters(q: str) -> List[Tuple[str, str, object]]:
    """识别问题中的业务过滤条件。"""
    filters: List[Tuple[str, str, object]] = []
    if "省外" in q:
        filters.append(("PROVINCE", "!=", "广东"))
    elif "省内" in q or "广东省内" in q:
        filters.append(("PROVINCE", "=", "广东"))
    m = re.search(r"([ABCD])\s*类", q)
    if m:
        filters.append(("PROJ_TYPE", "=", m.group(1)))
    if "在建" in q:
        filters.append(("STATUS", "=", "在建"))
    if "已完工" in q or "完工项目" in q:
        filters.append(("STATUS", "=", "已完工"))
    for alias, oid in BRANCH_ALIAS.items():
        if alias in q and len(alias) >= 3:
            filters.append(("ORG", "=", oid))
            break
    for eng in ENG_TYPES:
        if eng in q:
            filters.append(("ENG_TYPE", "=", eng))
            break
    for city in CITIES:
        if city in q:
            filters.append(("CITY", "=", city))
            break
    if "高风险" in q:
        filters.append(("__RISK_LEVEL", "=", "高风险"))
    return filters


def has_kb_intent(q: str) -> bool:
    """制度/口径类意图：要求出现业务名词 + 制度性问法，避免"怎么办"误判。"""
    strong = re.search(r"(规定|办法|制度|口径|流程|规范|依据|标准|规则|政策|细则|要求|管理要求)", q)
    if strong:
        return True
    weak = re.search(r"(为什么|怎么|如何|是什么|有哪些要求)", q)
    noun = re.search(r"(两金|指标|合同|权限|报告|危大|隐患|风险|立项|签入|回款|应收|收入|利润)", q)
    return bool(weak and noun)


def has_archive_intent(q: str) -> bool:
    return bool(re.search(r"(档案|基本情况|概况|介绍|详情|哪个项目|项目信息|画像)", q))


def has_drill_intent(q: str) -> bool:
    return bool(re.search(r"(下钻|再按|拆分|分开看|展开|细分|那按|换成)", q))
