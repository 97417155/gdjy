# 贡献指南

感谢愿意花时间改进这个项目。下面是最短路径，照着做基本不会踩坑。

## 开发环境

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.10+ | 必须（后端只依赖标准库） |
| Node.js | 18+ | 仅改前端时需要 |
| npm | 9+ | 建议加 `--registry=https://registry.npmmirror.com` |

```bash
# 后端
python run.py --init-only        # 建库 + 造数 + 建宽表
python run.py --port 8848        # 起服务

# 前端（另开终端）
cd frontend
npm install
npm run dev                      # http://localhost:5173，/api 代理到 8848
```

可选依赖（FastAPI、Word/PDF 导出）：`pip install -r requirements.txt`。

## 目录约定

| 想改什么 | 去哪里 |
|---|---|
| 指标口径、取数 SQL | `app/metrics.py` |
| 问答意图、计划、措辞 | `app/nl2sql/`（`lexicon.py` 词表、`planner.py` 计划、`router.py` 组装答复） |
| 权限范围与脱敏 | `app/permission.py` |
| 报告章节与措辞 | `app/report/sections.py` |
| 校验规则 | `app/report/validator.py` |
| 导出样式 | `app/report/export.py` |
| 页面与组件 | `frontend/src/views`、`frontend/src/components` |
| 接口契约 | `app/service.py`（业务）+ `server/fastapi_app.py` / `app/api.py`（协议） |

**不要手改 `web/`**：它是 `npm run build` 的产物，改前端请改 `frontend/src` 后重新构建。

## 分支与提交

- 从 `main` 切分支：`feat/xxx`、`fix/xxx`、`docs/xxx`
- 提交信息用 Conventional Commits 简版：

```
feat(report): 报告支持按章节分页导出 PDF
fix(permission): 修复谓词注入命中子查询 WHERE 的问题
docs(readme): 补充导出依赖说明
test(frontend): 补充会话分组单测
```

- 一个 PR 只做一件事，附带"为什么"而不是只写"改了什么"。

## 提交前自检

```bash
python tests/test_smoke.py       # 后端 36 项，必须全绿
cd frontend
npm run type-check               # 类型零错误
npm test                         # 前端 51 项，必须全绿
npm run build                    # 需要提交 web/ 时执行
```

CI 会跑同样三件事；本地先跑能省一轮来回。

## 常见改动怎么做

### 新增一个指标

1. 在 `app/metrics.py` 的 `METRICS` 增加一项：`name / cat / unit / expr / from / where`，
   需要跨表就写 `join`、需要派生就写 `derive`。
2. 在 `app/seed.py` 的 `DIM_KPI` 数据里登记口径（名称、定义、归口部门、口径编号）。
3. 把它加进 `KPI_ORDER` 或对应报告的章节列表（`app/report/builder.py` 的 `CHAPTERS`）。
4. 跑 `python run.py --init-only`（宽表会自动扩列）+ `python tests/test_smoke.py`。
5. 若该指标需要中文同义词，在 `app/nl2sql/lexicon.py` 的 `SYNONYMS` 里补。

### 新增一张表

1. `app/seed.py` 的 DDL 段落加 `CREATE TABLE`（注意 Oracle 兼容的字段命名）。
2. 造数逻辑里补数据，保持固定随机种子。
3. 如果参与指标，回到上一步；如果只用于档案检索，改 `app/nl2sql/planner.py` 的档案查询模板。
4. 表结构抽屉会自动出现（读取 `information_schema` / `PRAGMA`），无需额外改前端。

### 新增一个页面

`frontend/src/views/` 建文件 → `frontend/src/router/index.ts` 注册（带 `meta.title` 与 `meta.icon`）→
侧边栏自动出现入口。取数统一走 `frontend/src/api/index.ts`。

## 代码风格

- Python：4 空格缩进、行宽 100、类型标注尽量补齐；不引入额外格式化工具（保持零依赖）。
- TypeScript / Vue：`<script setup lang="ts">`，props 与 emit 显式声明类型；`vue-tsc` 零错误是硬要求。
- 注释写"为什么"，不写"是什么"；口径类逻辑必须在注释里点明业务含义。

## PR 检查清单

- [ ] 有对应的 Issue 或说明动机
- [ ] 后端自检全绿；新增行为有对应用例
- [ ] 前端类型检查与单测全绿
- [ ] 涉及接口变更时同步更新 `docs/api.md`
- [ ] 涉及口径 / 权限变更时同步更新 `docs/architecture.md`
- [ ] 没有提交 `_pydeps/`、`node_modules/`、`data/db/*.db`

## 行为准则

参与本项目即表示同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
