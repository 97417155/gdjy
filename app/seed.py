# -*- coding: utf-8 -*-
"""本地演示数据生成器（广东院能源工程咨询场景，29 张表）。

确定性随机（固定种子），可重复初始化。数据规模约 2 万行，
覆盖 2022-2026 年，能满足同比 / 环比 / 双周报等口径演示。
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from typing import List, Tuple

from app.config import DB_PATH, DB_DIR, DATA_END

SEED = 20260701
R = random.Random(SEED)

CITIES = ["广州", "深圳", "珠海", "汕头", "佛山", "韶关", "湛江", "肇庆", "江门", "茂名",
          "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞", "中山", "潮州", "揭阳", "云浮"]

ORG_TREE = [
    ("O000", "中国能建广东省电力设计研究院", None, 1, "全院", "广州"),
    ("O101", "电网分公司", "O000", 2, "分公司", "广州"),
    ("O102", "火电分公司", "O000", 2, "分公司", "广州"),
    ("O103", "新能源分公司", "O000", 2, "分公司", "广州"),
    ("O104", "市政交通分公司", "O000", 2, "分公司", "广州"),
    ("O105", "环境水务分公司", "O000", 2, "分公司", "广州"),
    ("O106", "国际工程分公司", "O000", 2, "分公司", "广州"),
]
DEPT_SUFFIX = [("01", "设计部"), ("02", "项目管理部"), ("03", "市场商务部")]
for oid, oname, _, lvl, typ, city in list(ORG_TREE):
    if lvl == 2:
        for suf, dname in DEPT_SUFFIX:
            ORG_TREE.append((oid + suf, "%s%s" % (oname.replace("分公司", ""), dname), oid, 3, "部门", city))

BRANCH_ENG = {
    "O101": ["输变电", "配电网"],
    "O102": ["火电", "燃机"],
    "O103": ["风电", "光伏", "储能"],
    "O104": ["市政", "交通"],
    "O105": ["环境", "水务"],
    "O106": ["输变电", "火电"],
}
ENG_PREFIX = {
    "输变电": ["500千伏", "220千伏", "110千伏"],
    "配电网": ["10千伏", "20千伏"],
    "火电": ["燃煤机组", "燃气-蒸汽联合循环"],
    "燃机": ["9F级燃机", "9H级燃机"],
    "风电": ["海上风电", "陆上风电"],
    "光伏": ["集中式光伏", "分布式光伏"],
    "储能": ["独立储能", "共享储能"],
    "市政": ["综合管廊", "市政道路"],
    "交通": ["城市轨道配套", "高速公路机电"],
    "环境": ["垃圾焚烧发电", "流域治理"],
    "水务": ["污水处理厂", "供水工程"],
}
ENG_SUFFIX = ["工程", "项目", "EPC总承包工程", "勘察设计工程", "扩建工程", "配套送出工程"]
OUT_PROVINCE = ["南宁", "海口", "昆明", "贵阳", "福州"]

CUSTOMERS = [
    ("C001", "广东电网有限责任公司", "电网", "广东"), ("C002", "深圳供电局有限公司", "电网", "深圳"),
    ("C003", "广东省能源集团有限公司", "发电", "广东"), ("C004", "国家能源集团广东电力有限公司", "发电", "广东"),
    ("C005", "华润电力（华南）有限公司", "发电", "广东"), ("C006", "中广核新能源控股有限公司", "发电", "广东"),
    ("C007", "深圳能源集团股份有限公司", "发电", "深圳"), ("C008", "广州发展集团股份有限公司", "发电", "广州"),
    ("C009", "广东省水利电力勘测设计研究院", "政府", "广东"), ("C010", "广州市城市建设投资集团", "政府平台", "广州"),
    ("C011", "东莞市交通投资集团", "政府平台", "东莞"), ("C012", "珠海华发集团有限公司", "政府平台", "珠海"),
    ("C013", "广东恒健投资控股有限公司", "投资", "广东"), ("C014", "南方电网调峰调频发电公司", "电网", "广东"),
    ("C015", "中电建新能源集团华南公司", "发电", "广东"), ("C016", "佛山市公用事业控股有限公司", "政府平台", "佛山"),
    ("C017", "惠州市水务集团有限公司", "政府平台", "惠州"), ("C018", "汕头市投资控股集团", "政府平台", "汕头"),
    ("C019", "中国广核电力股份有限公司", "发电", "深圳"), ("C020", "粤海控股集团", "投资", "广州"),
]

KPIS: List[Tuple[str, str, str, str, str, str, str]] = [
    # KPI_ID, 名称, 类别, 单位, 口径说明, 口径ID, 归口部门
    ("HS_NEW_AMT", "新签合同额", "CAT_CONTRACT", "万元", "统计期内收入类合同签订金额（含EPC、勘察设计），不含分包与采购合同", "CAL01", "市场商务部"),
    ("HS_CHARGE_SIGN", "收费合同签订额", "CAT_CONTRACT", "万元", "统计期内已明确收费节点与收费比例的合同金额", "CAL02", "市场商务部"),
    ("HS_SIGNIN", "签入合同额", "CAT_CONTRACT", "万元", "统计期内完成院内立项签入流程的合同金额", "CAL03", "市场商务部"),
    ("HS_CHANGE_AMT", "合同变更额", "CAT_CONTRACT", "万元", "统计期内合同变更累计增减金额（含正负）", "CAL04", "市场商务部"),
    ("HS_AVG_UNIT", "单体合同均值", "CAT_CONTRACT", "万元/个", "新签合同额 / 新签合同个数", "CAL01", "市场商务部"),
    ("SR_OPERATE", "营业收入", "CAT_REVENUE", "万元", "按完工百分比法确认的主营业务收入，与BI营业收入口径一致", "CAL05", "财务部"),
    ("SR_DESIGN", "设计咨询收入", "CAT_REVENUE", "万元", "统计期内确认的设计咨询类收入，不含总承包工程收入", "CAL05", "财务部"),
    ("SR_PER_STAFF", "人均营业收入", "CAT_REVENUE", "万元/人", "营业收入 / 期末在册人数", "CAL05", "财务部"),
    ("LR_TOTAL", "利润总额", "CAT_PROFIT", "万元", "营业收入 - 营业成本 - 期间费用 + 其他收益", "CAL06", "财务部"),
    ("LR_GROSS_RATE", "毛利率", "CAT_PROFIT", "%", "（营业收入 - 营业成本）/ 营业收入 × 100", "CAL06", "财务部"),
    ("LR_PROJ_MARGIN", "项目平均毛利率", "CAT_PROFIT", "%", "各在建项目毛利率的算术平均（按产值加权）", "CAL07", "项目管理部"),
    ("LR_COST", "营业成本", "CAT_PROFIT", "万元", "人工、分包、采购及其他直接成本合计", "CAL06", "财务部"),
    ("HK_AMT", "回款额", "CAT_CASH", "万元", "统计期内实际到账的工程款与设计费", "CAL08", "财务部"),
    ("HK_RATE", "回款率", "CAT_CASH", "%", "回款额 / 同期营业收入 × 100", "CAL08", "财务部"),
    ("HK_AR_BAL", "应收账款余额", "CAT_CASH", "万元", "期末应收账款账面余额（含质保金）", "CAL09", "财务部"),
    ("HK_AR_OVER1Y", "长账龄应收占比", "CAT_CASH", "%", "账龄超过1年的应收账款 / 应收账款余额 × 100", "CAL09", "财务部"),
    ("HK_TWOGOLD", "两金占用", "CAT_CASH", "万元", "应收账款余额 + 存货（未结算已完工未结转）", "CAL09", "财务部"),
    ("CZ_OUTPUT", "在建项目产值", "CAT_OUTPUT", "万元", "统计期内所有在建项目完成的产值合计", "CAL10", "项目管理部"),
    ("CZ_FINISH_RATE", "产值完成率", "CAT_OUTPUT", "%", "实际产值 / 计划产值 × 100", "CAL10", "项目管理部"),
    ("CZ_IMAGE_PROGRESS", "平均形象进度", "CAT_OUTPUT", "%", "在建项目形象进度的平均值", "CAL10", "项目管理部"),
    ("CZ_PROJ_ACTIVE", "在建项目数", "CAT_OUTPUT", "个", "统计期末状态为在建的项目个数", "CAL11", "项目管理部"),
    ("AQ_HAZARD_CNT", "危大工程数", "CAT_RISK", "个", "统计期内识别并在册的危大工程事项数", "CAL12", "安全监察部"),
    ("AQ_HAZARD_FIX_RATE", "隐患整改率", "CAT_RISK", "%", "已整改隐患 / 发现隐患 × 100", "CAL12", "安全监察部"),
    ("AQ_RISK_CNT", "风险事项数", "CAT_RISK", "个", "统计期内登记的风险事项数量", "CAL13", "风险管理部"),
    ("AQ_OVERDUE_CNT", "超期关键管理动作", "CAT_RISK", "个", "关键管理动作超期未关闭数量", "CAL13", "风险管理部"),
    ("RL_STAFF_HOURS", "投入工时", "CAT_EFF", "小时", "统计期内项目人员填报工时合计", "CAL14", "人力资源部"),
    ("RL_STAFF_CNT", "投入人数", "CAT_EFF", "人", "统计期内有工时填报的去重人数", "CAL14", "人力资源部"),
    ("RL_PROJ_PER_PM", "人均在管项目", "CAT_EFF", "个/人", "在建项目数 / 项目经理人数", "CAL11", "项目管理部"),
]

CALIBERS = [
    ("CAL01", "新签合同额口径", "收入类合同按签订日期归集，金额取合同总价（含税），不含补充协议；与BI“新签合同额”指标同源", 1),
    ("CAL02", "收费合同口径", "仅统计已约定收费节点、收费比例、结算方式的合同", 1),
    ("CAL03", "签入合同口径", "以院内立项签入完成日期为准，跨年签入不计入当年新签", 1),
    ("CAL04", "合同变更口径", "变更金额按审批完成日期归集，正负均计入", 0),
    ("CAL05", "营业收入口径", "完工百分比法确认，与BI营业收入表(VW_FACT_KPI)同源，差异需在报告中说明", 1),
    ("CAL06", "利润口径", "利润总额=营业收入-营业成本-期间费用+其他收益；毛利率不含期间费用", 1),
    ("CAL07", "项目毛利口径", "按项目产值加权平均，避免小项目拉偏均值", 0),
    ("CAL08", "回款口径", "银行到账日期归集，含预收款，不含票据背书", 1),
    ("CAL09", "两金口径", "应收账款含质保金；存货指已完工未结算部分", 1),
    ("CAL10", "产值口径", "按月度产值报表归集，计划产值取年初下达计划", 1),
    ("CAL11", "在建项目口径", "状态为“在建”，含新开工与续建，不含前期与暂停", 1),
    ("CAL12", "安全口径", "危大工程按专项方案备案数统计；隐患整改率按当期发现当期整改计算", 0),
    ("CAL13", "风险口径", "风险事项按登记入库口径，超期动作按OA审批节点计算", 0),
    ("CAL14", "人力口径", "工时取项目管理系统填报数据，按月度汇总", 0),
]


def _d(s: str) -> date:
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)


def _s(d: date) -> str:
    return d.isoformat()


def _month_list(start: str, end: str) -> List[str]:
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def build(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.executescript(DROP_SQL)
    c.executescript(DDL_SQL)

    # ---------------- 组织 / 人员 ----------------
    c.executemany("INSERT INTO DIM_ORG VALUES (?,?,?,?,?,?)", ORG_TREE)
    staff = []
    sid = 1
    orgs_l2 = [o for o in ORG_TREE if o[3] == 2]
    orgs_l3 = [o for o in ORG_TREE if o[3] == 3]

    def new_staff(name, org, role, title):
        nonlocal sid
        staff.append(("S%04d" % sid, name, org, role, title,
                      _s(date(2010, 1, 1) + timedelta(days=R.randint(0, 5000))), "在职"))
        sid += 1
        return "S%04d" % (sid - 1)

    top = new_staff("陈建国", "O000", "院长", "教授级高工")
    new_staff("李伟民", "O000", "副院长", "教授级高工")
    new_staff("黄志远", "O000", "财务专员", "高级会计师")
    new_staff("周敏", "O000", "财务专员", "会计师")
    branch_mgr = {o[0]: new_staff("张%d山" % (i + 1), o[0], "分公司负责人", "高级工程师")
                  for i, o in enumerate(orgs_l2)}
    dept_mgr = {o[0]: new_staff("刘%d峰" % (i + 1), o[0], "部门负责人", "高级工程师")
                for i, o in enumerate(orgs_l3)}
    pms = [new_staff("项目经理%02d" % i, R.choice(orgs_l3)[0], "项目经理", "工程师") for i in range(1, 41)]
    engineers = [new_staff("设计员%02d" % i, R.choice(orgs_l3)[0], "设计工程师", "工程师") for i in range(1, 61)]
    biz = [new_staff("商务%02d" % i, R.choice(orgs_l3)[0], "商务经理", "经济师") for i in range(1, 7)]
    c.executemany("INSERT INTO DIM_STAFF VALUES (?,?,?,?,?,?,?)", staff)

    # ---------------- 客户 / 项目 ----------------
    c.executemany("INSERT INTO DIM_CUSTOMER VALUES (?,?,?,?)", CUSTOMERS)
    projects, proj_ext, tags, members = [], [], [], []
    contract_rows, sub_rows, po_rows = [], [], []
    cid = 1
    used_names = {}
    for i in range(1, 301):
        branch = R.choice(orgs_l2)[0]
        dept = R.choice([o for o in orgs_l3 if o[0].startswith(branch)])
        eng = R.choice(BRANCH_ENG[branch])
        prefix = R.choice(ENG_PREFIX[eng])
        city = R.choice(CITIES)
        name = "%s%s%s" % (city, prefix, R.choice(ENG_SUFFIX))
        ptype = R.choices(["A", "B", "C", "D"], weights=[2, 4, 6, 4])[0]
        amt = {"A": R.randint(20000, 90000), "B": R.randint(5000, 20000),
               "C": R.randint(1000, 5000), "D": R.randint(80, 1000)}[ptype]
        start = date(2022, 1, 1) + timedelta(days=R.randint(0, 1500))
        dur = R.randint(420, 1650)
        end = start + timedelta(days=dur)
        if end < date(2026, 6, 1):
            status = "已完工"
            if R.random() < 0.45:      # 部分项目延期续建，保持在建项目基数稳定
                end = end + timedelta(days=R.randint(400, 900))
                status = "在建"
        elif start > date(2026, 8, 1):
            status = "前期"
        else:
            status = R.choices(["在建", "暂停"], weights=[9, 1])[0]
        code = "GD%04d-%04d" % (start.year, i)
        cust = R.choice(CUSTOMERS)[0]
        pm = R.choice(pms)
        org_id = dept[0]
        province = "广东"
        if R.random() < 0.12:
            city = R.choice(OUT_PROVINCE)
            province = {"南宁": "广西", "海口": "海南", "昆明": "云南", "贵阳": "贵州", "福州": "福建"}[city]
            name = "%s%s%s" % (city, prefix, R.choice(ENG_SUFFIX))
        used_names[name] = used_names.get(name, 0) + 1
        if used_names[name] > 1:
            name = "%s（%d期）" % (name, used_names[name])
        projects.append((code, name, org_id, pm, cust, ptype, status, _s(start), _s(end),
                         city, province, amt))
        cap = {"风电": R.randint(50, 600), "光伏": R.randint(30, 400), "储能": R.randint(50, 500),
               "火电": R.randint(300, 2000), "燃机": R.randint(200, 900),
               "输变电": 0, "配电网": 0, "市政": 0, "交通": 0, "环境": R.randint(10, 100),
               "水务": R.randint(5, 60)}.get(eng, 0)
        volt = {"输变电": R.choice([110, 220, 500]), "配电网": R.choice([10, 20])}.get(eng, 0)
        proj_ext.append((code, eng, cap, volt, 1 if R.random() < 0.45 else 0))
        if eng in ("风电", "光伏", "储能"):
            tags.append((code, "新能源"))
        if R.random() < 0.35:
            tags.append((code, "重点工程"))
        if R.random() < 0.2:
            tags.append((code, "省外项目"))
        picked = set()
        for _ in range(R.randint(2, 5)):
            st = R.choice(engineers + pms)
            if st in picked:
                continue
            picked.add(st)
            members.append((code, st, R.choice(["设计", "校核", "审核", "项目管理"])))

        # 合同：主合同 + 可能的变更
        sign = start - timedelta(days=R.randint(0, 90))
        is_charge = 1 if R.random() < 0.78 else 0
        is_signin = 1 if R.random() < 0.85 else 0
        contract_rows.append(("HT%05d" % cid, code, "CT01", amt, _s(sign), 0, branch, is_charge, is_signin))
        cid += 1
        if R.random() < 0.22:
            contract_rows.append(("HT%05d" % cid, code, "CT03", R.randint(20, 900),
                                  _s(sign + timedelta(days=R.randint(30, 400))), 1, branch, 0, 0))
            cid += 1
        # 分包 / 采购
        if ptype in ("A", "B") or R.random() < 0.5:
            for _ in range(R.randint(1, 3)):
                sub_rows.append(("FB%05d" % (len(sub_rows) + 1), code,
                                 R.choice(["广东电力建设一公司", "南方输变电工程公司", "中能建广东火电",
                                           "粤水电建设", "华电重工", "本地施工队"]),
                                 round(amt * R.uniform(0.08, 0.35), 2),
                                 _s(sign + timedelta(days=R.randint(60, 500))),
                                 R.choice(["土建", "安装", "调试", "勘察"])))
        for _ in range(R.randint(1, 4)):
            po_rows.append(("CG%05d" % (len(po_rows) + 1), code,
                            R.choice(["东方电气", "特变电工", "南瑞继保", "金风科技", "隆基绿能",
                                      "华为数字能源", "许继电气"]),
                            round(amt * R.uniform(0.02, 0.12), 2),
                            _s(sign + timedelta(days=R.randint(30, 600))),
                            R.choice(["主设备", "材料", "服务", "软件"])))

    c.executemany("""INSERT INTO DIM_PROJECT VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?)""", projects)
    c.executemany("INSERT INTO DIM_PROJECT_EXT VALUES (?,?,?,?,?)", proj_ext)
    c.executemany("INSERT INTO BRIDGE_PROJECT_TAG VALUES (?,?)", tags)
    c.executemany("INSERT INTO BRIDGE_PROJECT_STAFF VALUES (?,?,?)", members)
    # 补充 2025/2026 两个年度的三季度签约高峰（保证同比口径可比）
    cid = len(contract_rows) + 1
    pool = [p for p in projects if p[6] != "已完工"] or projects
    for year in (2025, 2026):
        for p in R.sample(pool, min(130, len(pool))):
            sign = date(year, 8, 1) + timedelta(days=R.randint(0, 85))
            amt2 = float(R.choices([R.randint(500, 4000), R.randint(4000, 12000), R.randint(12000, 30000)],
                                   weights=[6, 3, 1])[0])
            contract_rows.append(("HT%05d" % cid, p[0], R.choice(["CT01", "CT02"]), amt2, _s(sign), 0,
                                  p[2][:4], 1 if R.random() < 0.8 else 0, 1 if R.random() < 0.85 else 0))
            cid += 1
            if R.random() < 0.3:
                contract_rows.append(("HT%05d" % cid, p[0], "CT03", float(R.randint(50, 800)),
                                      _s(sign + timedelta(days=R.randint(10, 60))), 1, p[2][:4], 0, 0))
                cid += 1
    c.executemany("INSERT INTO FACT_CONTRACT VALUES (?,?,?,?,?,?,?,?,?)", contract_rows)
    c.executemany("INSERT INTO FACT_SUBCONTRACT VALUES (?,?,?,?,?,?)", sub_rows)
    c.executemany("INSERT INTO FACT_PROCUREMENT VALUES (?,?,?,?,?,?)", po_rows)

    # ---------------- 时间序列事实：收入/成本/回款/产值/应收/工时 ----------------
    months = _month_list("2025-01", "2026-10")
    rev, cost, col, prog, ar, hours = [], [], [], [], [], []
    for p in projects:
        code, _, org, pm, _, ptype, status, start_s, end_s, *_ = p
        s, e = _d(start_s), _d(end_s)
        if s > date(2026, 10, 31):
            continue
        for m in months:
            my, mm = int(m[:4]), int(m[5:7])
            mstart = date(my, mm, 1)
            if mstart < s or mstart > min(e, date(2026, 10, 31)):
                continue
            base = p[11] / max(6, ((e - s).days / 30))  # 月均产值基数
            factor = R.uniform(0.6, 1.4)
            amt = round(base * factor, 2)
            rev.append(("SY%d" % (len(rev) + 1), code, m, amt,
                        R.choices(["设计收入", "工程收入", "总包收入"], weights=[4, 4, 2])[0],
                        round(amt * R.uniform(0.62, 0.88), 2)))
            cost.append(("CB%d" % (len(cost) + 1), code, m,
                         R.choice(["人工", "分包", "采购", "其他"]), round(amt * R.uniform(0.25, 0.5), 2)))
            if R.random() < 0.55:
                col.append(("HK%d" % (len(col) + 1), code, m, round(amt * R.uniform(0.5, 1.15), 2),
                            R.choice(["工程款", "设计费", "预收款", "质保金"])))
            plan = round(base * R.uniform(0.9, 1.2), 2)
            out_amt = round(amt * R.uniform(0.92, 1.28), 2)
            prog.append(("CZ%d" % (len(prog) + 1), code, m, out_amt, plan,
                         min(100, max(0, int((mstart - s).days / max(1, (e - s).days) * 100)))))
            age = R.choices(["1年以内", "1-2年", "2-3年", "3年以上"], weights=[7, 2, 1, 1])[0]
            ar.append(("YS%d" % (len(ar) + 1), code, m, round(amt * R.uniform(0.4, 2.6), 2), age))
            for _ in range(R.randint(0, 3)):
                hours.append(("GS%d" % (len(hours) + 1), code, R.choice(engineers), m, R.randint(20, 160)))

    c.executemany("INSERT INTO FACT_REVENUE VALUES (?,?,?,?,?,?)", rev)
    c.executemany("INSERT INTO FACT_COST VALUES (?,?,?,?,?)", cost)
    c.executemany("INSERT INTO FACT_COLLECTION VALUES (?,?,?,?,?)", col)
    c.executemany("INSERT INTO FACT_PROGRESS VALUES (?,?,?,?,?,?)", prog)
    c.executemany("INSERT INTO FACT_AR VALUES (?,?,?,?,?)", ar)
    c.executemany("INSERT INTO FACT_STAFF_HOURS VALUES (?,?,?,?,?)", hours)

    # ---------------- 风险 / 危大工程 / 保函 ----------------
    risk, hazard, gua = [], [], []
    for p in projects:
        code = p[0]
        for _ in range(R.randint(0, 3)):
            fd = date(2025, 1, 1) + timedelta(days=R.randint(0, 660))
            closed = R.random() < 0.6
            risk.append(("FX%04d" % (len(risk) + 1), code,
                         R.choices(["高风险", "中风险", "低风险"], weights=[1, 4, 5])[0],
                         R.choice(["进度风险", "质量风险", "资金风险", "合规风险", "安全风险"]),
                         _s(fd), _s(fd + timedelta(days=R.randint(20, 200))) if closed else None,
                         "已关闭" if closed else "跟踪中"))
        for _ in range(R.randint(0, 4)):
            fd = date(2025, 1, 1) + timedelta(days=R.randint(0, 660))
            htype = R.choices(["危大工程", "隐患"], weights=[4, 6])[0]
            fixed = R.random() < 0.82
            hazard.append(("YA%04d" % (len(hazard) + 1), code, htype,
                           R.choices(["一级", "二级", "三级"], weights=[1, 3, 6])[0],
                           _s(fd), _s(fd + timedelta(days=R.randint(3, 60))) if fixed else None,
                           "已整改" if fixed else "未整改"))
        if R.random() < 0.3:
            sd = p[7]
            gua.append(("BH%04d" % (len(gua) + 1), code, R.choice(["投标保函", "履约保函", "预付款保函"]),
                        round(p[11] * R.uniform(0.02, 0.1), 2), sd, _s(_d(sd) + timedelta(days=365)),
                        R.choice(["有效", "已释放"])))

    c.executemany("INSERT INTO FACT_RISK VALUES (?,?,?,?,?,?,?)", risk)
    # 重点项目多方案备案，制造有区分度的排名
    for p in R.sample(projects, 30):
        for _ in range(R.randint(5, 11)):
            fd = date(2026, 9, 1) + timedelta(days=R.randint(0, 55))
            hazard.append(("YA%04d" % (len(hazard) + 1), p[0], "危大工程",
                           R.choices(["一级", "二级", "三级"], weights=[1, 4, 5])[0],
                           _s(fd), _s(fd + timedelta(days=R.randint(5, 60))) if R.random() < 0.7 else None,
                           "已整改" if R.random() < 0.7 else "未整改"))

    # 近三个月危大工程/隐患补充，保证双周口径有数据
    for _ in range(120):
        p = R.choice(projects)
        fd = date(2026, 8, 1) + timedelta(days=R.randint(0, 85))
        htype = R.choices(["危大工程", "隐患"], weights=[3, 7])[0]
        fixed = R.random() < 0.75
        hazard.append(("YA%04d" % (len(hazard) + 1), p[0], htype,
                       R.choices(["一级", "二级", "三级"], weights=[1, 3, 6])[0],
                       _s(fd), _s(fd + timedelta(days=R.randint(2, 40))) if fixed else None,
                       "已整改" if fixed else "未整改"))
    # 去年同期镜像一批，避免"本期危大工程同比 +1500%"这种由造数造成的失真
    for p in R.sample(projects, 30):
        for _ in range(R.randint(4, 10)):
            fd = date(2025, 9, 1) + timedelta(days=R.randint(0, 55))
            hazard.append(("YA%04d" % (len(hazard) + 1), p[0], "危大工程",
                           R.choices(["一级", "二级", "三级"], weights=[1, 4, 5])[0],
                           _s(fd), _s(fd + timedelta(days=R.randint(5, 60))) if R.random() < 0.72 else None,
                           "已整改" if R.random() < 0.72 else "未整改"))
    for _ in range(110):
        p = R.choice(projects)
        fd = date(2025, 8, 1) + timedelta(days=R.randint(0, 85))
        htype = R.choices(["危大工程", "隐患"], weights=[3, 7])[0]
        fixed = R.random() < 0.78
        hazard.append(("YA%04d" % (len(hazard) + 1), p[0], htype,
                       R.choices(["一级", "二级", "三级"], weights=[1, 3, 6])[0],
                       _s(fd), _s(fd + timedelta(days=R.randint(2, 40))) if fixed else None,
                       "已整改" if fixed else "未整改"))
    c.executemany("INSERT INTO FACT_HAZARD VALUES (?,?,?,?,?,?,?)", hazard)
    c.executemany("INSERT INTO FACT_GUARANTEE VALUES (?,?,?,?,?,?,?)", gua)

    # ---------------- 字典表 ----------------
    c.executemany("INSERT INTO DIM_CALIBER VALUES (?,?,?,?)", CALIBERS)
    c.executemany("INSERT INTO DIM_KPI VALUES (?,?,?,?,?,?,?)", KPIS)
    c.executemany("INSERT INTO DIM_CONTRACT_TYPE VALUES (?,?,?)", [
        ("CT01", "EPC总承包合同", 1), ("CT02", "勘察设计合同", 1),
        ("CT03", "补充协议/变更", 1), ("CT04", "分包合同", 0), ("CT05", "采购合同", 0)])
    dates = []
    for m in _month_list("2022-01", "2026-12"):
        y, mm = int(m[:4]), int(m[5:7])
        dates.append((m, m.replace("-", ""), y, mm, (mm - 1) // 3 + 1, "月度"))
    c.executemany("INSERT INTO DIM_DATE VALUES (?,?,?,?,?,?)", dates)

    # 历史查询审计（仅当为空时补，制造"系统已在用"的现场感）
    if conn.execute("SELECT COUNT(*) C FROM FACT_QUERY_LOG").fetchone()["C"] == 0:
        demo = [
            ("U001", "各分公司10月新签合同额排名", "data", 6, 9, "全院数据"),
            ("U002", "新能源分公司10月营业收入", "data", 1, 12, "新能源分公司"),
            ("U001", "近6个月营业收入趋势", "data", 6, 18, "全院数据"),
            ("U006", "两金占用按分公司拆分", "data", 6, 10, "全院数据"),
            ("U003", "电网设计部在建项目产值", "data", 1, 14, "电网设计部"),
            ("U001", "哪些项目进度滞后", "data", 10, 22, "全院数据"),
            ("U004", "两金压降有什么要求", "kb", 0, 8, "参与项目（25 个）"),
            ("U001", "新签合同额的口径是什么", "kb", 0, 6, "全院数据"),
            ("U005", "危大工程最多的5个项目", "data", 5, 16, "参与项目（18 个）"),
            ("U001", "风险项目有哪些", "data", 10, 13, "全院数据"),
            ("U002", "营业收入按工程类型看", "data", 8, 11, "新能源分公司"),
            ("U001", "毛利率最高的三个工程类型", "data", 3, 15, "全院数据"),
        ]
        for i, (uid, q, intent, rows, cost, scope) in enumerate(demo):
            conn.execute(
                "INSERT INTO FACT_QUERY_LOG (LOG_ID, USER_ID, QUESTION, INTENT, SQL_TEXT, ROW_CNT, "
                "COST_MS, STATUS, SCOPE_DESC, CREATE_TIME) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("LOG%04d" % i, uid, q, intent, "", rows, cost, "ok", scope,
                 "2026-10-31 %02d:%02d:00" % (9 + (i * 3) % 9, (i * 7) % 60)))
    conn.commit()


DROP_SQL = """
PRAGMA foreign_keys=OFF;
DROP TABLE IF EXISTS DIM_ORG; DROP TABLE IF EXISTS DIM_STAFF; DROP TABLE IF EXISTS DIM_CUSTOMER;
DROP TABLE IF EXISTS DIM_PROJECT; DROP TABLE IF EXISTS DIM_PROJECT_EXT; DROP TABLE IF EXISTS DIM_CONTRACT_TYPE;
DROP TABLE IF EXISTS DIM_KPI; DROP TABLE IF EXISTS DIM_CALIBER; DROP TABLE IF EXISTS DIM_DATE;
DROP TABLE IF EXISTS FACT_CONTRACT; DROP TABLE IF EXISTS FACT_SUBCONTRACT; DROP TABLE IF EXISTS FACT_PROCUREMENT;
DROP TABLE IF EXISTS FACT_REVENUE; DROP TABLE IF EXISTS FACT_COLLECTION; DROP TABLE IF EXISTS FACT_COST;
DROP TABLE IF EXISTS FACT_PROGRESS; DROP TABLE IF EXISTS FACT_RISK; DROP TABLE IF EXISTS FACT_HAZARD;
DROP TABLE IF EXISTS FACT_GUARANTEE; DROP TABLE IF EXISTS FACT_AR; DROP TABLE IF EXISTS FACT_STAFF_HOURS;
DROP TABLE IF EXISTS FACT_KPI_SNAPSHOT; DROP TABLE IF EXISTS FACT_KPI_WIDE;
DROP TABLE IF EXISTS FACT_APPROVAL; DROP TABLE IF EXISTS FACT_REPORT; DROP TABLE IF EXISTS FACT_PUSH_LOG;
DROP TABLE IF EXISTS FACT_QUERY_LOG;
DROP TABLE IF EXISTS BRIDGE_PROJECT_STAFF; DROP TABLE IF EXISTS BRIDGE_PROJECT_TAG;
PRAGMA foreign_keys=ON;
"""

DDL_SQL = """
CREATE TABLE DIM_ORG (
  ORG_ID TEXT PRIMARY KEY, ORG_NAME TEXT NOT NULL, PARENT_ID TEXT,
  ORG_LEVEL INTEGER NOT NULL, ORG_TYPE TEXT NOT NULL, CITY TEXT);

