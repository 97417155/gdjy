/** 会话导出为 Markdown 记录：保留问题、回答、口径、SQL 与追问推荐。 */
import type { ChatMsg } from '@/components/ChatMessage.vue'
import type { ChatSession } from '@/stores/chat'

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function stamp(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const INTENT: Record<string, string> = {
  data: '自然语言取数', archive: '项目档案检索', kb: '制度口径', clarify: '待确认', chat: '引导',
}

/** 把一条会话渲染成 Markdown 文本 */
export function sessionToMarkdown(session: ChatSession): string {
  const lines: string[] = []
  const asks = session.messages.filter((m) => m.role === 'user').length
  lines.push(`# ${session.title}`, '')
  lines.push(`> 身份：${session.userName || '未标注'}｜创建：${stamp(session.createdAt)}｜更新：${stamp(session.updatedAt)}｜提问 ${asks} 次`,
    '')

  let turn = 0
  session.messages.forEach((m: ChatMsg) => {
    if (m.role === 'user') {
      turn += 1
      lines.push(`## 问 ${turn}`, '', m.text ?? '', '')
      return
    }
    if (m.error) {
      lines.push(`**答**（失败）`, '', `> ${m.error}`, '')
      return
    }
    const p = m.payload
    if (!p) return
    const meta = [INTENT[p.intent] ?? p.intent, p.latency_ms ? `${p.latency_ms} ms` : '',
      p.degraded ? '已降级' : '', p.llm_used ? '模型生成' : ''].filter(Boolean).join(' · ')
    lines.push(`**答**（${meta}）`, '', String(p.answer ?? '').trim(), '')
    if (p.explain) lines.push(`_理解：${p.explain}_`, '')
    if (p.sources?.length) {
      lines.push(`_引用：${p.sources.map((s) => s.title).join('、')}_`, '')
    }
    if (p.sql) {
      lines.push('```sql', String(p.sql).trim(), '```', '')
    }
    if (p.related?.length) {
      lines.push(`_可继续追问：${p.related.join(' / ')}_`, '')
    }
  })

  lines.push('---', '', `_由广东院经营分析智能问数系统导出 · ${stamp(Date.now())}_`)
  return lines.join('\n')
}

/** 触发浏览器下载 */
export function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
