# 前端（Vue 3 + TypeScript + Vite）

```bash
npm install --registry=https://registry.npmmirror.com   # 首次
npm run dev        # 开发：http://localhost:5173 ，/api 代理到 8848
npm run build      # 构建：输出到 ../web，由 Python 后端托管
npm run type-check # vue-tsc 全量类型检查
npm test           # Vitest 单元测试
```

## 目录

```
src/
├── main.ts             # 挂载入口
├── App.vue             # 全局布局（侧边栏 + router-view），启动时拉取 meta 与期间
├── types.ts            # 与后端 service 返回结构对齐的类型定义
├── router/index.ts     # 5 个路由 + 未匹配重定向
├── stores/session.ts   # 身份 / 期间 / 数据范围 / 会话（reactive，无需 Pinia）
├── api/
│   ├── index.ts        # 接口封装 + askStream()（SSE 解析）
│   └── __tests__/stream.spec.ts
├── utils/
│   ├── charts.ts       # ECharts option 构造（bar / line / donut）
│   ├── markdown.ts     # 轻量 Markdown 渲染 + 目录抽取
│   ├── format.ts       # 数字 / 百分比 / 意图标签
│   └── __tests__/      # 12 项
├── components/
│   ├── AppSidebar.vue  # 导航 + 身份切换 + 数据范围
│   ├── EChart.vue      # 图表封装（按需引入、ResizeObserver 自适应）
│   ├── ChatMessage.vue # 单条问答：阶段、SQL 逐字、表格、图表、复制、追问
│   ├── TableDrawer.vue # 表结构抽屉：列定义 / 样例 / 相关指标 / 关联表
│   ├── ReportStepper.vue
│   ├── Toast.vue
│   └── __tests__/      # 15 项
└── views/
    ├── DashboardView.vue  # KPI + 3 张图 + 缺口清单 + 七类指标（骨架屏）
    ├── ChatView.vue       # SSE 流式问答，失败自动回退；支持 /chat?q=
    ├── ReportView.vue     # 生成 / 校验 / 审批 / 推送 / 导出 / 打印，支持 ?report=latest
    ├── DataView.vue       # 指标字典 + 表清单（可点击看结构）+ 权限矩阵，支持 ?table=
    └── AuditView.vue
```

## 约定

- 组件只处理展示与交互，取数统一走 `api/`；
- 组件 props / emit 全部带类型，事件用 `defineEmits<{...}>()` 声明；
- 图表一律用 `utils/charts.ts` 生成 option，保证同一指标在不同页面视觉一致；
- 新增页面：在 `views/` 建文件 → `router/index.ts` 注册 → 侧边栏自动出现（读取 `meta.title` / `meta.icon`）。

## 测试覆盖

| 文件 | 覆盖点 |
|---|---|
| `utils/format.spec.ts` | 千分位、百分比符号、空值、意图映射、截断 |
| `utils/markdown.spec.ts` | 标题/加粗/表格/列表/引用、HTML 转义、目录抽取 |
| `utils/charts.spec.ts` | 条形数据映射与标签截断、折线保留精度、"其他"合并后合计不丢数、图表选型 |
| `api/stream.spec.ts` | SSE 事件分发、跨网络分片拼装、error 事件 |
| `components/ChatMessage.spec.ts` | 正文渲染、生成中阶段、追问事件、SQL 折叠、修复标签、错误态 |
| `components/ReportStepper.spec.ts` | 各状态的完成/当前步骤与连线 |
| `components/TableDrawer.spec.ts` | 打开拉取、页签切换、关联表跳转、关闭事件、接口异常 |