CREATE TABLE DIM_STAFF (
  STAFF_ID TEXT PRIMARY KEY, STAFF_NAME TEXT NOT NULL, ORG_ID TEXT NOT NULL,
  ROLE_JOB TEXT NOT NULL, TITLE TEXT, HIRE_DATE TEXT, STATUS TEXT DEFAULT '在职');

CREATE TABLE DIM_CUSTOMER (
  CUSTOMER_ID TEXT PRIMARY KEY, CUSTOMER_NAME TEXT NOT NULL,
  CUSTOMER_TYPE TEXT, REGION TEXT);

CREATE TABLE DIM_PROJECT (
  PROJ_CODE TEXT PRIMARY KEY, PROJ_NAME TEXT NOT NULL, ORG_ID TEXT NOT NULL,
  PM_STAFF_ID TEXT, CUSTOMER_ID TEXT, PROJ_TYPE TEXT NOT NULL, PROJ_STATUS TEXT NOT NULL,
  START_DATE TEXT NOT NULL, END_DATE TEXT, CITY TEXT, PROVINCE TEXT,
  CONTRACT_AMT REAL NOT NULL);

CREATE TABLE DIM_PROJECT_EXT (
  PROJ_CODE TEXT PRIMARY KEY, ENG_TYPE TEXT, CAPACITY_MW REAL, VOLTAGE_KV REAL, IS_EPC INTEGER);

