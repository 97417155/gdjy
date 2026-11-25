# 架构说明

## 一、分层

```
┌──────────────────────────────────────────────────────────┐
│ 浏览器：Vue 3 + TypeScript + ECharts                       │
│ views: Dashboard / Chat / Report / Data / Audit          │
└───────────────┬──────────────────────────────────────────┘
                │ HTTP（JSON） / SSE（进度与逐字输出）
┌───────────────▼──────────────────────────────────────────┐
│ HTTP 适配层（二选一，代码只做协议转换）                        │
│  • server/fastapi_app.py  FastAPI + uvicorn（含 /docs）    │
│  • app/api.py             标准库 http.server（零依赖回退）    │
└───────────────┬──────────────────────────────────────────┘
                │ 纯 Python 函数调用
┌───────────────▼──────────────────────────────────────────┐
│ 业务层 app/service.py（与框架无关）                          │
│  问答 router · 指标 metrics · 权限 permission · 报告 report │
└───────────────┬──────────────────────────────────────────┘
                │ 
┌───────────────▼──────────────────────────────────────────┐
│ 数据层：指标元数据 / SQLite（演示）或 Oracle 11g（生产） / 知识库 │
└──────────────────────────────────────────────────────────┘
```

**为什么这么分**：一开始就要求"本地必须能跑，生产是 Oracle 11g"。
把业务与 HTTP 解耦后，两个目标各自独立实现——框架可以换（重写一层路由约 60 行），
数据库可以换（替换执行器），而指标口径、权限规则、报告体例这些真正花时间的部分只写一遍。

## 二、一次问答的调用链

```
用户提问
 └─ detect_intent()                 规则 + 词表判意图：data / archive / kb / clarify / chat
     └─ plan_*()                    生成"执行计划"：指标、维度、期间、过滤、排序、Limit
         ├─ metric_sql()            指标元数据 → SQL 片段（Oracle 11g 写法）
         ├─ oracle_compat.lint()    静态检查禁用方言（LIMIT / IFNULL / DATE_FORMAT ...）
         └─ permission.inject_row_scope()
                                    把岗位范围翻译成 SQL 谓词，注入到"顶层 WHERE"
             └─ repair.run_with_repair()
                 ├─ to_sqlite()     本地执行转译（生产直接送 Oracle）
                 ├─ 失败 → 定向改写（表名/列名大小写、聚合语义、语法函数）→ 重试 ≤3 轮
                 └─ 仍失败 → degrade() 降级查指标宽表，回答标注"已降级"
                     └─ _format_plan()  生成 markdown 回答 + 表格 + 图表规格 + 追问建议
                         └─ 写审计日志 FACT_QUERY_LOG
```

要点：

- **行级权限不是事后过滤**，而是在生成 SQL 时就把范围写成 `AND` 条件（`inject_row_scope`）。
  用括号深度扫描定位顶层 `WHERE`，避免谓词插进子查询把 SQL 弄坏。
- **无法校验范围的查询直接拒绝**：若 SQL 里没有项目维度，无法判断是否越权，抛 `PermissionError`。
- **降级是显式的**：`degraded: true` 会传到前端并显示标签，绝不用估算值冒充查询结果。

## 三、一次报告生成的调用链

```
POST /api/report/stream（SSE）
 └─ builder.build(hooks=...)
     ├─ ① metrics    构建宽表 + 抽取 28 指标 × 3 期（本期 / 上期 / 上年同期）
     ├─ ② compare    算同比环比，标记 |同比| ≥ 30% 的异常波动
     ├─ ③ compose    sections.build_sections() 逐章生成「结论句 + 数据表 + 分析 + 措施」
     ├─ ④ guard      validator.validate() 跑 10 条规则，得分写进轨迹
     └─ ⑤ save       落库（正文 + 指标快照 + 派生数字白名单 + 生成轨迹）
```

每个步骤回调 `hooks("stage", {name, title, text, status, ms})`，
HTTP 层把回调转成 SSE 事件，前端按 `name` 就地更新（running → ok）。
生成的报告带 `TRACE_JSON`，事后打开仍能看到"当时每一步花了多久"。

**校验为什么能防幻觉**：正文里出现的金额类数字必须能在
「指标值 / 同比 / 环比 / 派生占比 / 表格内登记值」集合中找到（容差 0.6%），
否则报 `N2 数值可追溯` 失败并阻断审批。表格内数字由生成器逐格登记，
所以分公司 / 项目维度的明细不会被误判，而模型编造的数字一定会被抓到。

## 四、权限模型

