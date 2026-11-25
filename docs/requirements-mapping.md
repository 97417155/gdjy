# 需求对照与实现细节

本文件把最初的项目需求逐条映射到代码位置，并保留指标口径、数据模型与上生产替换清单，
适合做代码走查或答辩时逐项对照。阅读顺序建议先看 [README](../README.md) 与
[架构说明](architecture.md)。

> 面向能源设计院的**经营分析报告自动生成 + 项目画像智能问答**一体化系统。

**技术栈**：Vue 3 + TypeScript + Vite + Vue Router + ECharts（前端） ｜ Python（FastAPI/uvicorn，缺失时自动回退标准库） ｜ SQLite 演示库（生产为 Oracle 11g）

```
python run.py           # 一条命令启动，浏览器打开 http://127.0.0.1:8848
```

---

## 一、需求对照

| 需求点 | 实现位置 | 说明 |
|---|---|---|
| 7 大类经营指标、动态 SQL 批量抽取 | `app/metrics.py` | 28 个指标登记为元数据（表达式 + 取数表 + 期间条件），新增指标不改代码 |
| 对齐 BI 统计口径、结构化指标宽表 | `app/metrics.py::build_wide` | 一列一指标动态扩列，一行 = 期间 × 分公司 × 项目等级；同时落长表快照供趋势查询 |
| 报告范式提示词库、模型撰写正文 | `app/nl2sql/prompts.py` | 七章结构 + 口径约束 + 禁止编造数字；无模型时走内置文案引擎 |
| Python 兜底校验（正则 + 规则） | `app/report/validator.py` | 10 条规则：结构、单位、数字格式、指标一致性、数值幻觉、异常波动、安全红线 |
| 打通院内审批推送链路 | `app/report/workflow.py` | 草稿 → 已校验 → 待审批 → 已通过 → 已推送，全程写审批与推送日志 |
| 多分支意图路由（档案 / 取数 / 知识） | `app/nl2sql/router.py::detect_intent` | 规则判意图，支持多轮追问与指标下钻 |
| Oracle 11g 语法限制定制 | `app/oracle_compat.py` | 三层：lint 静态检查 → rewrite 自动改写 → to_sqlite 转译执行 |
| 行业 NL2SQL 提示范式 + Few-shot + 同义词口径库 | `prompts.py` / `lexicon.py` / `app/kb.py` | 6 条 Few-shot 覆盖指标、排名、趋势、TopN、跨表；同义词 100+ 条 |
| 20+ 表跨表关联查询 | `app/seed.py` | 29 张表（9 维表 + 18 事实表 + 2 关联表），指标 SQL 最多跨 6 表 |
| SQL 语法捕获、改写、重试、失败降级 | `app/nl2sql/repair.py` | 3 次重试 + 四类定向修正；仍失败则降级到指标宽表 |
| 行级 / 岗位权限隔离 | `app/permission.py` | 行级靠 SQL 谓词注入（括号深度感知），列级靠利润指标脱敏 |
| 多轮反问、指标下钻、BI 图表联动 | `router.py` + `frontend/src/views/ChatView.vue` | 会话上下文继承指标与期间；回答自带图表规格，前端 ECharts 渲染 |

---

## 二、快速开始

### 2.1 生产模式（单进程，前端已构建）

```bash
cd gdjy
python run.py                # 首次自动建库、造数、构建指标宽表
# 浏览器打开 http://127.0.0.1:8848
```

启动器会自动选择 HTTP 框架：装了 FastAPI 就走 FastAPI（多出 `/docs` 交互文档），
没装则回退到零依赖的标准库实现，功能完全一致。

```bash
python run.py --server fastapi   # 强制 FastAPI（uvicorn）
python run.py --server stdlib    # 强制标准库
```

FastAPI/uvicorn 装在仓库内的 `_pydeps/`（`pip install --target ./_pydeps fastapi uvicorn`），
`run.py` 会自动加入 `sys.path`，不污染全局环境；删除该目录即回到零依赖模式。

`web/` 下是 Vue 的构建产物，由 Python 服务直接托管，前后端同源，无需额外配置。

### 2.2 开发模式（前后端分离，热更新）

