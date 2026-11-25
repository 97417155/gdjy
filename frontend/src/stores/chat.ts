/** 多会话管理：会话列表、切换、重命名、删除，本地持久化（刷新不丢）。 */
import { computed, reactive, watch } from 'vue'
import type { ChatMsg } from '@/components/ChatMessage.vue'
import { store } from '@/stores/session'

export interface ChatSession {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  userId: string
  userName: string
  messages: ChatMsg[]
}

const KEY = 'gdjy.chat.sessions.v1'
const ACTIVE_KEY = 'gdjy.chat.active.v1'
const MAX_SESSIONS = 40
const MAX_MSG_PER_SESSION = 60
export const DEFAULT_TITLE = '新会话'

export const chat = reactive<{ sessions: ChatSession[]; activeId: string }>({
  sessions: [],
  activeId: '',
})

export const activeSession = computed(
  () => chat.sessions.find((s) => s.id === chat.activeId) ?? null,
)

/** 分组折叠状态：默认只展开当前身份，其他身份收起，避免演示时列表混杂 */
export const collapsedGroups = reactive<Record<string, boolean>>({})

export interface SessionGroup {
  name: string
  sessions: ChatSession[]
  collapsed: boolean
  current: boolean
}

export function currentUserName(): string {
  return (store.users.find((u) => u.user_id === store.userId)?.name as string) ?? ''
}

export const sessionGroups = computed<SessionGroup[]>(() => {
  const cur = currentUserName()
  const map = new Map<string, ChatSession[]>()
  for (const s of chat.sessions) {
    const key = s.userName || '未标注身份'
    const list = map.get(key)
    if (list) list.push(s)
    else map.set(key, [s])
  }
  const groups: SessionGroup[] = []
  for (const [name, list] of map) {
    list.sort((a, b) => b.updatedAt - a.updatedAt)
    groups.push({
      name,
      sessions: list,
      collapsed: collapsedGroups[name] ?? name !== cur,
      current: name === cur,
    })
  }
  groups.sort((a, b) => {
    if (a.current !== b.current) return a.current ? -1 : 1
    return (b.sessions[0]?.updatedAt ?? 0) - (a.sessions[0]?.updatedAt ?? 0)
  })
  return groups
})

export function toggleGroup(name: string, collapsed?: boolean): void {
  const cur = sessionGroups.value.find((g) => g.name === name)?.collapsed ?? false
  collapsedGroups[name] = collapsed ?? !cur
}

function uid(): string {
  return 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
}

/** 落盘前剔除临时态：生成中、阶段日志、SQL 预览都没必要存 */
function serialize(sessions: ChatSession[]): string {
  const clean = sessions.map((s) => ({
    ...s,
    messages: s.messages
      .filter((m) => !m.pending)
      .map((m) => ({ role: m.role, text: m.text, payload: m.payload, error: m.error })),
  }))
  return JSON.stringify({ sessions: clean, activeId: chat.activeId })
}

let saveTimer: ReturnType<typeof setTimeout> | undefined

export function persistChat(): void {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(KEY, serialize(chat.sessions))
      localStorage.setItem(ACTIVE_KEY, chat.activeId)
    } catch {
      /* 隐私模式或超配额时静默降级为仅内存 */
    }
  }, 200)
}

export function loadChat(): void {
  if (chat.sessions.length) return
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const data = JSON.parse(raw) as { sessions?: ChatSession[]; activeId?: string }
      chat.sessions = (data.sessions ?? []).filter((s) => Array.isArray(s.messages))
      chat.activeId = data.activeId ?? chat.sessions[0]?.id ?? ''
    }
  } catch {
    chat.sessions = []
  }
  if (chat.sessions.length && !chat.sessions.some((s) => s.id === chat.activeId)) {
    chat.activeId = chat.sessions[0].id
  }
}

export function createSession(): ChatSession {
  const s: ChatSession = {
    id: uid(),
    title: DEFAULT_TITLE,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    userId: store.userId,
    userName: (store.users.find((u) => u.user_id === store.userId)?.name as string) ?? '',
    messages: [],
  }
  chat.sessions.unshift(s)
  chat.activeId = s.id
  // 超出上限时淘汰最久未更新的会话（保留当前会话）
  if (chat.sessions.length > MAX_SESSIONS) {
    const rest = chat.sessions.filter((x) => x.id !== chat.activeId)
    rest.sort((a, b) => b.updatedAt - a.updatedAt)
    const keep = new Set(rest.slice(0, MAX_SESSIONS - 1).map((x) => x.id))
    chat.sessions = chat.sessions.filter((x) => x.id === chat.activeId || keep.has(x.id))
  }
  persistChat()
  return s
}

export function switchSession(id: string): void {
  if (chat.sessions.some((s) => s.id === id)) {
    chat.activeId = id
    persistChat()
  }
}

export function removeSession(id: string): void {
  const idx = chat.sessions.findIndex((s) => s.id === id)
  if (idx < 0) return
  chat.sessions.splice(idx, 1)
  if (chat.activeId === id) {
    chat.activeId = chat.sessions[0]?.id ?? ''
    if (!chat.activeId) createSession()
  }
  persistChat()
}

export function renameSession(id: string, title: string): void {
  const s = chat.sessions.find((x) => x.id === id)
  if (!s) return
  const t = title.trim()
  s.title = t ? t.slice(0, 40) : DEFAULT_TITLE
  persistChat()
}

export function clearAllSessions(): void {
  chat.sessions = []
  createSession()
}

/** 新消息写入会话：首条提问自动成为标题，超出条数上限时丢弃最早的消息 */
export function pushMessage(id: string, msg: ChatMsg): void {
  const s = chat.sessions.find((x) => x.id === id)
  if (!s) return
  s.messages.push(msg)
  if (s.messages.length > MAX_MSG_PER_SESSION) {
    s.messages.splice(0, s.messages.length - MAX_MSG_PER_SESSION)
  }
  if (msg.role === 'user' && s.title === DEFAULT_TITLE) {
    s.title = (msg.text ?? DEFAULT_TITLE).slice(0, 24)
  }
  s.updatedAt = Date.now()
  if (!s.userId && store.userId) {
    s.userId = store.userId
    s.userName = (store.users.find((u) => u.user_id === store.userId)?.name as string) ?? ''
  }
  persistChat()
}

/** 会话内消息发生替换（如生成完成、出错）时刷新时间戳 */
export function touchSession(id: string): void {
  const s = chat.sessions.find((x) => x.id === id)
  if (s) s.updatedAt = Date.now()
  persistChat()
}

export function timeText(ts: number): string {
  const d = new Date(ts)
  const now = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return `${pad(d.getHours())}:${pad(d.getMinutes())}`
  const yesterday = new Date(now.getTime() - 86400000)
  if (d.toDateString() === yesterday.toDateString()) return '昨天'
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}/${d.getDate()}`
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}

watch(() => chat.activeId, persistChat)
