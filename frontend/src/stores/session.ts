import { computed, reactive } from 'vue'
import { api } from '@/api'
import type { DashboardData, MetaInfo, Period, User } from '@/types'

interface SessionState {
  ready: boolean
  users: User[]
  userId: string
  meta: MetaInfo | null
  periods: Period[]
  period: string
  scope: string
  sessionId: string
  toast: { text: string; visible: boolean }
}

export const store = reactive<SessionState>({
  ready: false,
  users: [],
  userId: '',
  meta: null,
  periods: [],
  period: '',
  scope: '',
  sessionId: 'w' + Date.now(),
  toast: { text: '', visible: false },
})

export const currentUser = computed<User | Record<string, never>>(
  () => store.users.find((u) => u.user_id === store.userId) || {},
)

let toastTimer: ReturnType<typeof setTimeout> | undefined

export function notify(text: string): void {
  store.toast.text = text
  store.toast.visible = true
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (store.toast.visible = false), 2400)
}

/** 某月最后一个自然日，避免用 Date 转 UTC 导致偏一天 */
export function periodEnd(ym: string): string {
  const y = Number(ym.slice(0, 4))
  const m = Number(ym.slice(5, 7))
  const last = new Date(y, m, 0).getDate()
  return `${ym}-${String(last).padStart(2, '0')}`
}

export async function bootstrap(): Promise<void> {
  if (store.ready) return
  const [meta, periods] = await Promise.all([api.meta(), api.periods()])
  store.meta = meta
  store.users = meta.users
  store.userId = meta.users[0]?.user_id ?? ''
  store.periods = periods
  store.period = periods[0]?.value ?? '2026-10'
  await refreshScope()
  store.ready = true
}

export async function refreshScope(): Promise<DashboardData> {
  const d = await api.dashboard(store.userId, `${store.period}-01`, periodEnd(store.period))
  store.scope = d.scope
  return d
}

export function setUser(id: string): void {
  store.userId = id
}

export function newSession(): void {
  store.sessionId = 'w' + Date.now()
}
