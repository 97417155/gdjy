<script setup lang="ts">
import { computed, ref } from 'vue'
import EChart from '@/components/EChart.vue'
import { renderMarkdown } from '@/utils/markdown'
import { intentLabel } from '@/utils/format'
import { optionFromSpec } from '@/utils/charts'
import type { AskPayload, StageEvent } from '@/types'

export interface ChatMsg {
  role: 'user' | 'bot'
  text?: string
  pending?: boolean
  stages?: StageEvent[]
  sqlPreview?: string
  payload?: AskPayload
  error?: string
}

const props = defineProps<{ message: ChatMsg }>()
const emit = defineEmits<{ (e: 'ask', question: string): void }>()

const showSql = ref(false)
const copied = ref(false)

const payload = computed<AskPayload | null>(() => props.message.payload ?? null)
const html = computed(() => (payload.value ? renderMarkdown(payload.value.answer) : ''))
const chartOption = computed(() => (payload.value?.chart ? optionFromSpec(payload.value.chart) : null))

async function copySql(): Promise<void> {
  const sql = payload.value?.sql
  if (!sql) return
  try {
    await navigator.clipboard.writeText(sql)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    copied.value = false
  }
}
</script>

<template>
  <div class="msg" :class="message.role">
    <div class="av">{{ message.role === 'user' ? '我' : 'AI' }}</div>
    <div class="bubble">
      <p v-if="message.role === 'user'">{{ message.text }}</p>

      <template v-else-if="message.pending">
        <div class="stages">
          <div v-for="(s, i) in message.stages || []" :key="i" class="stage">
            <span class="dot" :class="{ done: i < (message.stages?.length || 0) - 1 }"></span>
            <span class="stage-text">{{ s.text }}</span>
          </div>
          <div v-if="!message.stages || !message.stages.length" class="stage">
            <span class="dot"></span><span class="stage-text">正在理解问题…</span>
          </div>
        </div>
        <pre v-if="message.sqlPreview" class="typing-sql">{{ message.sqlPreview }}<span class="caret"></span></pre>
      </template>

      <p v-else-if="message.error" class="err">{{ message.error }}</p>

      <template v-else-if="payload">
        <div class="meta-tags">
          <span class="tag brand">{{ intentLabel(payload.intent) }}</span>
          <span class="tag">{{ payload.latency_ms }} ms</span>
          <span v-if="payload.degraded" class="tag warn">已降级</span>
          <span v-if="payload.repair?.status === 'repaired'" class="tag warn">
            自动修复 ×{{ payload.repair.attempts.length }}
          </span>
          <span v-if="payload.llm_used" class="tag ok">模型生成</span>
        </div>

        <div class="md" v-html="html"></div>

        <div v-if="chartOption" class="chart-wrap">
          <EChart :option="chartOption" height="220px" />
        </div>

        <p v-if="payload.explain" class="sub hint">理解：{{ payload.explain }}</p>
        <p v-if="payload.sources?.length" class="sub hint">
          引用：{{ payload.sources.map((s) => s.title).join(' · ') }}
        </p>

        <div v-if="payload.sql" class="sql-head">
          <span class="sql-toggle" @click="showSql = !showSql">
            {{ showSql ? '▾' : '▸' }} 查看 Oracle 11g SQL
          </span>
          <button class="mini" @click="copySql">{{ copied ? '已复制' : '复制' }}</button>
        </div>
        <pre v-if="payload.sql && showSql">{{ payload.sql }}</pre>

        <div v-if="payload.related?.length" class="follow-up">
          <button v-for="q in payload.related" :key="q" class="chip" @click="emit('ask', q)">{{ q }}</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.msg { display: flex; gap: 10px; }
.msg .av {
  width: 28px; height: 28px; border-radius: 8px; flex: 0 0 28px;
  display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600;
}
.msg.bot .av { background: var(--brand-soft); color: var(--brand); }
.msg.user { flex-direction: row-reverse; }
.msg.user .av { background: #eef1f5; color: var(--ink-2); }
.bubble {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md);
  padding: 12px 15px; max-width: 860px; min-width: 80px;
}
@media (min-width: 900px) { .msg.bot .bubble { min-width: 560px; } }
.msg.user .bubble { background: var(--brand); border-color: var(--brand); color: #fff; max-width: 620px; }
.meta-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.hint { margin-top: 9px; }
.chart-wrap { margin-top: 6px; }
.err { color: var(--bad); }

.stages { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.stage { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-2); }
.stage .dot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--brand);
  box-shadow: 0 0 0 3px rgba(31, 95, 169, .12); animation: pulse 1.2s infinite;
}
.stage .dot.done { background: var(--down); box-shadow: none; animation: none; }
@keyframes pulse { 0%, 100% { opacity: .35; } 50% { opacity: 1; } }
.typing-sql {
  margin: 0; padding: 9px 11px; background: #f7f9fb; border: 1px solid var(--line-2);
  border-radius: var(--r-sm); font-size: 11.5px; line-height: 1.55; color: #24313f;
  font-family: "SFMono-Regular", Consolas, monospace; white-space: pre-wrap; word-break: break-word;
  max-height: 168px; overflow: auto;
}
.caret {
  display: inline-block; width: 6px; height: 12px; background: var(--brand);
  margin-left: 2px; vertical-align: -2px; animation: blink 1s steps(2) infinite;
}
@keyframes blink { 50% { opacity: 0; } }

.sql-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--line);
}
.sql-toggle { font-size: 11.5px; color: var(--brand); cursor: pointer; user-select: none; }
.mini {
  font-size: 11px; padding: 1px 8px; border-radius: 12px; border: 1px solid var(--line);
  background: var(--surface); color: var(--ink-2); cursor: pointer;
}
.mini:hover { border-color: #c6d5e8; color: var(--brand); }
pre {
  margin: 8px 0 0; padding: 10px 12px; background: #f7f9fb; border: 1px solid var(--line-2);
  border-radius: var(--r-sm); overflow-x: auto; font-size: 11.5px; line-height: 1.6;
  font-family: "SFMono-Regular", Consolas, monospace; color: #24313f;
  white-space: pre-wrap; word-break: break-word;
}
.follow-up { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 11px; padding-top: 10px; border-top: 1px dashed var(--line); }
.chip {
  font-size: 11.5px; padding: 4px 10px; border-radius: 20px;
  background: var(--surface-2); border: 1px solid var(--line); color: var(--ink-2); cursor: pointer;
  transition: .14s;
}
.chip:hover { background: var(--brand-soft); border-color: #cddff3; color: var(--brand); }

:deep(.md h1) { font-size: 16px; margin: 2px 0 8px; }
:deep(.md h2) { font-size: 14.5px; margin: 14px 0 6px; color: var(--brand); }
:deep(.md p) { margin: 0 0 8px; }
:deep(.md p:last-child) { margin-bottom: 0; }
:deep(.md ul) { margin: 4px 0 10px; padding-left: 18px; }
:deep(.md table) { margin: 10px 0 4px; }
:deep(.md em) { color: var(--ink-3); font-style: normal; font-size: 12px; }
:deep(.md code) { background: var(--surface-2); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
</style>