CREATE TABLE DIM_CONTRACT_TYPE (
  CTYPE_ID TEXT PRIMARY KEY, CTYPE_NAME TEXT NOT NULL, IS_REVENUE INTEGER);

CREATE TABLE DIM_KPI (
  KPI_ID TEXT PRIMARY KEY, KPI_NAME TEXT NOT NULL, CATEGORY TEXT NOT NULL,
  UNIT TEXT NOT NULL, DEFINITION TEXT, CALIBER_ID TEXT, OWNER_DEPT TEXT);

CREATE TABLE DIM_CALIBER (
  CALIBER_ID TEXT PRIMARY KEY, CALIBER_NAME TEXT NOT NULL,
  DEFINITION TEXT, BI_ALIGNED INTEGER);

CREATE TABLE DIM_DATE (
  DATE_KEY TEXT PRIMARY KEY, YYYYMM TEXT, YYYY INTEGER, MM INTEGER,
  QUARTER INTEGER, PERIOD_TYPE TEXT);

CREATE TABLE FACT_CONTRACT (
  CONTRACT_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, CTYPE_ID TEXT NOT NULL,
  AMT REAL NOT NULL, SIGN_DATE TEXT NOT NULL, CHANGE_FLAG INTEGER DEFAULT 0,
  OWNER_ORG_ID TEXT, IS_CHARGE INTEGER DEFAULT 0, IS_SIGNIN INTEGER DEFAULT 0);