```bash
# 终端 1：启动后端
cd gdjy && python run.py --port 8848

# 终端 2：启动前端
cd gdjy/frontend
npm install          # 国内网络建议加 --registry=https://registry.npmmirror.com
npm run dev          # http://localhost:5173 ，/api 已代理到 8848
```

改完前端代码执行 `npm run build`，产物会输出到 `../web`（已被 Vite 配置为构建目标），后端无需重启。

### 2.3 质量检查

```bash
cd gdjy && python tests/test_smoke.py      # 后端端到端 36 项
cd gdjy/frontend
npm run type-check                         # vue-tsc 全量类型检查
npm test                                   # Vitest 单元测试（51 项）
```

常用参数：

```bash
python run.py --reset        # 重建演示数据
python run.py --port 9000    # 换端口
python run.py --init-only    # 只初始化，不起服务
python tests/test_smoke.py   # 端到端自检（36 项）
```

深链（方便演示与分享）：

```
http://127.0.0.1:8848/#chat                  直接进问答
http://127.0.0.1:8848/?q=各分公司10月新签合同额排名   带问题自动提问
http://127.0.0.1:8848/?report=latest         打开最近一次生成的报告
http://127.0.0.1:8848/#data                  进数据与权限页
```

> 环境要求：Python 3.10+。**不依赖 Flask / pandas / rdflib 等任何第三方库**，离线可用。
> 若设置 `GDJY_LLM_KEY`（OpenAI 兼容接口，如 DeepSeek），系统会自动切换到"大模型生成 SQL + 模型撰写报告"模式；否则用内置规则引擎，功能不缺失。

---

## 三、界面导览

| 页签 | 内容 |
|---|---|
| **经营驾驶舱** | 7 类指标卡片、分公司新签排名、近 6 个月收入趋势、工程类型收入结构、产值缺口 TOP |
| **智能问答** | 三分支问答、SQL 透明展示、图表联动、多轮下钻、降级与修复过程可见 |
| **报告生成** | 一键生成本期报告 → 执行兜底校验（逐条规则）→ 提交审批 → 推送 OA（返回回执号） |
| **数据与权限** | 岗位与可见范围、28 个指标口径字典、29 张表清单 |
| **查询审计** | 每次问答的问题、意图、行数、耗时、数据范围 |

右上角切换身份会实时改变可见数据范围，可现场演示"同一个问题、不同岗位、不同答案"。

---

## 四、系统架构

```
            ┌──────────────── 前端（原生 JS + SVG，无构建）────────────────┐
            │ 驾驶舱    智能问答    报告工作流    数据权限    审计          │
            └───────────────────────────┬──────────────────────────────────┘
                                        │ JSON over HTTP
┌───────────────────────────────────────▼──────────────────────────────────┐
│ 接口层 app/api.py（标准库 http.server）                                     │
├──────────────────────────────────────────────────────────────────────────┤
│ 编排层                                                                     │
│   router   意图路由 / 多轮上下文 / 回答与图表格式化                          │
│   planner  查询计划：指标型 / 趋势型 / 档案型 / 滞后型 / 风险型              │
│   report   报告编排 → 校验 → 审批推送                                       │
├──────────────────────────────────────────────────────────────────────────┤
│ 能力层                                                                     │
│   metrics    28 指标元数据 + 动态 SQL + 指标宽表                            │
│   permission 行业/组织范围 → 行级谓词；岗位 → 列级脱敏                       │
│   kb         BM25 + 字符二元组的制度口径检索                                │
│   repair     执行 → 报错分析 → 定向修正 → 重试 → 降级                        │
│   oracle_compat  Oracle 11g 方言 lint / rewrite / to_sqlite                │
├──────────────────────────────────────────────────────────────────────────┤
│ 数据层 SQLite（生产替换为 Oracle 11g，仅需替换 db.run_query 的执行器）       │
└──────────────────────────────────────────────────────────────────────────┘
```

**为什么用 SQLite 演示 Oracle**：`oracle_compat.to_sqlite()` 是唯一与执行引擎耦合的地方。生产环境把这一层换成 `cx_Oracle` 直连，其余（方言校验、修复回路、权限注入、指标引擎、报告校验）完全复用，这本身就是"方言适配层"的价值所在。

---

## 五、关键设计说明

### 1. Oracle 11g 方言三层适配

现场库是 11g，没有 `FETCH FIRST` / `LIMIT`，日期函数只有 `TO_CHAR/TO_DATE`，空值函数是 `NVL`。大模型默认吐 MySQL 方言，因此做了三层：

