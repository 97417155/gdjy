import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_TITLE, activeSession, chat, clearAllSessions, createSession, loadChat,
  pushMessage, removeSession, renameSession, switchSession, timeText,
} from '@/stores/chat'
import { store } from '@/stores/session'

const KEY = 'gdjy.chat.sessions.v1'

describe('chat store 多会话', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    chat.sessions = []
    chat.activeId = ''
    store.userId = 'U001'
    store.users = [
      { user_id: 'U001', staff_id: 'S1', name: '陈建国', role: '院长', org_id: 'O100', org_name: '院本部', scope_type: 'ALL', desc: '' },
    ]
  })

  it('新建会话并成为当前会话', () => {
    const s = createSession()
    expect(chat.sessions).toHaveLength(1)
    expect(chat.activeId).toBe(s.id)
    expect(activeSession.value?.title).toBe(DEFAULT_TITLE)
  })

  it('首条提问自动成为会话标题', () => {
    createSession()
    pushMessage(chat.activeId, { role: 'user', text: '各分公司10月新签合同额排名' })
    expect(activeSession.value?.title).toBe('各分公司10月新签合同额排名')
    // 后续提问不再改标题
    pushMessage(chat.activeId, { role: 'user', text: '再看环比' })
    expect(activeSession.value?.title).toBe('各分公司10月新签合同额排名')
  })

  it('落盘后能恢复会话与当前会话', () => {
    const s = createSession()
    pushMessage(s.id, { role: 'user', text: '近6个月营业收入趋势' })
    pushMessage(s.id, { role: 'bot', payload: { answer: '趋势如下', intent: 'data', latency_ms: 8 } })
    vi.advanceTimersByTime(300)

    expect(localStorage.getItem(KEY)).toBeTruthy()
    chat.sessions = []
    chat.activeId = ''
    loadChat()

    expect(chat.sessions).toHaveLength(1)
    expect(chat.activeId).toBe(s.id)
    expect(activeSession.value?.messages).toHaveLength(2)
    expect(activeSession.value?.messages[1].payload?.answer).toBe('趋势如下')
  })

  it('生成中的消息不写入本地存储', () => {
    const s = createSession()
    pushMessage(s.id, { role: 'user', text: '问一句' })
    pushMessage(s.id, { role: 'bot', pending: true, stages: [{ name: 'router', text: '意图识别' }] })
    vi.advanceTimersByTime(300)

    const raw = JSON.parse(localStorage.getItem(KEY) as string)
    expect(raw.sessions[0].messages).toHaveLength(1)
    expect(raw.sessions[0].messages[0].role).toBe('user')
  })

  it('会话之间互不干扰，切换回来内容还在', () => {
    const a = createSession()
    pushMessage(a.id, { role: 'user', text: '会话A的问题' })
    const b = createSession()
    pushMessage(b.id, { role: 'user', text: '会话B的问题' })

    switchSession(a.id)
    expect(activeSession.value?.messages[0].text).toBe('会话A的问题')
    switchSession(b.id)
    expect(activeSession.value?.messages[0].text).toBe('会话B的问题')
  })

  it('删除当前会话后自动落到下一个', () => {
    const a = createSession()
    const b = createSession()
    expect(chat.activeId).toBe(b.id)
    removeSession(b.id)
    expect(chat.activeId).toBe(a.id)
    removeSession(a.id)
    expect(chat.sessions).toHaveLength(1)   // 删空后自动补一个空会话
  })

  it('重命名生效且空标题回退默认名', () => {
    const s = createSession()
    renameSession(s.id, '  月度经营复盘  ')
    expect(activeSession.value?.title).toBe('月度经营复盘')
    renameSession(s.id, '   ')
    expect(activeSession.value?.title).toBe(DEFAULT_TITLE)
  })

  it('会话数超上限时淘汰最久未更新的（保留当前）', () => {
    const ids: string[] = []
    for (let i = 0; i < 42; i += 1) {
      const s = createSession()
      pushMessage(s.id, { role: 'user', text: `问题${i}` })
      ids.push(s.id)
    }
    expect(chat.sessions.length).toBeLessThanOrEqual(40)
    expect(chat.sessions.some((s) => s.id === chat.activeId)).toBe(true)
  })

  it('清空全部后保留一个空会话', () => {
    createSession()
    pushMessage(chat.activeId, { role: 'user', text: 'x' })
    clearAllSessions()
    expect(chat.sessions).toHaveLength(1)
    expect(chat.sessions[0].messages).toHaveLength(0)
  })

  it('时间展示：当天显示时分，其余显示日期', () => {
    const now = new Date(2026, 10, 23, 9, 5).getTime()
    vi.setSystemTime(now)
    expect(timeText(now)).toBe('09:05')
    expect(timeText(new Date(2026, 10, 22, 18, 0).getTime())).toBe('昨天')
    expect(timeText(new Date(2026, 9, 8, 10, 0).getTime())).toBe('10/8')
    expect(timeText(new Date(2025, 9, 8, 10, 0).getTime())).toBe('2025/10/8')
  })
})
