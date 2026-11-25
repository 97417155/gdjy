import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatMessage from '@/components/ChatMessage.vue'
import type { ChatMsg } from '@/components/ChatMessage.vue'
import type { AskPayload } from '@/types'

const payload: AskPayload = {
  answer: '**2026年10月**，按分公司看 **新签合同额**：新能源分公司居首。',
  intent: 'data',
  latency_ms: 12,
  sql: 'SELECT 1 FROM DUAL',
  related: ['新签合同额按工程类型看', '近6个月新签合同额趋势'],
  explain: '指标：新签合同额；维度：分公司',
  repair: { status: 'ok', attempts: [] },
}

const mountMsg = (message: ChatMsg) =>
  mount(ChatMessage, {
    props: { message },
    global: { stubs: { EChart: true } },
  })

describe('ChatMessage', () => {
  it('渲染回答正文与意图标签', () => {
    const w = mountMsg({ role: 'bot', payload })
    expect(w.text()).toContain('新能源分公司居首')
    expect(w.find('.tag.brand').text()).toBe('取数')
    expect(w.html()).toContain('<strong>新签合同额</strong>')
  })

  it('生成中展示阶段与 SQL 逐字内容', () => {
    const w = mountMsg({
      role: 'bot',
      pending: true,
      stages: [{ name: 'router', text: '意图识别：自然语言取数' }],
      sqlPreview: 'SELECT O.ORG_NAME',
    })
    expect(w.text()).toContain('意图识别：自然语言取数')
    expect(w.find('.typing-sql').text()).toContain('SELECT O.ORG_NAME')
    expect(w.find('.meta-tags').exists()).toBe(false)
  })

  it('点击追问推荐会向父组件抛出 ask 事件', async () => {
    const w = mountMsg({ role: 'bot', payload })
    const chips = w.findAll('.chip')
    expect(chips).toHaveLength(2)
    await chips[1].trigger('click')
    expect(w.emitted('ask')?.[0]).toEqual(['近6个月新签合同额趋势'])
  })

  it('SQL 默认折叠，点击后展开', async () => {
    const w = mountMsg({ role: 'bot', payload })
    expect(w.find('pre').exists()).toBe(false)
    await w.find('.sql-toggle').trigger('click')
    expect(w.find('pre').text()).toContain('SELECT 1 FROM DUAL')
  })

  it('修复过的查询显示自动修复标签', () => {
    const w = mountMsg({
      role: 'bot',
      payload: { ...payload, repair: { status: 'repaired', attempts: [{ round: 1, sql: '', error: 'x', fix: 'y' }] } },
    })
    expect(w.text()).toContain('自动修复 ×1')
  })

  it('错误状态展示错误信息', () => {
    const w = mountMsg({ role: 'bot', error: '问题不能为空' })
    expect(w.find('.err').text()).toBe('问题不能为空')
  })
})
