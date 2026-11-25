<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ChatMessage from '@/components/ChatMessage.vue'
import type { ChatMsg } from '@/components/ChatMessage.vue'
import { api, askStream } from '@/api'
import { store, notify } from '@/stores/session'
import {
  activeSession, chat, clearAllSessions, createSession, loadChat, pushMessage,
  removeSession, renameSession, sessionGroups, switchSession, timeText, toggleGroup,
  touchSession, DEFAULT_TITLE,
} from '@/stores/chat'
import { sessionToMarkdown, downloadText } from '@/utils/session-export'
import type { AskPayload } from '@/types'

const route = useRoute()
const router = useRouter()

const input = ref('')
const sending = ref(false)
const streaming = ref(route.query.stream !== '0')
const logEl = ref<HTMLDivElement | null>(null)
const keyword = ref('')
const editingId = ref('')
const editingTitle = ref('')
const confirmId = ref('')

const SAMPLES = [
  '各分公司10月新签合同额排名',
  '近6个月营业收入趋势',
  '危大工程最多的5个项目',
  '营业收入按分公司拆分占比',
  '哪些项目进度滞后',
  '两金压降有什么要求',
]

const WELCOME_CARDS = [
  { title: '经营指标取数', desc: '各分公司10月新签合同额排名 / 近6个月营业收入趋势', q: '各分公司10月新签合同额排名' },
  { title: '制度与口径', desc: '两金压降有什么要求 / 新签合同额的口径是什么', q: '两金压降有什么要求' },
  { title: '项目画像', desc: '哪些项目进度滞后 / 危大工程最多的5个项目', q: '哪些项目进度滞后' },
]

const messages = computed<ChatMsg[]>(() => activeSession.value?.messages ?? [])

/** 按身份分组；搜索时跨组展开，命中为空的分组直接隐藏 */
const groups = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  return sessionGroups.value
    .map((g) => {
      const sessions = k
        ? g.sessions.filter((s) => s.title.toLowerCase().includes(k) ||
            s.messages.some((m) => ((m.text ?? '') + (m.payload?.answer ?? '')).toLowerCase().includes(k)))
        : g.sessions
      return { ...g, sessions, collapsed: k ? false : g.collapsed }
    })
    .filter((g) => g.sessions.length)
})

const hasMessages = computed(() => (activeSession.value?.messages.length ?? 0) > 0)

