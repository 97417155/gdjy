<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import { notify } from '@/stores/session'
import type { AuditRow } from '@/types'

const rows = ref<AuditRow[]>([])
const loading = ref(false)

const INTENT: Record<string, string> = { data: '取数', archive: '档案', kb: '制度', clarify: '澄清', chat: '引导' }

const stats = computed(() => {
  const cost = rows.value.map((r) => r.COST_MS || 0)
  const avg = cost.length ? Math.round(cost.reduce((a, b) => a + b, 0) / cost.length) : 0
  return [
    { label: '查询总数', value: rows.value.length },
    { label: '平均耗时', value: avg + ' ms' },
    { label: '覆盖账号', value: new Set(rows.value.map((r) => r.USER_ID)).size },
    { label: '异常/澄清', value: rows.value.filter((r) => r.STATUS && r.STATUS !== 'ok').length },
  ]
})

async function load(showToast = false): Promise<void> {
  loading.value = true
  try {
    rows.value = await api.audit(50)
    if (showToast) notify('已刷新')
  } catch (e) {
    notify('加载失败：' + (e as Error).message)
  } finally {
    loading.value = false
  }
}

onMounted(() => load())
</script>

<template>
  <header class="page-head">
    <div>
      <h1>查询审计</h1>
      <p class="sub">问题、意图、SQL、耗时、数据范围全程留痕</p>
    </div>
    <div class="head-tools">
      <button class="btn" :disabled="loading" @click="load(true)">{{ loading ? '刷新中…' : '刷新' }}</button>
    </div>
  </header>

  <div class="stat-row">
    <div v-for="s in stats" :key="s.label" class="stat">
      <div class="s-label">{{ s.label }}</div>
      <div class="s-value">{{ s.value }}</div>
    </div>
  </div>

  <div class="card">
    <div v-if="rows.length" class="tbl-wrap">
      <table>
        <thead>
          <tr>
            <th>时间</th><th>账号</th><th>问题</th><th>意图</th>
            <th class="num">行数</th><th class="num">耗时</th><th>状态</th><th>数据范围</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.LOG_ID">
            <td>{{ (r.CREATE_TIME || '').slice(5) }}</td>
            <td>{{ r.USER_ID }}</td>
            <td :title="r.QUESTION">{{ (r.QUESTION || '').slice(0, 34) }}</td>
            <td>{{ INTENT[r.INTENT] || r.INTENT }}</td>
            <td class="num">{{ r.ROW_CNT }}</td>
            <td class="num">{{ r.COST_MS }}</td>
            <td>
              <span v-if="r.STATUS === 'ok'" class="tag ok">正常</span>
              <span v-else class="tag warn">{{ r.STATUS }}</span>
            </td>
            <td>{{ r.SCOPE_DESC }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="chart-empty">暂无查询记录</div>
  </div>
</template>

<style scoped>
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px; }
@media (max-width: 900px) { .stat-row { grid-template-columns: repeat(2, 1fr); } }
.stat { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); padding: 12px 14px; }
.s-label { font-size: 11.5px; color: var(--ink-3); }
.s-value { font-size: 20px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
</style>