CREATE TABLE FACT_SUBCONTRACT (
  SUB_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, VENDOR_NAME TEXT,
  AMT REAL NOT NULL, SIGN_DATE TEXT, SCOPE TEXT);

CREATE TABLE FACT_PROCUREMENT (
  PO_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, VENDOR_NAME TEXT,
  AMT REAL NOT NULL, ORDER_DATE TEXT, CATEGORY TEXT);

CREATE TABLE FACT_REVENUE (
  REV_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, PERIOD TEXT NOT NULL,
  AMT REAL NOT NULL, REV_TYPE TEXT, COST_AMT REAL);

CREATE TABLE FACT_COLLECTION (
  COL_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, PERIOD TEXT NOT NULL,
  AMT REAL NOT NULL, COL_TYPE TEXT);

CREATE TABLE FACT_COST (
  COST_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, PERIOD TEXT NOT NULL,
  COST_TYPE TEXT, AMT REAL NOT NULL);

CREATE TABLE FACT_PROGRESS (
  PROG_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, PERIOD TEXT NOT NULL,
  OUTPUT_AMT REAL, PLAN_OUTPUT_AMT REAL, IMAGE_PROGRESS REAL);

CREATE TABLE FACT_RISK (
  RISK_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, RISK_LEVEL TEXT, RISK_TYPE TEXT,
  FOUND_DATE TEXT, CLOSE_DATE TEXT, STATUS TEXT);