| 岗位 | scope_type | 行级谓词 | 利润类指标 |
|---|---|---|---|
| 院长 / 副院长 / 财务专员 | `ALL` | 无限制 | 可见 |
| 分公司负责人 | `ORG` | `SUBSTR(P.ORG_ID,1,4) = 本单位` | 可见 |
| 部门负责人 | `DEPT` | `P.ORG_ID = 本部门` | 可见 |
| 项目经理 / 设计工程师 | `PROJ` | `P.PROJ_CODE IN (参与项目)` | 脱敏 |

- 行级：`permission.scope_filters(user)` 同时供问答、看板、报告三条链路复用，口径一致。
- 列级：`mask_rows` 与前端表格脱敏；非财务岗生成的报告直接剔除利润章节，且不进入校验口径。
- 报告落库时记录 `SCOPE_DESC`，`?report=latest` 只打开与当前范围一致的历史报告，避免串号。

## 五、Oracle 11g 兼容层

`app/oracle_compat.py` 三层：

| 层 | 作用 |
|---|---|
| `lint()` | 静态检查 15 条 MySQL / 新版本方言违规（`LIMIT`、`IFNULL`、`DATE_FORMAT`、`ILIKE`…） |
| `rewrite()` | 自动改写为 11g 写法（`LIMIT n` → `ROWNUM <= n`，`IFNULL` → `NVL`…） |
| `to_sqlite()` | 本地执行转译（`TO_DATE`、`TO_CHAR`、`DAYS_BETWEEN` 等），**仅用于演示库** |

界面展示与审计日志里保留的始终是 Oracle 写法——这是"给业务看的 SQL"，不是本地执行用的。

## 六、上生产需要替换的部分

| 位置 | 现状 | 生产做法 |
|---|---|---|
| `app/db.py` | SQLite 连接 | 换成 `cx_Oracle` / `oracledb` 连接池，`to_sqlite()` 直通 |
| `app/permission.py` | 演示账号表 | 对接院内权限中心（SSO / 组织架构接口） |
| `app/nl2sql/llm.py` | 无模型时走规则引擎 | 配置 OpenAI 兼容接口（`GDJY_LLM_KEY`），失败自动回退规则引擎 |
| `app/report/builder.py` | 内置文案引擎 | 同一套提示词交给模型撰写，仍需过 10 条校验 |
| `app/report/workflow.py` | 模拟审批 | 对接 OA / 集团经营平台接口，保留回执号落库 |
| `app/kb.py` | 字符二元组 BM25 | 换向量库（如 pgvector / Milvus）+ rerank |
| `web/` | 静态构建产物 | Nginx 托管或 CDN，后端只留 API |

## 七、数据模型概要

| 分组 | 表 |
|---|---|
| 维度（9） | DIM_ORG、DIM_STAFF、DIM_CUSTOMER、DIM_PROJECT、DIM_PROJECT_EXT、DIM_CONTRACT_TYPE、DIM_KPI、DIM_CALIBER、DIM_DATE |
| 合同与收入（6） | FACT_CONTRACT、FACT_SUBCONTRACT、FACT_PROCUREMENT、FACT_REVENUE、FACT_COLLECTION、FACT_COST |
| 履约与风险（6） | FACT_PROGRESS、FACT_RISK、FACT_HAZARD、FACT_GUARANTEE、FACT_AR、FACT_STAFF_HOURS |
| 指标（2） | FACT_KPI_SNAPSHOT（长表，按期间留档）、FACT_KPI_WIDE（宽表，一行 = 期间 × 分公司 × 项目等级） |
| 流程（4） | FACT_REPORT、FACT_APPROVAL、FACT_PUSH_LOG、FACT_QUERY_LOG |
| 关联（2） | BRIDGE_PROJECT_STAFF、BRIDGE_PROJECT_TAG |

几条建模上的取舍：

- **指标双写**：长表 `FACT_KPI_SNAPSHOT` 保证历史可追溯（口径调整不篡改旧数字），
  宽表 `FACT_KPI_WIDE` 支撑"一列一指标"的快速取数与报告取数，宽表列随指标注册表自动扩展。
- **合同与产值分开**：`FACT_CONTRACT` 记签约，`FACT_PROGRESS` 记月度产值与形象进度，
  避免"签约额当收入用"这类口径混淆；收入按完工百分比由 `FACT_REVENUE` 承载。
- **两金拆开存**：`FACT_AR`（应收账龄明细）+ 已完工未结算，才能算长账龄占比，而不是只存一个余额数。
- **口径字典独立成表**：`DIM_KPI` 与 `DIM_CALIBER` 分离，指标可复用同一口径编号，也便于与 BI 平台对齐核对。
- **审计表必须落库**：`FACT_QUERY_LOG` 记录问题、SQL、行数、耗时、数据范围，权限争议时可回溯。

数据规模：300 个项目、500+ 合同、约 2 万条事实，覆盖 2025-01 ~ 2026-10，支持同比（上年同期）与环比。
