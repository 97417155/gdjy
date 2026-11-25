# 接口说明

所有接口统一返回：

```json
{ "ok": true, "data": { ... } }
```

出错时 `ok=false` 并带 `message`，HTTP 状态码取 400（参数问题）/ 404（不存在）/ 500（服务端异常）。

`user_id` 决定数据范围：`U001` 院长（全院）、`U002` 新能源分公司负责人、`U003` 电网设计部负责人、
`U004` 项目经理、`U005` 设计工程师、`U006` 财务专员。可从 `GET /api/meta` 获取全部账号。

交互式文档：装了 FastAPI 后访问 <http://127.0.0.1:8848/docs>。

---

## 基础

### `GET /api/health`

```json
{ "ok": true, "data": { "status": "up", "server": "fastapi" } }
```

### `GET /api/meta`

账号列表、知识库规模、表数、指标数、模型状态、导出能力（`export.docx/pdf/markdown/html`）。

### `GET /api/periods`

可选期间列表，倒序：`[{"value":"2026-10","label":"2026年10月"}, ...]`

### `GET /api/dashboard?user_id=U001&start=2026-10-01&end=2026-10-31`

```json
{
  "ok": true,
  "data": {
    "top": [{ "kpi": "HS_NEW_AMT", "name": "新签合同额", "value": 237998.0, "unit": "万元",
              "mom": 7.14, "yoy": -8.24, "masked": false }],
    "cards": [ ... ],
    "charts": [{ "type": "bar", "title": "各分公司新签合同额（万元）",
                 "labels": ["新能源分公司"], "series": [{ "name": "新签合同额", "data": [78515.0] }],
                 "unit": "万元" }],
    "risks": [ ... ],
    "scope": "全院数据",
    "masked": false,
    "period": { "start": "2026-10-01", "end": "2026-10-31", "label": "2026年10月" }
  }
}
```

### `GET /api/metrics`

指标字典（28 项）：`KPI_ID / KPI_NAME / CATEGORY / category_name / UNIT / DEFINITION / CALIBER_ID / OWNER_DEPT / caliber / in_engine`。

### `GET /api/schema` · `GET /api/table/{name}`

`/api/schema` 返回表清单与行数；`/api/table/FACT_CONTRACT` 返回列定义（含主键标记）、
样例行、相关指标、可能关联的表。

### `GET /api/kpi-wide?period=2026-10-01`

指标宽表原始行（一行 = 期间 × 分公司 × 项目等级）。

### `GET /api/audit?limit=50`

查询审计日志。`limit` 范围 1–500。

---

## 问答

### `POST /api/ask`

```bash
curl -X POST http://127.0.0.1:8848/api/ask \
  -H "Content-Type: application/json" \
  -d '{"user_id":"U001","question":"各分公司10月新签合同额排名"}'
```

```json
{
  "ok": true,
  "data": {
    "answer": "**2026年10月**期间，按分公司看 **新签合同额**：**新能源分公司** 为 **78,515.00 万元**，居首。",
    "intent": "data",
    "latency_ms": 9,
    "sql": "SELECT O.ORG_NAME AS D_ORG, NVL(SUM(C.AMT),0) AS VAL ...",
    "rows": [{ "分公司": "新能源分公司", "新签合同额(万元)": 78515.0 }],
    "columns": ["分公司", "新签合同额(万元)"],
    "chart": { "type": "bar", "labels": ["新能源分公司"], "series": [{ "data": [78515.0] }], "unit": "万元" },
    "explain": "指标：新签合同额；维度：分公司；期间：2026年10月",
    "degraded": false,
    "related": ["新签合同额按工程类型看", "近6个月新签合同额趋势", "新签合同额同比是多少"],
    "repair": { "status": "ok", "attempts": [] }
  }
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `intent` | `data` 取数 / `archive` 项目档案 / `kb` 制度口径 / `clarify` 需澄清 / `chat` 引导 |
| `sql` | **Oracle 11g 写法**的 SQL（界面与审计展示用） |
| `degraded` | `true` 表示 SQL 修复失败、已降级查指标宽表，数字口径不同，需提示用户 |
| `repair.attempts` | 每一轮修复的 SQL 与错误信息 |
| `masked` | 利润类指标在非财务岗位下返回 `***（无权限）` |

### `POST /api/ask/stream`（SSE）

请求体同 `/api/ask`。事件序列：

```
event: stage
data: {"name":"router","text":"意图识别：自然语言取数"}