- `lint()`：静态检查 15 条规则（LIMIT、IFNULL、DATE_FORMAT、ILIKE、反引号…），用于提示词约束与自动修复；
- `rewrite()`：把 `LIMIT 5` → `SELECT * FROM (...) WHERE ROWNUM <= 5`，`IFNULL` → `NVL`，`DATE_FORMAT` → `TO_CHAR`；
- `to_sqlite()`：把 11g 写法转译为本地可执行形式（`NVL`→`IFNULL`、`TO_DATE`→字面量、`TO_CHAR`→`STRFTIME`、`DAYS_BETWEEN`→`julianday` 差值）。

演示 SQL 全部以 Oracle 11g 写法生成并在界面原样展示，保证"看得见的 SQL 就是能在现场跑的 SQL"。

### 2. 修复回路与失败降级

`repair.run_with_repair()` 最多 3 轮：捕获报错 → 按四类高频错误定向修正（表名大小写、列名大小写、聚合语义、语法/函数）→ 重试。仍失败则 `degrade()` 直接查已构建的指标宽表，回答里明确标注"已降级"，绝不静默返回错数。

### 3. 权限：两层隔离 + 一个拒绝

- **行级**：把岗位范围翻译成 SQL 谓词，注入到顶层 `WHERE`（用括号深度扫描定位，避免插进子查询），即使模型生成了错误 JOIN 也只是查不到数据，不会越权；
- **列级**：利润类指标对非财务岗位返回"***（无权限）"；
- **拒绝**：查询若无项目维度（无法完成范围校验），直接拒绝并提示补充条件——这是比"放开"更安全的默认值。

### 4. 指标元数据驱动

每个指标登记 `表达式 + 取数表 + 期间条件 + 单位 + 口径 ID`，SQL 由 `metric_sql()` 按维度/过滤条件拼装。宽表列名即指标编码，`ensure_wide_columns()` 自动 `ALTER TABLE` 扩列——新增一个指标只需在 `METRICS` 里加一条，宽表、快照、字典、校验全部自动生效。

### 5. 报告兜底校验（防幻觉的核心）

10 条规则中最关键的是两条：

- **N1 指标一致性**：正文中每个指标名后 24 字内的数字必须与宽表值一致（容差 1%），不一致直接 error；
- **N2 数值可追溯**：正文出现的所有金额类数字，必须能在"指标值 / 同比 / 环比 / 派生占比"集合中找到，找不到即判为疑似幻觉。

校验不通过则报告不能进入审批队列——这是"生产稳定"的硬闸门，而不是提示。

### 6. 知识库

制度、办法、口径共 7 篇 Markdown，按 `##` 切块，用字符二元组 + BM25 打分检索，回答附带引用来源。生产环境把 `tokenize` 换成 embedding 即可，上层"检索 → 引用 → 生成"结构不变。

---

## 六、数据模型（29 张表）

| 分组 | 表 |
|---|---|
| 维度（9） | DIM_ORG、DIM_STAFF、DIM_CUSTOMER、DIM_PROJECT、DIM_PROJECT_EXT、DIM_CONTRACT_TYPE、DIM_KPI、DIM_CALIBER、DIM_DATE |
| 合同与收入（6） | FACT_CONTRACT、FACT_SUBCONTRACT、FACT_PROCUREMENT、FACT_REVENUE、FACT_COLLECTION、FACT_COST |
| 履约与风险（6） | FACT_PROGRESS、FACT_RISK、FACT_HAZARD、FACT_GUARANTEE、FACT_AR、FACT_STAFF_HOURS |
| 指标（2） | FACT_KPI_SNAPSHOT（长表）、FACT_KPI_WIDE（宽表） |
| 流程（4） | FACT_REPORT、FACT_APPROVAL、FACT_PUSH_LOG、FACT_QUERY_LOG |
| 关联（2） | BRIDGE_PROJECT_STAFF、BRIDGE_PROJECT_TAG |

数据规模：300 个项目、500+ 合同、约 2 万条事实记录，覆盖 2025-01 至 2026-10，支持同比（取上年同期）与环比。

---

## 七、示例问题

