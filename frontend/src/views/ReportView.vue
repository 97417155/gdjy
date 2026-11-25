<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ReportStepper from '@/components/ReportStepper.vue'
import { api, buildReportStream } from '@/api'
import { store, periodEnd, notify } from '@/stores/session'
import { renderMarkdown, extractHeadings } from '@/utils/markdown'
import type { ReportInfo, ReportStep, ReportTrace, Timeline, ValidateResult } from '@/types'

const route = useRoute()

const report = ref<ReportInfo | null>(null)
const timeline = ref<Timeline | null>(null)
const validate = ref<ValidateResult | null>(null)
const building = ref(false)
const steps = ref<ReportStep[]>([])
const trace = ref<ReportTrace | null>(null)
const showTrace = ref(true)
const viewMode = ref<'paged' | 'flow'>('paged')
const bodyEl = ref<HTMLElement | null>(null)

const status = computed<string>(() => timeline.value?.status ?? '草稿')
const mdSource = computed(() => String(report.value?.content_md ?? '').replace(/^#\s+.*\n+/, ''))
const bodyHtml = computed(() => renderMarkdown(mdSource.value))
const toc = computed(() => extractHeadings(mdSource.value))
/** 正文里的表格数量（按表头分隔行统计） */
const tableCount = computed(() => (mdSource.value.match(/^\|\s*-{3}/gm) ?? []).length)

/** 分页：按二级标题（章）切页，与导出的 Word / PDF 分页保持一致 */
const pages = computed(() => {
  const chunks = mdSource.value.split(/\n(?=## )/).filter((c) => c.trim())
  // 首个 ## 之前是"数据来源"等引言，并到第一章，避免首页只有一行引用
  if (chunks.length > 1 && !chunks[0].startsWith('## ')) {
    chunks.splice(0, 2, chunks[0].trimEnd() + '\n\n' + chunks[1])
  }
  return chunks.map((md, i) => ({ no: i + 1, md, html: renderMarkdown(md) }))
})
const pageCount = computed(() => pages.value.length)

const doneSteps = computed(() => steps.value.filter((s) => s.status !== 'running').length)
const totalMs = computed(() => trace.value?.total_ms ?? steps.value.reduce((a, s) => a + (s.ms || 0), 0))
const canExportWord = computed(() => store.meta?.export?.docx !== false)
const canExportPdf = computed(() => store.meta?.export?.pdf !== false)

const canSubmit = computed(() => ['草稿', '已校验'].includes(status.value))
const canPass = computed(() => status.value === '待审批')
const canPush = computed(() => status.value === '已通过')

function upsertStep(step: ReportStep): void {
  const i = steps.value.findIndex((s) => s.name === step.name)
  if (i >= 0) steps.value[i] = { ...step }
  else steps.value.push({ ...step })
}

async function build(): Promise<void> {
  building.value = true
  steps.value = []
  trace.value = null
  showTrace.value = true
  validate.value = null
  const start = `${store.period}-01`
  const end = periodEnd(store.period)
  try {
    await buildReportStream(store.userId, start, end, {
      onStage: upsertStep,
      onResult: (r) => {
        report.value = r
        trace.value = r.trace ?? { steps: [...steps.value], total_ms: totalMs.value }
        validate.value = r.pre_check ?? null
      },
      onError: (m) => notify('生成失败：' + m),
    })
    if (!report.value) {
      // 后端未返回结果（流中断）时兜底走普通接口
      const r = await api.buildReport(store.userId, start, end)
      report.value = r
      trace.value = r.trace ?? null
      validate.value = r.pre_check ?? null
    }
    await refreshTimeline()
    notify('报告已生成')
  } catch (e) {
    // 老后端没有 /api/report/stream 时自动降级
    try {
      const r = await api.buildReport(store.userId, start, end)
      report.value = r
      trace.value = r.trace ?? null
      validate.value = r.pre_check ?? null
      await refreshTimeline()
      notify('报告已生成（普通模式）')
    } catch (e2) {
      notify('生成失败：' + (e2 as Error).message)
    }
  } finally {
    building.value = false
  }
}

async function loadLatest(): Promise<void> {
  try {
    const list = await api.reportList()
    if (!list.length) return
    // 报告带数据范围，避免把别的岗位/单位口径的报告当成自己的打开
    const mine = list.filter((r) => !r.SCOPE_DESC || r.SCOPE_DESC === store.scope)
    if (!mine.length) {
      notify('没有与当前数据范围匹配的历史报告，请先点击「生成本期报告」')
      return
    }
    list.splice(0, list.length, ...mine)
    const rep = await api.report(list[0]!.REPORT_ID)
    report.value = {
      report_id: rep.REPORT_ID,
      title: rep.TITLE,
      content_md: rep.content_md,
      metrics: [],
      exceptions: [],
      llm_used: false,
      label: `${rep.PERIOD_START} 至 ${rep.PERIOD_END}`,
      trace: rep.trace ?? null,
    }
    trace.value = rep.trace ?? null
    steps.value = rep.trace?.steps ? [...rep.trace.steps] : []
    showTrace.value = true
    validate.value = rep.validate ?? null
    await refreshTimeline()
  } catch (e) {
    notify('加载历史报告失败：' + (e as Error).message)
  }
}

async function refreshTimeline(): Promise<void> {
  if (!report.value) return
  const rep = await api.report(report.value.report_id)
  timeline.value = rep.timeline ?? null
}

async function runValidate(): Promise<void> {
  if (!report.value) return
  try {
    const r = await api.validateReport(store.userId, report.value.report_id)
    validate.value = r.validate
    await refreshTimeline()
    notify(r.validate.passed ? '校验通过，可提交审批' : '校验未通过，请修正后重试')
  } catch (e) {
    notify('校验失败：' + (e as Error).message)
  }
}

async function act(action: string): Promise<void> {
  if (!report.value) return
  try {
    const r = await api.reportAction(store.userId, report.value.report_id, action)
    await refreshTimeline()
    notify(r.message || '当前状态：' + r.status)
  } catch (e) {
    notify('操作失败：' + (e as Error).message)
  }
}

function exportAs(fmt: 'md' | 'docx' | 'pdf' | 'html'): void {
  if (!report.value) return
  const url = api.exportUrl(report.value.report_id, fmt)
  if (fmt === 'html') {
    window.open(url, '_blank')          // HTML 内联预览，可直接 Ctrl+P 存 PDF
    return
  }
  // 其余格式走下载：用隐藏链接，避免多开一个空白标签页
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function printReport(): void {
  window.print()
}

/** 目录跳转：分页视图定位到对应页，连续视图滚动到对应标题 */
function gotoToc(index: number): void {
  if (viewMode.value === 'paged') {
    const title = toc.value[index]?.title ?? ''
    const pageIdx = pages.value.findIndex((p) => p.md.includes(title))
    if (pageIdx >= 0) {
      document.getElementById('page-' + (pageIdx + 1))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    return
  }
  const el = bodyEl.value?.querySelector<HTMLElement>('#sec-' + index)
  if (el && bodyEl.value) bodyEl.value.scrollTo({ top: el.offsetTop - 12, behavior: 'smooth' })
}

/** 连续视图渲染后给 h2 打锚点 */
watch(bodyHtml, () => {
  nextTick(() => {
    const hs = bodyEl.value?.querySelectorAll('h2') ?? []
    hs.forEach((h, i) => {
      h.id = 'sec-' + i
    })
  })
})

onMounted(() => {
  if (route.query.report) loadLatest()
})

/** 切换身份后报告口径已变，清空避免串号 */
watch(() => store.userId, () => {
  report.value = null
  validate.value = null
  timeline.value = null
  steps.value = []
  trace.value = null
})
</script>

<template>
  <header class="page-head print-hide">
    <div>
      <h1>经营分析报告</h1>
      <p class="sub">指标抽取 → 同比环比 → 正文撰写 → 兜底校验 → 落库，每一步都可追溯</p>
    </div>
    <div class="head-tools">
      <select v-model="store.period" class="select">
        <option v-for="p in store.periods" :key="p.value" :value="p.value">{{ p.label }}</option>
      </select>
      <button class="btn primary" :disabled="building" @click="build">
        {{ building ? '生成中…' : '生成本期报告' }}
      </button>
    </div>
  </header>

  <!-- 生成过程：SSE 实时推进，生成完成后作为可追溯记录保留 -->
  <div v-if="steps.length" class="card trace print-hide">
    <div class="trace-head" @click="showTrace = !showTrace">
      <div class="th-left">
        <b>生成过程</b>
        <span class="sub">
          {{ doneSteps }}/{{ steps.length }} 步
          <template v-if="!building && totalMs"> · 总耗时 {{ totalMs }} ms</template>
        </span>
      </div>
      <span class="chev">{{ showTrace ? '收起 ▲' : '展开 ▼' }}</span>
    </div>
    <div v-show="showTrace" class="trace-list">
      <div v-for="(s, i) in steps" :key="s.name" class="tstep" :class="s.status">
        <div class="rail">
          <span class="dot">
            <i v-if="s.status === 'running'" class="spin"></i>
            <template v-else>{{ s.status === 'ok' ? '✓' : '!' }}</template>
          </span>
          <span v-if="i < steps.length - 1" class="line"></span>
        </div>
        <div class="body">
          <div class="row">
            <b>{{ s.title }}</b>
            <span class="ms">{{ s.status === 'running' ? '进行中…' : s.ms + ' ms' }}</span>
          </div>
          <div class="text">{{ s.text }}</div>
        </div>
      </div>
    </div>
  </div>

  <div v-if="!report" class="card empty-state print-hide">
    <div class="empty-icon">
      <svg viewBox="0 0 24 24" width="26" height="26">
        <path d="M6 3.5h8l5 5v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-16a1 1 0 0 1 1-1z"
              fill="none" stroke="currentColor" stroke-width="1.4" />
        <path d="M13.6 3.8v4.9h4.9" fill="none" stroke="currentColor" stroke-width="1.4" />
      </svg>
    </div>
    <h3>{{ building ? '正在生成本期报告…' : '还没有生成报告' }}</h3>
    <p class="sub">
      {{ building
        ? '左侧步骤会实时推进，指标抽取、表格生成、校验各自耗时可见。'
        : '点击右上角「生成本期报告」，系统会抽取 28 项指标、按七章体例撰写「文字 + 数据表格」的正文，并通过 10 条规则做兜底校验。' }}
    </p>
  </div>

  <template v-else>
    <div class="card print-hide">
      <div class="title-row">
        <div>
          <h2>{{ report.title }}</h2>
          <p class="sub">
            {{ report.label }} ·
            <template v-if="report.metrics.length">
              指标 {{ report.metrics.length }} 项 · 数据表 {{ tableCount }} 张 · 异常 {{ report.exceptions.length }} 项 ·
            </template>
            <template v-else-if="tableCount">数据表 {{ tableCount }} 张 · </template>
            {{ report.llm_used ? '模型撰写' : '内置文案引擎' }}
          </p>
        </div>
        <div class="head-tools">
          <button class="btn" @click="exportAs('docx')" :disabled="!canExportWord">导出 Word</button>
          <button class="btn" @click="exportAs('pdf')" :disabled="!canExportPdf">导出 PDF</button>
          <button class="btn" @click="exportAs('md')">导出 Markdown</button>
          <button class="btn" @click="printReport">打印</button>
        </div>
      </div>

      <ReportStepper :status="status" />

      <div class="head-tools report-actions">
        <button class="btn" :disabled="status === '已推送'" @click="runValidate">执行校验</button>
        <button class="btn" :disabled="!canSubmit" @click="act('approve')">提交审批</button>
        <button class="btn" :disabled="!canPass" @click="act('approve')">审批通过</button>
        <button class="btn primary" :disabled="!canPush" @click="act('push')">推送 OA</button>
      </div>

      <div v-if="validate" class="validate">
        <div class="v-head">
          <div class="v-score" :class="validate.passed ? 'pass' : 'fail'">{{ validate.score }}</div>
          <div>
            <b>兜底校验{{ validate.passed ? '通过' : '未通过' }}</b>
            <div class="sub">
              {{ validate.passed_count }}/{{ validate.total }} 条规则通过 · {{ validate.blocking.length }} 项阻断
            </div>
          </div>
        </div>
        <div class="v-list">
          <div v-for="i in validate.items" :key="i.rule" class="v-item" :class="i.ok ? 'ok' : 'ng'">
            <span class="i">{{ i.ok ? '✓' : '✕' }}</span>
            <span><b>{{ i.rule }}</b><span class="m"> · {{ i.message }}</span></span>
          </div>
        </div>
      </div>
    </div>

    <div class="report-layout">
      <aside class="card toc print-hide">
        <div class="card-head">
          <h3>目录</h3>
          <div class="view-switch">
            <button :class="{ active: viewMode === 'paged' }" @click="viewMode = 'paged'">分页</button>
            <button :class="{ active: viewMode === 'flow' }" @click="viewMode = 'flow'">连续</button>
          </div>
        </div>
        <a v-for="(h, i) in toc" :key="h.id" @click="gotoToc(i)">{{ h.title }}</a>
        <div class="toc-foot">
          <div class="toc-label">
            流程轨迹
            <span v-if="pageCount">· 共 {{ pageCount }} 页</span>
          </div>
          <div v-for="(a, i) in timeline?.approvals ?? []" :key="'a' + i" class="tl-row">
            <span class="tl-time">{{ (a.OP_TIME || '').slice(5, 16) }}</span>
            <span>{{ a.ACTION }} · {{ a.APPROVER }}</span>
          </div>
          <div v-for="(p, i) in timeline?.push ?? []" :key="'p' + i" class="tl-row">
            <span class="tl-time">{{ (p.PUSH_TIME || '').slice(5, 16) }}</span>
            <span>{{ p.CHANNEL }} · {{ p.RECEIPT_NO }}</span>
          </div>
        </div>
      </aside>

      <!-- 分页视图：一章一页，页脚有页码，打印与导出 PDF 一致 -->
      <div v-if="viewMode === 'paged'" class="pager">
        <article
          v-for="p in pages"
          :id="'page-' + p.no"
          :key="p.no"
          class="card sheet md"
          v-html="p.html"
        ></article>
        <div class="page-foot print-hide">共 {{ pageCount }} 页 · 导出 PDF / Word 时按此分页</div>
      </div>

      <article v-else ref="bodyEl" class="card report-body md" v-html="bodyHtml"></article>
    </div>
  </template>
</template>

<style scoped>
.title-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.report-actions { margin-top: 12px; }
.validate { margin-top: 14px; border-top: 1px solid var(--line-2); padding-top: 12px; }
.v-head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.v-score {
  width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center;
  justify-content: center; font-size: 13px; font-weight: 600;
}
.v-score.pass { background: #edf7f1; color: var(--down); }
.v-score.fail { background: #fbeeed; color: var(--bad); }
.v-list { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 18px; }
@media (max-width: 900px) { .v-list { grid-template-columns: 1fr; } }
.v-item { display: flex; gap: 7px; font-size: 12px; padding: 2px 0; }
.v-item .m { color: var(--ink-2); }
.v-item.ok .i { color: var(--down); }
.v-item.ng .i { color: var(--bad); }

/* ---------- 生成过程 ---------- */
.trace { padding: 12px 14px; }
.trace-head { display: flex; align-items: center; justify-content: space-between; cursor: pointer; }
.th-left { display: flex; align-items: baseline; gap: 9px; }
.th-left b { font-size: 13px; }
.chev { font-size: 11px; color: var(--ink-3); }
.trace-list { margin-top: 10px; display: flex; flex-direction: column; gap: 2px; }
.tstep { display: flex; gap: 10px; }
.rail { display: flex; flex-direction: column; align-items: center; width: 16px; flex: 0 0 16px; }
.rail .dot {
  width: 16px; height: 16px; border-radius: 50%; border: 1px solid var(--line);
  display: flex; align-items: center; justify-content: center;
  font-size: 9px; color: var(--ink-3); background: var(--surface);
}
.rail .line { flex: 1; width: 1px; background: var(--line); margin: 2px 0; }
.tstep.ok .dot { background: #edf7f1; border-color: #bfe3cd; color: #2e7d4f; }
.tstep.warn .dot { background: #fdf6e7; border-color: #ecd9a8; color: #9a6a12; }
.tstep.running .dot { border-color: var(--brand); color: var(--brand); }
.spin {
  width: 7px; height: 7px; border-radius: 50%; border: 1.5px solid #cfd9e5;
  border-top-color: var(--brand); animation: sp .7s linear infinite;
}
@keyframes sp { to { transform: rotate(360deg); } }
.tstep .body { padding-bottom: 7px; min-width: 0; }
.tstep .row { display: flex; align-items: baseline; gap: 9px; }
.tstep .row b { font-size: 12.5px; }
.tstep .ms { font-size: 10.5px; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.tstep .text { font-size: 11.5px; color: var(--ink-2); line-height: 1.55; }
.tstep.running .text { color: var(--ink-3); }

/* ---------- 目录 / 分页 ---------- */
.report-layout { display: grid; grid-template-columns: 232px 1fr; gap: 16px; align-items: start; }
@media (max-width: 1080px) { .report-layout { grid-template-columns: 1fr; } }
.toc { position: sticky; top: 22px; margin-bottom: 0; padding: 14px 14px 12px; }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.view-switch { display: flex; gap: 2px; background: var(--surface-2); border-radius: 6px; padding: 2px; }
.view-switch button {
  border: 0; background: transparent; font-size: 11px; color: var(--ink-3);
  padding: 2px 7px; border-radius: 4px; cursor: pointer;
}
.view-switch button.active { background: var(--surface); color: var(--brand); box-shadow: 0 1px 2px rgba(20,40,70,.08); }
.toc a { display: block; padding: 5px 8px; border-radius: 6px; font-size: 12.5px; color: var(--ink-2); cursor: pointer; }
.toc a:hover { background: var(--surface-2); color: var(--brand); }
.toc-foot { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--line-2); font-size: 11.5px; color: var(--ink-3); }
.toc-label { font-size: 11px; margin-bottom: 4px; }
.tl-row { display: flex; gap: 8px; padding: 2px 0; }
.tl-time { color: var(--ink-3); flex: 0 0 88px; font-size: 10.5px; }

.pager { display: flex; flex-direction: column; gap: 16px; }
.sheet {
  margin: 0; padding: 26px 30px 22px; min-height: 300px;
  box-shadow: 0 1px 3px rgba(20, 40, 70, .06);
  position: relative; counter-increment: page;
}
.sheet::after {
  content: "第 " counter(page) " 页";
  position: absolute; right: 30px; bottom: 10px;
  font-size: 10.5px; color: var(--ink-3);
}
.page-foot { text-align: center; font-size: 11px; color: var(--ink-3); padding: 4px 0 10px; }
.report-body { font-size: 13.5px; line-height: 1.75; max-height: calc(100vh - 150px); overflow-y: auto; }

.md :deep(h1) { font-size: 19px; margin-bottom: 10px; }
.md :deep(h2) {
  font-size: 15px; margin: 4px 0 10px; padding-bottom: 6px;
  border-bottom: 1px solid var(--line-2); color: var(--brand); scroll-margin-top: 20px;
}
.md :deep(blockquote) {
  margin: 10px 0; padding: 8px 12px; background: var(--surface-2);
  border-left: 3px solid #cfdceb; color: var(--ink-2); font-size: 12px; border-radius: 0 6px 6px 0;
}
.md :deep(ul) { padding-left: 18px; }
.md :deep(li) { margin: 3px 0; }
.md :deep(table) { margin: 10px 0; }

/* ---------- 打印：只输出正文页面，一章一页 ---------- */
@media print {
  .print-hide { display: none !important; }
  .report-layout { display: block; }
  .pager { gap: 0; }
  .sheet {
    box-shadow: none; border: 0; padding: 0; margin: 0;
    break-after: page; page-break-after: always;
  }
  .sheet:last-child { break-after: auto; page-break-after: auto; }
  .sheet::after { display: none; }
  @page { size: A4; margin: 18mm 16mm; }
}
</style>