event: stage
data: {"name":"plan","text":"指标：新签合同额；维度：分公司"}

event: sql
data: {"chunk":"SELECT O.ORG_NAME","done":false}
...
event: sql
data: {"chunk":"","done":true}

event: result
data: { ...与 /api/ask 相同的结果对象... }
```

出错时发 `event: error` + `{"message": "..."}`。
前端在流不可用时自动回退到普通接口。

---

## 报告

### `POST /api/report/build`

```bash
curl -X POST http://127.0.0.1:8848/api/report/build \
  -H "Content-Type: application/json" \
  -d '{"user_id":"U001","start":"2026-10-01","end":"2026-10-31"}'
```

返回 `report_id / title / label / content_md / metrics / exceptions / llm_used / tables / trace / pre_check`。
`start`/`end` 省略时取默认期间。

### `POST /api/report/stream`（SSE）

```bash
curl -N -X POST http://127.0.0.1:8848/api/report/stream \
  -H "Content-Type: application/json" \
  -d '{"user_id":"U001","start":"2026-10-01","end":"2026-10-31"}'
```

每一步先发 `status=running`，完成后发 `status=ok`（校验未过为 `warn`），前端按 `name` 就地更新：

```
event: stage
data: {"name":"metrics","title":"指标抽取","text":"读取 28 项指标的本期、上期与上年同期数据","status":"running","ms":0,"at":0}

event: stage
data: {"name":"metrics","title":"指标抽取","text":"28 项指标已抽取（2026-10-01 至 2026-10-31，数据范围：全院数据）","status":"ok","ms":2860,"at":2860}
...
event: result
data: { ...报告对象... }
```

五个步骤固定为：`metrics` 指标抽取 → `compare` 同比环比 → `compose` 正文撰写 →
`guard` 兜底校验 → `save` 报告落库。

### `POST /api/report/validate`

```bash
curl -X POST http://127.0.0.1:8848/api/report/validate \
  -H "Content-Type: application/json" \
  -d '{"user_id":"U001","report_id":"RP20261125102453"}'
```

返回 `validate`（得分、10 条规则明细、阻断项）与推进后的 `status`。校验不通过会退回草稿。

### `POST /api/report/action`

```json
{ "user_id": "U001", "report_id": "RP2026...", "action": "approve", "comment": "同意" }
```

`action`：`approve`（提交审批 / 审批通过，按当前状态自动推进）、`reject`（退回）、`push`（推送 OA，返回回执号）。

### `GET /api/report/list` · `GET /api/report/{id}`

列表返回 `REPORT_ID / TITLE / STATUS / BUILDER / CREATE_TIME / SCOPE_DESC / PERIOD_START / PERIOD_END`；
详情额外返回 `content_md`、审批轨迹 `timeline`、校验结果 `validate`、生成轨迹 `trace`。

### `GET /api/report/export?id=RP...&fmt=docx`

`fmt` 可选 `md` / `docx` / `pdf` / `html`：

- `docx`、`pdf`、`md`：带 `Content-Disposition: attachment` 下载
- `html`：内联返回，浏览器直接预览，可按 A4 打印成 PDF

依赖缺失时 `docx`/`pdf` 返回 500 与提示信息（`/api/meta` 的 `export` 字段会提前告诉前端哪些可用）。

---

## 错误示例

```json
{ "ok": false, "message": "查询未包含项目维度，无法完成行级权限校验，已拒绝执行" }
```

```json
{ "ok": false, "message": "未安装 reportlab，无法导出 PDF（pip install reportlab）" }
```
