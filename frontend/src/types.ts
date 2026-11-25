/** 前后端共享的数据结构定义（与 app/service.py 的返回保持一致） */

export interface User {
  user_id: string
  staff_id: string
  name: string
  role: string
  org_id: string
  org_name: string
  scope_type: 'ALL' | 'ORG' | 'DEPT' | 'PROJ'
  desc: string
}

export interface Period {
  value: string // YYYY-MM
  label: string
}

export interface MetricMeta {
  kpi: string
  name: string
  unit: string
  value: number | string
  masked?: boolean
  mom?: number | null
  yoy?: number | null
  category?: string
  category_name?: string
}

export interface ChartSpec {
  type: 'bar' | 'line' | 'pie'
  title: string
  labels: string[]
  series: { name: string; data: number[] }[]
  unit: string
  highlight?: number
}

export interface RiskRow {
  项目名称: string
  分公司: string
  缺口_万元: number
  完成率_百分比?: number
}

export interface DashboardData {
  period: { start: string; end: string; label: string }
  top: MetricMeta[]
  cards: MetricMeta[]
  charts: ChartSpec[]
  risks: RiskRow[]
  scope: string
  masked: boolean
  user: { name: string; role: string; org: string }
}

export type Intent = 'data' | 'archive' | 'kb' | 'clarify' | 'chat'

export interface RepairTrace {
  status: 'ok' | 'repaired' | 'failed' | 'rejected'
  attempts: { round: number; sql: string; error: string | null; fix: string | null }[]
  scope?: string
  degraded?: boolean
}

export interface AskPayload {
  answer: string
  intent: Intent
  latency_ms: number
  sql?: string | null
  rows?: Record<string, unknown>[]
  columns?: string[]
  chart?: ChartSpec | null
  explain?: string
  degraded?: boolean
  llm_used?: boolean
  repair?: RepairTrace
  related?: string[]
  sources?: { doc: string; title: string; score: number }[]
  scope?: string
  user?: { name: string; role: string }
}

export interface StageEvent {
  name: string
  text: string
}

export interface MetaInfo {
  users: User[]
  llm: { mode: string; model: string; online: boolean }
  kb: { chunks: number; files: number; list: string[] }
  tables: number
  metrics: number
  categories: Record<string, string>
  oracle_rules: string
  export?: { docx: boolean; pdf: boolean; markdown: boolean; html: boolean }
}

export interface TableColumn {
  name: string
  type: string
  pk: boolean
}

export interface SchemaTable {
  table: string
  rows: number
  columns: TableColumn[]
}

export interface TableDetail {
  table: string
  rows: number
  columns: TableColumn[]
  samples: Record<string, unknown>[]
  related_kpis: { kpi: string; name: string; unit: string }[]
  related_tables: { table: string; shared: string[] }[]
}

export interface MetricDictItem {
  KPI_ID: string
  KPI_NAME: string
  CATEGORY: string
  category_name: string
  UNIT: string
  DEFINITION: string
  CALIBER_ID: string
  OWNER_DEPT: string
  caliber: string
  in_engine: boolean
}

export interface ReportStep {
  name: string
  title: string
  text: string
  status: 'running' | 'ok' | 'warn' | 'fail'
  ms: number
  at: number
}

export interface ReportTrace {
  steps: ReportStep[]
  total_ms: number
}

export interface ReportInfo {
  report_id: string
  title: string
  label: string
  content_md: string
  metrics: MetricMeta[]
  exceptions: MetricMeta[]
  llm_used: boolean
  tables?: number
  trace?: ReportTrace | null
  pre_check?: ValidateResult | null
}

export interface Approval {
  OP_TIME: string
  STEP: string
  APPROVER: string
  ACTION: string
  COMMENT: string
}

export interface PushLog {
  PUSH_TIME: string
  CHANNEL: string
  RECEIPT_NO: string
  STATUS: string
}

export interface Timeline {
  status: string
  states: string[]
  allowed: string[]
  approvals: Approval[]
  push: PushLog[]
}

export interface ValidateItem {
  rule: string
  ok: boolean
  level: 'error' | 'warn'
  message: string
  detail?: string
}

export interface ValidateResult {
  passed: boolean
  total: number
  passed_count: number
  score: number
  items: ValidateItem[]
  blocking: ValidateItem[]
}

export interface AuditRow {
  LOG_ID: string
  USER_ID: string
  QUESTION: string
  INTENT: string
  ROW_CNT: number
  COST_MS: number
  STATUS: string
  SCOPE_DESC: string
  CREATE_TIME: string
}

export interface ReportRecord {
  REPORT_ID: string
  SCOPE_DESC?: string
  trace?: ReportTrace | null
  TITLE: string
  STATUS: string
  BUILDER: string
  CREATE_TIME: string
  PERIOD_START: string
  PERIOD_END: string
  content_md: string
  validate: ValidateResult | null
  timeline?: Timeline
}
