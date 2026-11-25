<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import EChart from '@/components/EChart.vue'
import { api } from '@/api'
import { store, currentUser, periodEnd, notify } from '@/stores/session'
import { barOption, lineOption, donutOption } from '@/utils/charts'
import { fmt, fmtInt, pct } from '@/utils/format'
import type { DashboardData } from '@/types'

const data = ref<DashboardData | null>(null)
const loading = ref(true)

async function load(showToast = false): Promise<void> {
  loading.value = true
  try {
    data.value = await api.dashboard(store.userId, `${store.period}-01`, periodEnd(store.period))
    store.scope = data.value.scope
    if (showToast) notify('已刷新')
  } catch (e) {
    notify('加载失败：' + (e as Error).message)
  } finally {
    loading.value = false
  }
}

onMounted(() => load())
watch(() => store.userId, () => load())
watch(() => store.period, () => load())

const rankOption = computed(() => {
  const c = data.value?.charts?.[0]
  return c ? barOption(c.labels, c.series[0]?.data ?? [], '万元') : null
})
const trendOption = computed(() => {
  const c = data.value?.charts?.[1]
  return c ? lineOption(c.labels, c.series[0]?.data ?? [], '万元') : null
})
const engOption = computed(() => {
  const c = data.value?.charts?.[2]
  return c ? donutOption(c.labels, c.series[0]?.data ?? [], '万元') : null
})
const trendNote = computed(() => {
  const chart = data.value?.charts?.[1]
  const arr = (chart?.series?.[0]?.data ?? []).filter((v) => v != null)
  if (!chart || arr.length < 2) return ''
  const change = ((arr[arr.length - 1] - arr[0]) / (arr[0] || 1)) * 100
  return `${chart.labels[0]} → ${chart.labels[chart.labels.length - 1]} · ${pct(change)}`
})
const periodLabel = computed(() => {
  const ym = store.period || ''
  return `${ym.slice(0, 4)} 年 ${Number(ym.slice(5, 7))} 月`
})
</script>

<template>
  <header class="page-head">
    <div>
      <h1>经营驾驶舱</h1>
      <p class="sub">
        {{ periodLabel }} · {{ currentUser.name }}（{{ currentUser.role }}）· {{ data?.scope || store.scope }}
      </p>
    </div>
    <div class="head-tools">
      <select v-model="store.period" class="select">
        <option v-for="p in store.periods" :key="p.value" :value="p.value">{{ p.label }}</option>
      </select>
      <button class="btn" :disabled="loading" @click="load(true)">{{ loading ? '刷新中…' : '刷新' }}</button>
    </div>
  </header>

  <div v-if="!data" class="kpi-row">
    <div v-for="i in 4" :key="i" class="kpi skeleton">
      <div class="sk-line w40"></div>
      <div class="sk-line w70 tall"></div>
      <div class="sk-line w55"></div>
    </div>
  </div>

  <template v-else>
    <div class="kpi-row">
      <div v-for="t in data.top" :key="t.kpi" class="kpi">
        <div class="k-label">{{ t.name }}</div>
        <template v-if="t.masked">
          <div class="k-mask">*** 无权限（利润类指标）</div>
        </template>
        <template v-else>
          <div class="k-value">{{ fmt(t.value, t.unit === '%' ? 2 : 0) }}<small>{{ t.unit }}</small></div>
          <div class="k-delta">
            <span>同比 <b :class="(t.yoy ?? 0) >= 0 ? 'up' : 'down'">{{ pct(t.yoy) }}</b></span>
            <span>环比 <b :class="(t.mom ?? 0) >= 0 ? 'up' : 'down'">{{ pct(t.mom) }}</b></span>
          </div>
        </template>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-head">
          <h3>各分公司新签合同额</h3>
          <span class="card-note">共 {{ data.charts[0]?.labels.length || 0 }} 个单位</span>
        </div>
        <EChart v-if="rankOption" :option="rankOption" height="230px" />
      </div>
      <div class="card">
        <div class="card-head">
          <h3>近 6 个月营业收入</h3>
          <span class="card-note">{{ trendNote }}</span>
        </div>
        <EChart v-if="trendOption" :option="trendOption" height="230px" />
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-head"><h3>营业收入结构</h3><span class="card-note">按工程类型</span></div>
        <EChart v-if="engOption" :option="engOption" height="230px" />
      </div>
      <div class="card">
        <div class="card-head"><h3>产值完成缺口</h3><span class="card-note">在建项目 · 缺口 TOP6</span></div>
        <div class="list-box">
          <div v-for="(r, i) in data.risks" :key="r['项目名称'] + i" class="list-row">
            <span class="rank">{{ i + 1 }}</span>
            <span class="name" :title="r['项目名称']">{{ r['项目名称'] }}</span>
            <span class="org">{{ r['分公司'] }}</span>
            <span class="val">缺 {{ fmtInt(r['缺口_万元']) }} 万</span>
          </div>
          <div v-if="!data.risks.length" class="chart-empty">本期无产值缺口项目</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h3>七大类指标</h3><span class="card-note">口径与 BI 平台对齐</span></div>
      <div class="cat-grid">
        <div v-for="c in data.cards" :key="c.kpi" class="cat">
          <div class="c-name">{{ c.category_name }} · {{ c.name }}</div>
          <div class="c-val">
            <span v-if="c.masked" class="masked">*** 无权限</span>
            <template v-else>{{ fmt(c.value, c.unit === '%' ? 2 : 0) }}<small>{{ c.unit }}</small></template>
          </div>
        </div>
      </div>
    </div>
  </template>
</template>

<style scoped>
.skeleton { pointer-events: none; }
.sk-line { height: 10px; border-radius: 4px; background: #eef1f5; margin-bottom: 10px; animation: pulse 1.4s infinite; }
.sk-line.tall { height: 22px; }
.w40 { width: 40%; }
.w55 { width: 55%; }
.w70 { width: 70%; }
@keyframes pulse { 0%, 100% { opacity: .55; } 50% { opacity: 1; } }
.masked { font-size: 11.5px; color: var(--ink-3); }
</style>
