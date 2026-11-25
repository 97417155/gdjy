/** 轻量 Markdown 渲染：只覆盖报告与问答里实际用到的语法，避免引入额外依赖 */

const escapeHtml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const inline = (t: string): string =>
  escapeHtml(t)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+?)`/g, '<code>$1</code>')

export interface Heading {
  id: string
  title: string
}

export function renderMarkdown(text: string | undefined | null): string {
  if (!text) return ''
  const lines = String(text).replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let table: string[] = []
  let list: string[] = []
  let quote: string[] = []

  const flushTable = (): void => {
    if (!table.length) return
    const rows = table.filter((r) => !/^\|[\s\-:|]+\|$/.test(r))
    if (rows.length) {
      const cells = rows.map((r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim()))
      out.push(
        '<table><thead><tr>'
        + cells[0].map((c, i) => `<th class="${i ? 'num' : ''}">${inline(c)}</th>`).join('')
        + '</tr></thead><tbody>'
        + cells.slice(1)
          .map((r) => '<tr>' + r.map((c, i) => `<td class="${i ? 'num' : ''}">${inline(c)}</td>`).join('') + '</tr>')
          .join('')
        + '</tbody></table>',
      )
    }
    table = []
  }
  const flushList = (): void => {
    if (!list.length) return
    out.push('<ul>' + list.map((li) => `<li>${inline(li)}</li>`).join('') + '</ul>')
    list = []
  }
  const flushQuote = (): void => {
    if (!quote.length) return
    out.push('<blockquote>' + quote.map((q) => inline(q)).join('<br>') + '</blockquote>')
    quote = []
  }
  const flushAll = (): void => {
    flushTable(); flushList(); flushQuote()
  }

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    if (/^\|.*\|$/.test(line.trim())) { flushList(); flushQuote(); table.push(line.trim()); continue }
    if (/^[-*]\s+/.test(line)) { flushTable(); flushQuote(); list.push(line.replace(/^[-*]\s+/, '')); continue }
    if (/^>\s?/.test(line)) { flushTable(); flushList(); quote.push(line.replace(/^>\s?/, '')); continue }
    flushAll()
    if (!line.trim()) { out.push(''); continue }
    if (/^#### /.test(line)) out.push(`<h4>${inline(line.slice(5))}</h4>`)
    else if (/^### /.test(line)) out.push(`<h3>${inline(line.slice(4))}</h3>`)
    else if (/^## /.test(line)) out.push(`<h2>${inline(line.slice(3))}</h2>`)
    else if (/^# /.test(line)) out.push(`<h1>${inline(line.slice(2))}</h1>`)
    else if (/^---+$/.test(line)) out.push('<hr>')
    else out.push(`<p>${inline(line)}</p>`)
  }
  flushAll()
  return out.join('\n')
}

export function extractHeadings(markdown: string | undefined | null): Heading[] {
  return String(markdown || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .filter((l) => /^## /.test(l))
    .map((l, i) => ({ id: `sec-${i}`, title: l.slice(3).trim() }))
}
