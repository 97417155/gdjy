import { describe, expect, it } from 'vitest'
import { sessionToMarkdown } from '@/utils/session-export'
import type { ChatSession } from '@/stores/chat'

const base: ChatSession = {
  id: 's1',
  title: '各分公司10月新签合同额排名',
  createdAt: new Date(2026, 10, 25, 10, 30).getTime(),
  updatedAt: new Date(2026, 10, 25, 10, 32).getTime(),
  userId: 'U001',
  userName: '陈建国',
  messages: [
    { role: 'user', text: '各分公司10月新签合同额排名' },
    {
      role: 'bot',
      payload: {
        answer: '**新能源分公司** 居首，新签 78,515.00 万元。',
        intent: 'data',
        latency_ms: 12,
        explain: '指标：新签合同额；维度：分公司',
        sql: 'SELECT O.ORG_NAME FROM DUAL',
        related: ['新签合同额按工程类型看'],
      },
    },
  ],
}

describe('sessionToMarkdown', () => {
  it('导出标题、身份与时间信息', () => {
    const md = sessionToMarkdown(base)
    expect(md).toContain('# 各分公司10月新签合同额排名')
    expect(md).toContain('身份：陈建国')
    expect(md).toContain('提问 1 次')
  })

  it('问题与回答按轮次编号，SQL 独立代码块', () => {
    const md = sessionToMarkdown(base)
    expect(md).toContain('## 问 1')
    expect(md).toContain('新能源分公司')
    expect(md).toContain('自然语言取数 · 12 ms')
    expect(md).toContain('```sql')
    expect(md).toContain('SELECT O.ORG_NAME FROM DUAL')
    expect(md).toContain('_理解：指标：新签合同额；维度：分公司_')
    expect(md).toContain('可继续追问')
  })

  it('错误消息以引用块记录，不中断导出', () => {
    const md = sessionToMarkdown({
      ...base,
      messages: [
        { role: 'user', text: '毛利率是多少' },
        { role: 'bot', error: '查询超时' },
        { role: 'user', text: '再看一次' },
      ],
    })
    expect(md).toContain('**答**（失败）')
    expect(md).toContain('> 查询超时')
    expect(md).toContain('## 问 2')
  })

  it('生成中的空消息不会写进记录', () => {
    const md = sessionToMarkdown({
      ...base,
      messages: [{ role: 'user', text: '在吗' }, { role: 'bot', pending: true }],
    })
    expect(md).toContain('## 问 1')
    expect(md).not.toContain('**答**')
  })
})