function exportCurrent(): void {
  const s = activeSession.value
  if (!s || !s.messages.length) {
    notify('当前会话还没有内容')
    return
  }
  const name = (s.title || '会话').replace(/[\\/:*?"<>|]/g, '_')
  downloadText(`${name}.md`, sessionToMarkdown(s))
  notify('已导出 Markdown')
}

function exportOne(id: string): void {
  const s = chat.sessions.find((x) => x.id === id)
  if (!s) return
  const name = (s.title || '会话').replace(/[\\/:*?"<>|]/g, '_')
  downloadText(`${name}.md`, sessionToMarkdown(s))
  notify('已导出 Markdown')
}

function scrollToBottom(): void {
  const go = (): void => {
    if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
  }
  nextTick(() => {
    go()
    requestAnimationFrame(go)
    setTimeout(go, 120)
  })
}

/** 非流式兜底：SSE 不可用时退回一次性接口 */
async function fallback(sid: string, idx: number, question: string): Promise<void> {
  const arr = sessionMessages(sid)
  try {
    const payload = await api.ask(store.userId, question, sid)
    arr[idx] = { role: 'bot', payload }
  } catch (e) {
    arr[idx] = { role: 'bot', error: (e as Error).message }
  }
}

function sessionMessages(id: string): ChatMsg[] {
  return chat.sessions.find((s) => s.id === id)?.messages ?? []
}

async function send(text?: string): Promise<void> {
  const question = (text ?? input.value ?? '').trim()
  if (!question || sending.value) return
  if (!activeSession.value) createSession()
  const sid = chat.activeId
  const arr = sessionMessages(sid)

  input.value = ''
  sending.value = true
  pushMessage(sid, { role: 'user', text: question })
  pushMessage(sid, { role: 'bot', pending: true, stages: [], sqlPreview: '' })
  const idx = arr.length - 1
  const cur = (): ChatMsg => arr[idx]
  scrollToBottom()

  if (!streaming.value) {
    cur().pending = false
    await fallback(sid, idx, question)
    touchSession(sid)
    sending.value = false
    scrollToBottom()
    return
  }

  try {
    await askStream(store.userId, question, sid, {
      onStage: (s) => {
        cur().stages = [...(cur().stages ?? []), s]
        scrollToBottom()
      },
      onSql: (chunk, done) => {
        if (done) return
        cur().sqlPreview = (cur().sqlPreview ?? '') + chunk
        scrollToBottom()
      },
      onResult: (payload: AskPayload) => {
        arr[idx] = { role: 'bot', payload }
        touchSession(sid)
        scrollToBottom()
      },
      onError: (msg) => {
        arr[idx] = { role: 'bot', error: msg }
        touchSession(sid)
      },
    })
  } catch (e) {
    // 老版本后端没有 SSE 端点时自动降级
    await fallback(sid, idx, question)
    touchSession(sid)
    notify('已切换为普通模式：' + (e as Error).message)
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

function startRename(id: string, title: string): void {
  editingId.value = id
  editingTitle.value = title === DEFAULT_TITLE ? '' : title
  nextTick(() => {
    const el = document.querySelector<HTMLInputElement>('.rename-input')
    el?.focus()
    el?.select()
  })
}

function commitRename(): void {
  if (editingId.value) renameSession(editingId.value, editingTitle.value || DEFAULT_TITLE)
  editingId.value = ''
}

function askDelete(id: string): void {
  if (confirmId.value === id) {
    removeSession(id)
    confirmId.value = ''
    notify('已删除会话')
    return
  }
  confirmId.value = id
  setTimeout(() => {
    if (confirmId.value === id) confirmId.value = ''
  }, 2600)
}

function addSession(): void {
  createSession()
  confirmId.value = ''
  keyword.value = ''
  notify('已新建会话')
}

function clearAll(): void {
  if (confirmId.value !== '__all__') {
    confirmId.value = '__all__'
    setTimeout(() => {
      if (confirmId.value === '__all__') confirmId.value = ''
    }, 2600)
    return
  }
  clearAllSessions()
  confirmId.value = ''
  notify('已清空全部会话')
}

onMounted(() => {
  loadChat()
  // ?user=U002 可直接以某个身份开会话（便于演示多身份分组）
  const who = route.query.user
  if (typeof who === 'string' && store.users.some((u) => u.user_id === who)) {
    store.userId = who
  }
  const q = route.query.q
  if (q) {
    // 深链视为一次新对话：避免外部链接把问题塞进别人的既有会话
    createSession()
    send(String(q))
    router.replace({ query: {} })
  } else if (!chat.sessions.length) {
    createSession()
  }
})

watch(() => store.userId, () => {
  if (!activeSession.value) return
  pushMessage(chat.activeId, {
    role: 'bot',
    payload: {
      answer: '身份已切换，之后的问答都按新的数据范围执行。',
      intent: 'chat', latency_ms: 0,
    } as AskPayload,
  })
})
</script>

<template>
  <header class="page-head">
    <div>
      <h1>项目画像智能问答</h1>
      <p class="sub">指标取数 · 项目档案 · 制度口径 · 多轮下钻</p>
    </div>
    <div class="head-tools">
      <label class="switch-stream" title="开启后可以看到 SQL 生成过程">
        <input v-model="streaming" type="checkbox" />
        <span>流式输出</span>
      </label>
      <button class="btn" :disabled="!hasMessages" @click="exportCurrent">导出记录</button>
      <button class="btn" @click="addSession">新建会话</button>
    </div>
  </header>

  <div class="chat-shell">
    <aside class="session-rail">
      <div class="rail-head">
        <div class="rail-title">
          <span>对话记录</span>
          <em>{{ chat.sessions.length }}</em>
        </div>
        <input v-model="keyword" class="rail-search" placeholder="搜索会话…" />
      </div>

      <div class="rail-list">
        <div v-for="g in groups" :key="g.name" class="grp">
          <button class="grp-head" :class="{ current: g.current }" @click="toggleGroup(g.name, !g.collapsed)">
            <span class="chev">{{ g.collapsed ? '▸' : '▾' }}</span>
            <span class="grp-name">{{ g.name }}</span>
            <span class="grp-count">{{ g.sessions.length }}</span>
          </button>

          <template v-if="!g.collapsed">
            <div
              v-for="s in g.sessions"
              :key="s.id"
              class="sess"
              :class="{ active: s.id === chat.activeId, confirm: confirmId === s.id }"
              @click="switchSession(s.id)"
            >
              <template v-if="editingId === s.id">
                <input
                  v-model="editingTitle"
                  class="rename-input"
                  maxlength="40"
                  @click.stop
                  @keyup.enter="commitRename"
                  @keyup.esc="editingId = ''"
                  @blur="commitRename"
                />
              </template>
              <template v-else>
                <span class="t">{{ s.title }}</span>
                <span class="m">
                  <i>{{ timeText(s.updatedAt) }}</i>
                  <i>{{ s.messages.filter((m) => m.role === 'user').length }} 问</i>
                </span>
                <span class="ops" @click.stop>
                  <button title="导出 Markdown" @click="exportOne(s.id)">↓</button>
                  <button title="重命名" @click="startRename(s.id, s.title)">✎</button>
                  <button
                    :title="confirmId === s.id ? '再点一次确认删除' : '删除'"
                    :class="{ danger: confirmId === s.id }"
                    @click="askDelete(s.id)"
                  >{{ confirmId === s.id ? '删?' : '✕' }}</button>
                </span>
              </template>
            </div>
          </template>
        </div>

        <div v-if="!groups.length" class="rail-empty">
          {{ keyword ? '没有匹配的会话' : '还没有会话，点上方「新建会话」' }}
        </div>
      </div>

      <div class="rail-foot">
        <button class="link-btn" :class="{ danger: confirmId === '__all__' }" @click="clearAll">
          {{ confirmId === '__all__' ? '再点一次清空全部' : '清空全部会话' }}
        </button>
        <span class="rail-tip">本地保存 · 刷新不丢</span>
      </div>
    </aside>

    <div class="chat-main">
      <div ref="logEl" class="chat-log">
        <div v-if="!messages.length" class="welcome">
          <h2>问点什么？</h2>
          <p class="sub">支持指标取数、项目档案、制度口径，也能多轮下钻。对话会自动保存在本机。</p>
          <div class="welcome-cards">
            <div v-for="c in WELCOME_CARDS" :key="c.title" class="wcard" @click="send(c.q)">
              <b>{{ c.title }}</b><span>{{ c.desc }}</span>
            </div>
          </div>
        </div>

        <ChatMessage v-for="(m, i) in messages" :key="i" :message="m" @ask="send" />
      </div>

      <div class="composer">
        <div class="chips">
          <button v-for="s in SAMPLES" :key="s" class="chip" @click="send(s)">{{ s }}</button>
        </div>
        <form class="composer-inner" @submit.prevent="send()">
          <input v-model="input" placeholder="问点什么，例如：各分公司10月新签合同额排名" autocomplete="off" />
          <button class="btn primary" type="submit" :disabled="sending">{{ sending ? '思考中…' : '发送' }}</button>
        </form>
        <div class="composer-tip">
          回车发送 · 回答下方可继续追问 · SQL 以 Oracle 11g 写法呈现{{ streaming ? ' · 可看到生成过程' : '' }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-shell { display: flex; gap: 14px; height: calc(100vh - 168px); }

/* ---------- 会话侧栏 ---------- */
.session-rail {
  width: 232px; flex: 0 0 232px; display: flex; flex-direction: column;
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-md); overflow: hidden;
}
.rail-head { padding: 10px 10px 8px; border-bottom: 1px solid var(--line-2); }
.rail-title {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 12px; font-weight: 600; color: var(--ink-2); margin-bottom: 7px;
}
.rail-title em {
  font-style: normal; font-size: 10.5px; color: var(--ink-3);
  background: var(--surface-2); border-radius: 9px; padding: 1px 7px;
}
.rail-search {
  width: 100%; border: 1px solid var(--line); border-radius: 7px;
  padding: 5px 8px; font-size: 11.5px; outline: none; background: var(--surface-2);
}
.rail-search:focus { border-color: #a9c4e6; background: var(--surface); }
.rail-list { flex: 1; overflow-y: auto; padding: 6px; display: flex; flex-direction: column; gap: 4px; }
.grp { display: flex; flex-direction: column; gap: 1px; }
.grp-head {
  display: flex; align-items: center; gap: 6px; width: 100%;
  border: 0; background: transparent; cursor: pointer; padding: 5px 6px;
  border-radius: 6px; font-size: 11.5px; color: var(--ink-3); text-align: left;
}
.grp-head:hover { background: var(--surface-2); }
.grp-head.current { color: var(--brand); font-weight: 600; }
.grp-head .chev { font-size: 9px; width: 9px; }
.grp-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.grp-count { font-size: 10px; color: var(--ink-3); background: var(--surface-2); border-radius: 8px; padding: 0 6px; }
.grp-head.current .grp-count { background: var(--brand-soft); color: var(--brand); }
.sess {
  position: relative; border-radius: 7px; padding: 7px 8px; cursor: pointer;
  border: 1px solid transparent; transition: background .12s;
}
.sess:hover { background: var(--surface-2); }
.sess.active { background: var(--brand-soft); border-color: #d6e4f4; }
.sess.confirm { background: #fdf0ef; border-color: #f3d3d0; }
.sess .t {
  display: block; font-size: 12.5px; color: var(--ink);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 34px;
}
.sess .m { display: flex; gap: 7px; margin-top: 2px; font-size: 10.5px; color: var(--ink-3); }
.sess .m i { font-style: normal; }
.sess .ops { position: absolute; right: 4px; top: 6px; display: none; gap: 1px; }
.sess:hover .ops { display: flex; }
.sess .ops button {
  border: 0; background: var(--surface); color: var(--ink-3); cursor: pointer;
  width: 17px; height: 17px; border-radius: 4px; font-size: 10px; line-height: 1;
  display: flex; align-items: center; justify-content: center;
}
.sess .ops button:hover { background: #e9eef5; color: var(--ink); }
.sess .ops button.danger { background: #f6d9d6; color: #b3261e; }
.rename-input {
  width: 100%; border: 1px solid var(--brand); border-radius: 5px;
  padding: 3px 6px; font-size: 12px; outline: none;
}
.rail-empty { font-size: 11.5px; color: var(--ink-3); text-align: center; padding: 18px 8px; }
.rail-foot {
  padding: 7px 10px; border-top: 1px solid var(--line-2);
  display: flex; align-items: center; justify-content: space-between; gap: 6px;
}
.link-btn {
  border: 0; background: transparent; color: var(--ink-3); font-size: 11px;
  cursor: pointer; padding: 2px 0;
}
.link-btn:hover { color: var(--ink-2); }
.link-btn.danger { color: #b3261e; font-weight: 600; }
.rail-tip { font-size: 10px; color: var(--ink-3); }

/* ---------- 对话区 ---------- */
.chat-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.chat-log { flex: 1; overflow-y: auto; padding: 4px 2px 8px; display: flex; flex-direction: column; gap: 16px; }
.welcome { max-width: 720px; margin: 24px auto 0; text-align: center; }
.welcome h2 { font-size: 19px; margin-bottom: 6px; }
.welcome .sub { margin-bottom: 18px; }
.welcome-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; text-align: left; }
.wcard {
  border: 1px solid var(--line); border-radius: var(--r-md); padding: 13px 14px;
  background: var(--surface); cursor: pointer; transition: border-color .14s;
}
.wcard:hover { border-color: #c6d5e8; }
.wcard b { display: block; font-size: 13px; margin-bottom: 3px; }
.wcard span { font-size: 11.5px; color: var(--ink-3); line-height: 1.5; }
.composer { padding-top: 10px; }
.chips { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 9px; }
.chip {
  font-size: 11.5px; padding: 4px 10px; border-radius: 20px;
  background: var(--surface); border: 1px solid var(--line); color: var(--ink-2); cursor: pointer;
}
.chip:hover { background: var(--brand-soft); border-color: #cddff3; color: var(--brand); }
.composer-inner { display: flex; gap: 9px; }
.composer-inner input {
  flex: 1; border: 1px solid var(--line); background: var(--surface);
  border-radius: var(--r-md); padding: 11px 14px; font-size: 13.5px; outline: none;
  transition: border-color .14s, box-shadow .14s;
}
.composer-inner input:focus { border-color: #a9c4e6; box-shadow: 0 0 0 3px rgba(31,95,169,.07); }
.composer-tip { margin-top: 7px; font-size: 11px; color: var(--ink-3); }
.switch-stream { display: flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--ink-2); }
.switch-stream input { accent-color: var(--brand); }

@media (max-width: 1080px) {
  .session-rail { display: none; }
  .welcome-cards { grid-template-columns: 1fr; }
}
</style>
