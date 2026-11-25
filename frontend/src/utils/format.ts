export function fmt(v: unknown, d = 2): string {
  if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return '—'
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
}

export const fmtInt = (v: unknown): string => fmt(v, 0)

export function pct(v: unknown, d = 1): string {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return (n >= 0 ? '+' : '') + n.toFixed(d) + '%'
}

export function intentLabel(i?: string): string {
  const map: Record<string, string> = {
    data: '取数', archive: '项目档案', kb: '制度口径', clarify: '待确认', chat: '引导',
  }
  return (i && map[i]) || i || ''
}

export function truncate(text: string, len: number): string {
  return text.length > len ? text.slice(0, len) + '…' : text
}
