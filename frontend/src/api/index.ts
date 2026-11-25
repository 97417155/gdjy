/** 统一接口层：替换 baseURL、加鉴权头、统一错误处理都只改这里 */
import type {
  AskPayload, AuditRow, DashboardData, MetaInfo, MetricDictItem, Period,
  ReportInfo, ReportRecord, ReportStep, SchemaTable, TableDetail, ValidateResult,
} from '@/types'

const BASE: string = import.meta.env.VITE_API_BASE || ''

interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
  params?: Record<string, string | number | undefined | null>
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status = 0) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, { method = 'GET', body, params }: RequestOptions = {}): Promise<T> {
  let url = BASE + path
  if (params) {
    const q = new URLSearchParams(
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null)
        .map(([k, v]) => [k, String(v)]),
    ).toString()
    if (q) url += (url.includes('?') ? '&' : '?') + q
  }
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const json = await res.json().catch(() => ({ ok: false, message: `HTTP ${res.status}` }))
  if (!json.ok) throw new ApiError(json.message || '请求失败', res.status)
  return json.data as T
}

export const api = {
  meta: () => request<MetaInfo>('/api/meta'),
  periods: () => request<Period[]>('/api/periods'),
  dashboard: (userId: string, start: string, end: string) =>
    request<DashboardData>('/api/dashboard', { params: { user_id: userId, start, end } }),
  ask: (userId: string, question: string, sessionId: string) =>
    request<AskPayload>('/api/ask', { method: 'POST', body: { user_id: userId, question, session_id: sessionId } }),
  metrics: () => request<MetricDictItem[]>('/api/metrics'),
  schema: () => request<SchemaTable[]>('/api/schema'),
  table: (name: string) => request<TableDetail>(`/api/table/${encodeURIComponent(name)}`),
  audit: (limit = 50) => request<AuditRow[]>('/api/audit', { params: { limit } }),
  buildReport: (userId: string, start: string, end: string) =>
    request<ReportInfo>('/api/report/build', { method: 'POST', body: { user_id: userId, start, end } }),
  validateReport: (userId: string, reportId: string) =>
    request<{ ok: boolean; validate: ValidateResult; status: string }>('/api/report/validate', {
      method: 'POST', body: { user_id: userId, report_id: reportId },
    }),
  reportAction: (userId: string, reportId: string, action: string, comment = '') =>
    request<{ ok: boolean; status: string; message?: string; receipt_no?: string }>('/api/report/action', {
      method: 'POST', body: { user_id: userId, report_id: reportId, action, comment },
    }),
  report: (id: string) => request<ReportRecord>('/api/report/' + id),
  reportList: () => request<ReportRecord[]>('/api/report/list'),
  exportUrl: (id: string, fmt: 'md' | 'docx' | 'pdf' | 'html' = 'md') =>
    `${BASE}/api/report/export?id=${encodeURIComponent(id)}&fmt=${fmt}`,
}

/* ------------------------------------------------------------------ */
/* SSE：SQL 生成过程逐字可见                                            */
/* ------------------------------------------------------------------ */

export interface StreamHandlers {
  onStage?: (stage: { name: string; text: string }) => void
  onSql?: (chunk: string, done: boolean) => void
  onResult?: (payload: AskPayload) => void
  onError?: (message: string) => void
}

/** 报告生成的阶段事件与结果 */
export interface ReportStreamHandlers {
  onStage?: (step: ReportStep) => void
  onResult?: (report: ReportInfo) => void
  onError?: (message: string) => void
}

/** 通用 SSE 读取：按 event 分发，跨网络分片也能正确拼装 */
async function readStream(
  path: string,
  body: unknown,
  onEvent: (event: string, payload: any) => void,
): Promise<void> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const json = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
    throw new ApiError(json.message || '请求失败', res.status)
  }
  if (!res.body) throw new ApiError('当前浏览器不支持流式响应')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const handle = (block: string): void => {
    let event = 'message'
    let data = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data += line.slice(5).trim()
    }
    if (!data) return
    try {
      onEvent(event, JSON.parse(data))
    } catch {
      /* 忽略无法解析的帧 */
    }
  }

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() || ''
    blocks.forEach(handle)
  }
  if (buffer.trim()) handle(buffer)
}

export async function askStream(
  userId: string,
  question: string,
  sessionId: string,
  handlers: StreamHandlers,
): Promise<void> {
  await readStream('/api/ask/stream',
    { user_id: userId, question, session_id: sessionId },
    (event, payload) => {
      if (event === 'stage') handlers.onStage?.(payload)
      else if (event === 'sql') handlers.onSql?.(payload.chunk ?? '', Boolean(payload.done))
      else if (event === 'result') handlers.onResult?.(payload as AskPayload)
      else if (event === 'error') handlers.onError?.(payload.message || '处理失败')
    })
}

/** 报告生成：逐步接收进度，最后拿到报告本体 */
export async function buildReportStream(
  userId: string,
  start: string,
  end: string,
  handlers: ReportStreamHandlers,
): Promise<void> {
  await readStream('/api/report/stream', { user_id: userId, start, end },
    (event, payload) => {
      if (event === 'stage') handlers.onStage?.(payload as ReportStep)
      else if (event === 'result') handlers.onResult?.(payload as ReportInfo)
      else if (event === 'error') handlers.onError?.(payload.message || '生成失败')
    })
}