CREATE TABLE FACT_HAZARD (
  HAZARD_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, HAZARD_TYPE TEXT, LEVEL TEXT,
  FOUND_DATE TEXT, FIX_DATE TEXT, STATUS TEXT);

CREATE TABLE FACT_GUARANTEE (
  GUA_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, GUA_TYPE TEXT, AMT REAL,
  START_DATE TEXT, END_DATE TEXT, STATUS TEXT);

CREATE TABLE FACT_AR (
  AR_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, PERIOD TEXT NOT NULL,
  BAL_AMT REAL NOT NULL, AGE_BUCKET TEXT);

CREATE TABLE FACT_STAFF_HOURS (
  HOUR_ID TEXT PRIMARY KEY, PROJ_CODE TEXT NOT NULL, STAFF_ID TEXT NOT NULL,
  PERIOD TEXT NOT NULL, HOURS REAL);

CREATE TABLE FACT_KPI_SNAPSHOT (
  PERIOD TEXT NOT NULL, ORG_ID TEXT NOT NULL, PROJ_TYPE TEXT,
  KPI_ID TEXT NOT NULL, VALUE REAL, UNIT TEXT,
  PRIMARY KEY (PERIOD, ORG_ID, PROJ_TYPE, KPI_ID));

CREATE TABLE FACT_KPI_WIDE (
  PERIOD TEXT NOT NULL, ORG_ID TEXT NOT NULL, ORG_NAME TEXT, PROJ_TYPE TEXT,
  PRIMARY KEY (PERIOD, ORG_ID, PROJ_TYPE));

