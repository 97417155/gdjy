# -*- coding: utf-8 -*-
"""提示词范式库：行业 NL2SQL 提示范式 + 报告撰写范式 + Few-shot 样例。

现场数据库是 Oracle 11g，且业务口径复杂，所以提示词不是简单的"你是SQL专家"，
而是四段式：角色与边界 / 库与环境约束 / 口径与词表 / 样例与输出格式。
"""
from __future__ import annotations

from typing import List

from app import metrics as M

ORACLE_11G_RULES = """【数据库环境约束（Oracle 11g，必须严格遵守）】
1. 只能使用 Oracle 11g 支持的语法，禁止使用 12c 及以上特性：禁止 FETCH FIRST、OFFSET ... ROWS、LIMIT。
2. 分页/取前N条必须写成：SELECT * FROM ( 子查询 ) WHERE ROWNUM <= N。
3. 空值函数用 NVL(col, 0)，禁止 IFNULL / ISNULL / COALESCE 之外的 MySQL 写法。
4. 日期格式化用 TO_CHAR(col,'YYYY-MM')，日期常量用 TO_DATE('2026-10-01','YYYY-MM-DD')，当前时间用 SYSDATE。
5. 禁止使用 DATE_FORMAT / STRFTIME / NOW() / CURDATE() / ILIKE / EXCEPT / 反引号。
6. 集合差用 MINUS；字符串拼接用 ||；标识符用大写字母与下划线，不加引号。
7. GROUP BY 中必须写完整表达式，不能引用 SELECT 别名。
8. 聚合函数与外连接混用时，注意 LEFT JOIN 后 COUNT(*) 的语义漂移。
"""

BUSINESS_RULES = """【统计口径（与 BI 平台对齐，口径不一致的查询一律作废）】
1. 金额单位统一为万元，百分比保留两位小数，不要自行换算成元或亿元。
2. 新签合同额：按合同签订日期归集，取收入类合同（CT01/CT02/CT03），排除分包与采购合同；
   统计新签时需排除变更合同（CHANGE_FLAG=1），变更金额单独作为一个指标。
3. 营业收入：按月度确认收入归集，PERIOD 字段为 'YYYY-MM' 文本，区间过滤用 PERIOD BETWEEN 'a' AND 'b'。
4. 回款率 = 回款额 / 同期营业收入 × 100；毛利率 = (营业收入 - 营业成本) / 营业收入 × 100。
5. 应收账款与两金为期末时点余额，取期间最后一个月（PERIOD = 期末月）。
6. 在建项目口径：DIM_PROJECT.PROJ_STATUS = '在建'，不含前期与暂停。
7. 分公司维度按 SUBSTR(P.ORG_ID,1,4) 归集（部门编码前4位为分公司编码）。
8. 所有查询默认排除逻辑删除数据（本库目前无软删除字段，如遇 IS_DELETED 需加 =0）。
"""

def metric_table_text() -> str:
    lines = ["【指标口径字典】"]
    for k, v in M.METRICS.items():
        lines.append("- %s（%s，%s）：%s" % (k, v["name"], v["unit"], v.get("desc", "")))
    return "\n".join(lines)


