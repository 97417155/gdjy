<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/api'
import type { TableDetail } from '@/types'
import { fmtInt } from '@/utils/format'

const props = defineProps<{ modelValue: boolean; table: string }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'select', table: string): void
}>()

const detail = ref<TableDetail | null>(null)
const loading = ref(false)
const error = ref('')
const tab = ref<'columns' | 'samples'>('columns')

const title = computed(() => detail.value?.table || props.table)
const sampleColumns = computed(() => (detail.value?.samples?.[0] ? Object.keys(detail.value.samples[0]) : []))

function close(): void {
  emit('update:modelValue', false)
}

async function load(name: string): Promise<void> {
  if (!name) return
  loading.value = true
  error.value = ''
  detail.value = null
  try {
    detail.value = await api.table(name)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.modelValue, props.table],
  ([open, name]) => {
    if (open && name) {
      tab.value = 'columns'
      load(String(name))
    }
  },
  { immediate: true },
)

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') close()
}
watch(() => props.modelValue, (open) => {
  if (open) window.addEventListener('keydown', onKey)
  else window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="modelValue" class="overlay" @click.self="close">
        <aside class="drawer">
          <header class="drawer-head">
            <div>
              <div class="eyebrow">数据表结构</div>
              <h2>{{ title }}</h2>
              <p class="sub" v-if="detail">
                {{ fmtInt(detail.rows) }} 行 · {{ detail.columns.length }} 列
              </p>
            </div>
            <button class="close" @click="close" aria-label="关闭">✕</button>
          </header>

          <div v-if="loading" class="drawer-body center">正在读取表结构…</div>
          <div v-else-if="error" class="drawer-body center err">{{ error }}</div>

          <div v-else-if="detail" class="drawer-body">
            <div class="tabs">
              <button class="tab" :class="{ active: tab === 'columns' }" @click="tab = 'columns'">
                列定义 {{ detail.columns.length }}
              </button>
              <button class="tab" :class="{ active: tab === 'samples' }" @click="tab = 'samples'">
                样例数据
              </button>
            </div>

            <div v-if="tab === 'columns'" class="col-list">
              <div v-for="c in detail.columns" :key="c.name" class="col-row">
                <code class="c-name">{{ c.name }}</code>
                <span class="c-type">{{ c.type }}</span>
                <span v-if="c.pk" class="tag brand">PK</span>
              </div>
            </div>

            <div v-else class="sample-wrap">
              <div v-if="!detail.samples.length" class="center sub">该表暂无数据</div>
              <table v-else class="sample">
                <thead>
                  <tr><th v-for="c in sampleColumns" :key="c">{{ c }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(row, i) in detail.samples" :key="i">
                    <td v-for="c in sampleColumns" :key="c">{{ row[c] ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <section class="block">
              <h3>相关指标</h3>
              <div v-if="detail.related_kpis.length" class="chips">
                <span v-for="k in detail.related_kpis" :key="k.kpi" class="chip">
                  {{ k.name }}<em>{{ k.unit }}</em>
                </span>
              </div>
              <p v-else class="sub">
                该表为派生宽表 / 快照表，承载多个指标的汇总值，不直接出现在指标取数 SQL 中。
              </p>
            </section>

            <section class="block">
              <h3>可能关联的表</h3>
              <div class="chips">
                <button v-for="t in detail.related_tables" :key="t.table" class="chip link"
                        @click="emit('select', t.table)">
                  {{ t.table }}<em>{{ t.shared.join(' / ') }}</em>
                </button>
              </div>
              <p v-if="!detail.related_tables.length" class="sub">未发现同名列，可能是独立维表。</p>
            </section>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: rgba(20, 28, 38, .28);
  display: flex; justify-content: flex-end; z-index: 80;
}
.drawer {
  width: min(560px, 94vw); height: 100%; background: var(--surface);
  border-left: 1px solid var(--line); display: flex; flex-direction: column;
}
.drawer-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 18px 20px 14px; border-bottom: 1px solid var(--line-2);
}
.eyebrow { font-size: 11px; color: var(--ink-3); letter-spacing: .4px; }
.drawer-head h2 { font-size: 17px; margin: 2px 0 2px; font-family: Consolas, monospace; }
.close {
  border: 1px solid var(--line); background: var(--surface); color: var(--ink-2);
  width: 26px; height: 26px; border-radius: 8px; cursor: pointer; line-height: 1;
}
.close:hover { border-color: #c6d5e8; color: var(--ink); }
.drawer-body { padding: 14px 20px 24px; overflow-y: auto; }
.center { padding: 40px 0; text-align: center; color: var(--ink-3); }
.err { color: var(--bad); }

.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); margin-bottom: 12px; }
.tab {
  background: transparent; border: 0; border-bottom: 2px solid transparent; margin-bottom: -1px;
  padding: 7px 12px; font-size: 12.5px; color: var(--ink-2); cursor: pointer;
}
.tab.active { color: var(--brand); border-bottom-color: var(--brand); font-weight: 600; }

.col-list { border: 1px solid var(--line-2); border-radius: var(--r-md); overflow: hidden; }
.col-row {
  display: flex; align-items: center; gap: 10px; padding: 7px 12px;
  border-bottom: 1px solid var(--line-2); font-size: 12.5px;
}
.col-row:last-child { border-bottom: 0; }
.col-row:hover { background: var(--surface-2); }
.c-name { font-family: Consolas, monospace; font-size: 12.5px; color: var(--ink); flex: 1; }
.c-type { color: var(--ink-3); font-size: 11.5px; }

.sample-wrap { border: 1px solid var(--line-2); border-radius: var(--r-md); overflow-x: auto; }
.sample { width: max-content; min-width: 100%; font-size: 12px; }
.sample th, .sample td { white-space: nowrap; }

.block { margin-top: 20px; }
.block h3 { font-size: 12.5px; margin-bottom: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11.5px; padding: 4px 9px; border-radius: 14px;
  background: var(--surface-2); border: 1px solid var(--line); color: var(--ink-2);
}
.chip em { font-style: normal; color: var(--ink-3); font-size: 10.5px; }
.chip.link { cursor: pointer; }
.chip.link:hover { border-color: #c6d5e8; color: var(--brand); }

.fade-enter-active, .fade-leave-active { transition: opacity .18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.fade-enter-active .drawer { transition: transform .22s ease; }
.fade-enter-from .drawer { transform: translateX(24px); }
</style>