CREATE TABLE FACT_REPORT (
  REPORT_ID TEXT PRIMARY KEY, PERIOD_START TEXT NOT NULL, PERIOD_END TEXT NOT NULL,
  TITLE TEXT, STATUS TEXT, BUILDER TEXT, CONTENT_MD TEXT, VALIDATE_JSON TEXT,
  CREATE_TIME TEXT, SCOPE_DESC TEXT DEFAULT '全院数据');

CREATE TABLE FACT_APPROVAL (
  APPROVAL_ID TEXT PRIMARY KEY, REPORT_ID TEXT NOT NULL, STEP TEXT,
  APPROVER TEXT, ACTION TEXT, COMMENT TEXT, OP_TIME TEXT);

CREATE TABLE FACT_PUSH_LOG (
  PUSH_ID TEXT PRIMARY KEY, REPORT_ID TEXT NOT NULL, CHANNEL TEXT,
  RECEIPT_NO TEXT, PUSH_TIME TEXT, STATUS TEXT);

CREATE TABLE FACT_QUERY_LOG (
  LOG_ID TEXT PRIMARY KEY, USER_ID TEXT, QUESTION TEXT, INTENT TEXT,
  SQL_TEXT TEXT, ROW_CNT INTEGER, COST_MS INTEGER, STATUS TEXT, SCOPE_DESC TEXT, CREATE_TIME TEXT);