| 问题 | 预期路径 |
|---|---|
| 2026年10月新签合同额是多少 | 取数 · 单值 + 同比环比 |
| 各分公司10月新签合同额排名 | 取数 · 排名 + 柱图 |
| 近6个月营业收入趋势 | 取数 · 趋势 + 折线 |
| 毛利率最高的三个工程类型 | 取数 · TopN + 权限判断 |
| 两金占用按分公司拆分 | 取数 · 分组 |
| 广东省内A类在建项目的产值 | 取数 · 多条件过滤 |
| 危大工程数量最多的5个项目 | 取数 · 项目维度 TopN |
| 哪些项目进度滞后 | 分析模板 · 产值缺口 |
| 风险项目有哪些 | 分析模板 · 风险台账 |
| 广州500千伏输变电工程的档案 | 项目档案 · 结构化卡片 |
| 两金压降有什么要求 | 知识库 · 制度检索 |
| 新签合同额的口径是什么 | 知识库 · 口径说明 |
| （追问）那按工程类型拆分呢 | 多轮下钻 · 继承上一轮指标 |

---

## 八、接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/periods` | 可选期间列表（期间选择器） |
| GET | `/api/meta` | 账号、模型状态、知识库、表/指标数量 |
| GET | `/api/dashboard?user_id=` | 驾驶舱数据 |
| GET | `/api/metrics` | 指标口径字典 |
| GET | `/api/schema` | 表清单（含行数与列数） |
| GET | `/api/table/{name}` | 单表详情：列定义、样例数据、相关指标、关联表 |
| GET | `/api/kpi-wide?period=` | 指标宽表 |
| GET | `/api/audit?limit=` | 查询审计 |
| GET | `/api/report/list` · `/api/report/<id>` | 报告列表 / 详情（含审批轨迹） |
| GET | `/api/report/export?id=&fmt=` | 导出 `md` / `docx` / `pdf` / `html`（html 内联预览，其余下载） |
| POST | `/api/report/stream` | SSE 生成进度：`stage`（逐步 running→ok）→ `result` / `error` |
| POST | `/api/ask` | 问答 `{user_id, question, session_id}` |
| POST | `/api/ask/stream` | SSE 流：`stage`（阶段）→ `sql`（逐字）→ `result` / `error` |
| POST | `/api/report/build` | 生成报告 |
| POST | `/api/report/validate` | 执行兜底校验 |
| POST | `/api/report/action` | `approve` / `reject` / `push` |

---

## 九、目录结构

