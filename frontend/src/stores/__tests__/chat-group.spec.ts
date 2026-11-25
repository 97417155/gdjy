import { beforeEach, describe, expect, it } from 'vitest'
import { chat, createSession, pushMessage, sessionGroups, toggleGroup } from '@/stores/chat'
import { store } from '@/stores/session'
import type { User } from '@/types'

const U1: User = {
  user_id: 'U001', staff_id: 'S1', name: '陈建国', role: '院长',
  org_id: 'O100', org_name: '院本部', scope_type: 'ALL', desc: '',
}
const U2: User = {
  user_id: 'U002', staff_id: 'S2', name: '林志强', role: '分公司负责人',
  org_id: 'O103', org_name: '新能源分公司', scope_type: 'ORG', desc: '',
}

function makeSession(userId: string, name: string, question: string): void {
  store.userId = userId
  createSession()
  pushMessage(chat.activeId, { role: 'user', text: question })
}

describe('会话按身份分组', () => {
  beforeEach(() => {
    chat.sessions = []
    chat.activeId = ''
    store.users = [U1, U2]
    store.userId = 'U001'
  })

  it('同身份会话归到一组，不同身份分开', () => {
    makeSession('U001', '陈建国', '院长问题一')
    makeSession('U001', '陈建国', '院长问题二')
    makeSession('U002', '林志强', '分公司问题')
    const groups = sessionGroups.value
    expect(groups).toHaveLength(2)
    const dean = groups.find((g) => g.name === '陈建国')
    const branch = groups.find((g) => g.name === '林志强')
    expect(dean?.sessions).toHaveLength(2)
    expect(branch?.sessions).toHaveLength(1)
  })

  it('当前身份排在最前且默认展开，其他身份默认收起', () => {
    makeSession('U001', '陈建国', '院长问题')
    makeSession('U002', '林志强', '分公司问题')
    store.userId = 'U001'
    const groups = sessionGroups.value
    expect(groups[0].name).toBe('陈建国')
    expect(groups[0].current).toBe(true)
    expect(groups[0].collapsed).toBe(false)
    expect(groups.find((g) => g.name === '林志强')?.collapsed).toBe(true)
  })

  it('切换身份后展开状态随之改变', () => {
    makeSession('U001', '陈建国', '院长问题')
    makeSession('U002', '林志强', '分公司问题')
    store.userId = 'U002'
    const groups = sessionGroups.value
    expect(groups[0].name).toBe('林志强')
    expect(groups[0].collapsed).toBe(false)
  })

  it('手动展开/收起优先于默认规则', () => {
    makeSession('U001', '陈建国', '院长问题')
    makeSession('U002', '林志强', '分公司问题')
    store.userId = 'U001'
    toggleGroup('林志强')
    expect(sessionGroups.value.find((g) => g.name === '林志强')?.collapsed).toBe(false)
    toggleGroup('陈建国', true)
    expect(sessionGroups.value.find((g) => g.name === '陈建国')?.collapsed).toBe(true)
  })

  it('组内按最近更新排序', () => {
    makeSession('U001', '陈建国', '问题一')
    const first = chat.activeId
    makeSession('U001', '陈建国', '问题二')
    const second = chat.activeId
    // 同一毫秒内创建时时间戳相同，这里显式把较早的会话标记为"刚更新过"
    const target = chat.sessions.find((s) => s.id === first)
    if (target) target.updatedAt = Date.now() + 5000
    const group = sessionGroups.value[0]
    expect(group.sessions[0].id).toBe(first)
    expect(group.sessions[1].id).toBe(second)
  })
})