CREATE TABLE BRIDGE_PROJECT_STAFF (
  PROJ_CODE TEXT NOT NULL, STAFF_ID TEXT NOT NULL, ROLE_IN_PROJ TEXT,
  PRIMARY KEY (PROJ_CODE, STAFF_ID));

CREATE TABLE BRIDGE_PROJECT_TAG (
  PROJ_CODE TEXT NOT NULL, TAG TEXT NOT NULL, PRIMARY KEY (PROJ_CODE, TAG));

CREATE INDEX IDX_CONTRACT_DATE ON FACT_CONTRACT(SIGN_DATE);
CREATE INDEX IDX_REV_PERIOD ON FACT_REVENUE(PERIOD);
CREATE INDEX IDX_REV_PROJ ON FACT_REVENUE(PROJ_CODE);
CREATE INDEX IDX_PROJ_ORG ON DIM_PROJECT(ORG_ID);
CREATE INDEX IDX_PROJ_STATUS ON DIM_PROJECT(PROJ_STATUS);
CREATE INDEX IDX_AR_PERIOD ON FACT_AR(PERIOD);
CREATE INDEX IDX_PROGRESS_PERIOD ON FACT_PROGRESS(PERIOD);
CREATE INDEX IDX_HAZARD_DATE ON FACT_HAZARD(FOUND_DATE);
CREATE INDEX IDX_RISK_DATE ON FACT_RISK(FOUND_DATE);
"""


def main() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    build(conn)
    cur = conn.execute("SELECT COUNT(*) C FROM DIM_PROJECT")
    n = cur.fetchone()["C"]
    tables = conn.execute("SELECT COUNT(*) C FROM sqlite_master WHERE type='table'").fetchone()["C"]
    print("[seed] 表数量=%d 项目数=%d 数据库=%s" % (tables, n, DB_PATH))
    conn.close()


if __name__ == "__main__":
    main()