FEW_SHOT: List[dict] = [
    {
        "q": "2026年10月全院新签合同额是多少",
        "sql": """SELECT NVL(SUM(C.AMT),0) AS VAL
FROM FACT_CONTRACT C
JOIN DIM_PROJECT P ON P.PROJ_CODE = C.PROJ_CODE
WHERE C.SIGN_DATE BETWEEN TO_DATE('2026-10-01','YYYY-MM-DD') AND TO_DATE('2026-10-31','YYYY-MM-DD')
  AND NVL(C.CHANGE_FLAG,0) = 0""",
    },
    {
        "q": "各分公司10月新签合同额排名",
        "sql": """SELECT O.ORG_NAME AS 分公司, NVL(SUM(C.AMT),0) AS 新签合同额_万元
FROM FACT_CONTRACT C
JOIN DIM_PROJECT P ON P.PROJ_CODE = C.PROJ_CODE
JOIN DIM_ORG O ON O.ORG_ID = SUBSTR(P.ORG_ID,1,4)
WHERE C.SIGN_DATE BETWEEN TO_DATE('2026-10-01','YYYY-MM-DD') AND TO_DATE('2026-10-31','YYYY-MM-DD')
  AND NVL(C.CHANGE_FLAG,0) = 0
GROUP BY O.ORG_NAME
ORDER BY 新签合同额_万元 DESC""",
    },
    {
        "q": "2026年9月营业收入和毛利率",
        "sql": """SELECT ROUND(NVL(SUM(V.AMT),0),2) AS 营业收入_万元,
       ROUND(100*(NVL(SUM(V.AMT),0)-NVL(SUM(K.AMT),0))/NULLIF(SUM(V.AMT),0),2) AS 毛利率_百分比
FROM (SELECT PROJ_CODE, PERIOD, SUM(AMT) AS AMT FROM FACT_REVENUE
      WHERE PERIOD BETWEEN '2026-09' AND '2026-09' GROUP BY PROJ_CODE, PERIOD) V
LEFT JOIN (SELECT PROJ_CODE, PERIOD, SUM(AMT) AS AMT FROM FACT_COST
           GROUP BY PROJ_CODE, PERIOD) K
  ON K.PROJ_CODE = V.PROJ_CODE AND K.PERIOD = V.PERIOD
JOIN DIM_PROJECT P ON P.PROJ_CODE = V.PROJ_CODE""",
    },
    {
        "q": "危大工程数量最多的5个项目",
        "sql": """SELECT * FROM (
  SELECT P.PROJ_NAME AS 项目名称, COUNT(*) AS 危大工程数_个
  FROM FACT_HAZARD Z
  JOIN DIM_PROJECT P ON P.PROJ_CODE = Z.PROJ_CODE
  WHERE Z.HAZARD_TYPE = '危大工程'
    AND Z.FOUND_DATE BETWEEN TO_DATE('2026-10-01','YYYY-MM-DD') AND TO_DATE('2026-10-31','YYYY-MM-DD')
  GROUP BY P.PROJ_NAME
  ORDER BY 危大工程数_个 DESC
) WHERE ROWNUM <= 5""",
    },
    {
        "q": "2026年5月到10月营业收入逐月趋势",
        "sql": """SELECT V.PERIOD AS 月份, ROUND(SUM(V.AMT),2) AS 营业收入_万元
FROM FACT_REVENUE V
WHERE V.PERIOD BETWEEN '2026-05' AND '2026-10'
GROUP BY V.PERIOD
ORDER BY V.PERIOD""",
    },
    {
        "q": "省外A类在建项目的产值合计",
        "sql": """SELECT NVL(SUM(G.OUTPUT_AMT),0) AS 产值_万元
FROM FACT_PROGRESS G
JOIN DIM_PROJECT P ON P.PROJ_CODE = G.PROJ_CODE
WHERE G.PERIOD BETWEEN '2026-10' AND '2026-10'
  AND P.PROVINCE <> '广东'
  AND P.PROJ_TYPE = 'A'
  AND P.PROJ_STATUS = '在建'""",
    },
]


def nl2sql_prompt(question: str, schema: str, user_ctx: str = "") -> str:
    fs = "\n\n".join(["问：%s\n答：%s" % (f["q"], f["sql"]) for f in FEW_SHOT])
    return f"""你是广东院经营数据助手"小海"，负责把业务人员的自然语言问题翻译为一条可执行的 Oracle 11g SQL。

{ORACLE_11G_RULES}

{BUSINESS_RULES}

{schema}

【Few-shot 样例（严格模仿其写法与别名风格）】
{fs}

【输出要求】
1. 只输出一条 SQL 代码块，不要解释、不要输出多条语句、不要以分号结尾。
2. 列别名使用中文并带单位，如 新签合同额_万元。
3. 查询必须只读，禁止任何写操作与 DDL。
4. 若问题超出数据范围（例如问人事、财务明细凭证），输出：UNSUPPORTED。
5. 当前用户数据范围：{user_ctx}。若问题要求的数据超出该范围，请在 SQL 中同样按项目范围过滤。

用户问题：{question}
"""


REPORT_SYSTEM = """你是广东院经营分析报告撰写助手。你的输出必须是规范的 Markdown 正文，
面向院领导班子，语言简洁、结论先行、数据支撑，不使用夸张措辞。

写作要求：
1. 每一段提到的数字，必须来自给定的指标表，禁止推测、换算或编造。
2. 数字保留两位小数，金额单位统一为万元，百分比保留一位小数。
3. 结构固定为七章，每章包含：结论句 + 数据支撑 + 简要分析。
4. 不出现"我认为""可能""大概"等模糊表述；无法判断时说明"数据不足，需业务部门核实"。
5. 不使用 markdown 表格以外的排版元素；不写代码块。
"""


def report_prompt(period_label: str, kpi_rows: str, exceptions: str) -> str:
    return f"""【本期报告期间】{period_label}

【指标数据（已按 BI 口径计算，直接引用）】
{kpi_rows}

【系统自动识别的异常（必须撰写提示，不得掩盖）】
{exceptions or "无"}

请按以下七章撰写《{period_label}经营分析报告》正文：
一、经营总览；二、合同签约；三、收入与利润；四、回款与两金；五、项目履约与产值；六、安全与风险；七、结论与建议。
每章 150-250 字，结论先行。
"""


def router_prompt(question: str) -> str:
    return f"""判断用户问题属于哪一类：
A = 项目档案检索（问某个项目的基本情况、工期、投资、业主）
B = 自然语言取数（问指标数值、排名、趋势、占比）
C = 知识库问答（问制度、办法、口径、流程）
D = 闲聊或超出范围

只输出一个字母。问题：{question}
"""