完整的目录树与每层职责见 [README 的「目录结构」](../README.md#目录结构)，
这里不再重复，避免两处维护导致不一致。

速查：

| 位置 | 职责 |
|---|---|
| `app/service.py` | 业务服务层，与 HTTP 框架无关 |
| `app/nl2sql/` | 词表、提示词、计划器、修复回路、路由 |
| `app/report/` | 报告编排、章节、校验、导出、审批流 |
| `frontend/src/` | Vue 3 + TypeScript 前端（views / components / stores / api / utils） |
| `tests/test_smoke.py` | 后端端到端自检 |

## 九之一、前端架构说明

| 语言 | 全量 TypeScript：`src/types.ts` 统一描述后端返回结构，`vue-tsc --noEmit` 零错误 |
| 路由 | `vue-router` history 模式；后端对非 `/api` 且未命中的路径回退 `index.html`，刷新不 404 |
| 状态 | 轻量 `reactive` store（身份 / 期间 / 数据范围 / 会话），未引入 Pinia，减少依赖 |
| 接口 | `src/api/index.ts` 统一封装，`VITE_API_BASE` 可切换网关地址 |
| 流式 | `askStream()` 解析 SSE：`stage` 阶段、`sql` 逐字、`result` 结果；失败自动回退普通接口 |
| 图表 | `utils/charts.ts` 输出 ECharts option（条形 / 折线 / 环形），`EChart.vue` 负责实例与自适应 |
| 按需打包 | ECharts 仅引入 bar/line/pie + 必要组件，产物 536 KB（gzip 181 KB），较全量减少约 50% |
| 表结构 | 数据表卡片可点击，`TableDrawer` 抽屉展示列定义 / 样例数据 / 相关指标 / 关联表，支持深链 `/data?table=xxx` |
| 测试 | Vitest + @vue/test-utils，51 项覆盖格式化、Markdown、图表配置、SSE 解析、聊天渲染、步进器、抽屉、多会话与分组 |
| 深链 | `/chat?q=xxx` 自动提问、`/report?report=latest`、`/data?table=FACT_CONTRACT` |
| 打印 | 报告页 `@media print` 隐藏导航与操作区，直接输出正文 |

> 后端若要换成 FastAPI，只需把 `app/api.py` 的 `_api_get/_api_post` 逐个映射为路由函数（约 60 行），业务层 `metrics / permission / router / report` 无需改动——这也是当初把 HTTP 与业务分离的原因。

## 九之二、优化记录

| 类别 | 优化点 |
|---|---|
| **修复** | 报告生成原本忽略岗位范围（分公司负责人可生成全院报告）——现按 `scope_filters` 出数，抬头标注数据范围，非财务岗自动脱敏利润章且不进入校验口径 |
| **修复** | 同比基期错误：原实现取「上一期再往前一年」，现统一为「本期整体前移 12 个月」，与看板口径一致 |
| **修复** | 权限谓词注入会插进子查询内部导致语法错误——改为括号深度扫描定位顶层 `WHERE` |
| **修复** | 列级脱敏只在有值时生效，导致无数据时显示"—"而非"无权限" |
| **增强** | 报表支持 5 段状态机可视化 + 按状态禁用按钮 + 导出 Markdown / 打印样式 |
| **增强** | 问答：占比问题补「占比(%)」列、同比提问优先展示同比、每轮回答附 3 条可点击追问 |
| **增强** | 口径类问题（"毛利率怎么算"）优先返回 DIM_KPI 权威定义，再附制度原文，避免答成数值 |
| **增强** | 非业务问题（"今天天气"）走引导话术，不再返回"知识库未检索到" |
| **增强** | 期间选择器（2025-01 ~ 2026-10）、URL 深链、图表 hover 提示、加载动画、滚动修正 |
| **数据** | 项目周期与签约金额重新标定，同比/环比不再出现 ±50% 的失真；重点项目危大工程集中在近两月，排名有区分度 |
| **架构** | 前端从原生 JS 迁移到 Vue 3 + Vite + Vue Router + ECharts，拆分为 5 个视图与 5 个通用组件；后端补 CORS 与 SPA 回退 |
| **修复** | 占比类问题的环图把"占比"当成金额画（中心显示"合计 100"），改为按金额取数、图例显示占比 |
| **修复** | 聊天回答"卡在思考中"：直接改 push 进去的原始对象不触发 Vue 响应式，改为回写数组下标 |
| **架构** | 抽出 `app/service.py` 业务层，标准库与 FastAPI 两个适配层共用；`python run.py` 自动择优 |
| **类型** | 前端迁移到 TypeScript，`types.ts` 与后端返回对齐；修正 TS7/vue-tsc、Vitest5/Vite5 版本不兼容 |
| **流式** | 新增 `/api/ask/stream`（SSE）：阶段提示 + SQL 逐字 + 结果；前端可开关，失败自动回退 |
| **体验** | 数据表可点击查看结构（抽屉）、指标/表面板支持搜索、看板骨架屏、SQL 一键复制、追问推荐、深链 |
| **修复** | 报告表新增 `SCOPE_DESC`（含老库自动迁移），`?report=latest` 只打开与当前数据范围一致的报告，避免看到别的单位口径 |
| **修复** | 自检脚本会写入演示报告并污染列表，改为结束时清理自己产生的报告 |

---

## 十、上生产需要替换的部分

| 演示实现 | 生产方案 |
|---|---|
| SQLite + `to_sqlite()` | Oracle 11g + `cx_Oracle`，只需替换 `db.run_query` 执行器 |
| 内置规则引擎（离线） | 内网 vLLM / DeepSeek，设置 `GDJY_LLM_KEY` 即切换，链路不变 |
| 演示账号（6 个岗位） | 对接院内统一权限中心，同步"人员-岗位-数据范围" |
| BM25 字符二元组 | 向量库（bge-m3 等）+ 混合检索 |
| 文件内 Markdown 知识库 | 知识库平台 + 文档版本管理 |
| 审批状态机 | 对接院内 OA / 集团经营平台接口（回执号机制已预留） |
| 单机定时触发 | Airflow / 定时任务：每期自动生成 → 校验 → 待审批 |
