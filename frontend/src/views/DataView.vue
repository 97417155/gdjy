<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import TableDrawer from '@/components/TableDrawer.vue'
import { api } from '@/api'
import { store } from '@/stores/session'
import type { MetricDictItem, SchemaTable } from '@/types'

const route = useRoute()
const tab = ref<'metrics' | 'schema' | 'roles'>('metrics')
const metrics = ref<MetricDictItem[]>([])
const schema = ref<SchemaTable[]>([])
const keyword = ref('')
const loading = ref(true)
const drawerOpen = ref(false)
const activeTable = ref('')

const TABS = [
  { key: 'metrics', label: '指标口径' },
  { key: 'schema', label: '数据表' },
  { key: 'roles', label: '权限矩阵' },
] as const

const FIN_ROLES = ['院长', '副院长', '分公司负责人', '财务专员']
const SCOPE_TEXT: Record<string, string> = {
  ALL: '全院数据', ORG: '本分公司及下级', DEPT: '本部门', PROJ: '参与项目',
}

const dataSub = computed(() =>
  store.meta ? `${store.meta.tables} 张表 · ${store.meta.metrics} 个指标 · 当前可见范围：${store.scope}` : '',
)

const filteredTables = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return schema.value
  return schema.value.filter((t) => t.table.toLowerCase().includes(k))
})

const filteredMetrics = computed(() => {
  const k = keyword.value.trim()
  if (!k) return metrics.value
  return metrics.value.filter((m) => m.KPI_NAME.includes(k) || (m.DEFINITION || '').includes(k))
})

function openTable(name: string): void {
  activeTable.value = name
  drawerOpen.value = true
}

onMounted(async () => {
  try {
    const [m, s] = await Promise.all([api.metrics(), api.schema()])
    metrics.value = m
    schema.value = s
    // 深链：/data?table=FACT_CONTRACT 直接打开表结构抽屉
    const t = route.query.table
    if (typeof t === 'string' && t) {
      tab.value = 'schema'
      openTable(t)
    }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <header class="page-head">
    <div>
      <h1>数据与权限</h1>
      <p class="sub">{{ dataSub }}</p>
    </div>
    <div class="head-tools">
      <input v-model="keyword" class="search" placeholder="搜索指标或表名" />
    </div>
  </header>

  <div class="tabs-line">
    <button
      v-for="t in TABS" :key="t.key" class="tl-item"
      :class="{ active: tab === t.key }" @click="tab = t.key"
    >
      {{ t.label }}
    </button>
  </div>

  <div v-show="tab === 'metrics'" class="card">
    <div class="card-head">
      <h3>指标字典</h3>
      <span class="card-note">共 {{ filteredMetrics.length }} 个 · 点开可看完整口径</span>
    </div>
    <div v-if="loading" class="chart-empty">加载中…</div>
    <details v-for="m in filteredMetrics" :key="m.KPI_ID" class="metric-row">
      <summary>
        <span class="m-name">{{ m.KPI_NAME }}</span>
        <span class="m-cat">{{ m.category_name }}</span>
        <span class="m-def">{{ m.DEFINITION }}</span>
        <span class="m-unit">{{ m.UNIT }}</span>
      </summary>
      <div class="m-more">
        <b>口径编号：</b>{{ m.CALIBER_ID }} · {{ m.caliber || '—' }}<br />
        <b>归口部门：</b>{{ m.OWNER_DEPT || '—' }} · <b>已接入引擎：</b>{{ m.in_engine ? '是' : '否' }}
      </div>
    </details>
  </div>

  <div v-show="tab === 'schema'" class="card">
    <div class="card-head">
      <h3>数据表清单</h3>
      <span class="card-note">共 {{ filteredTables.length }} 张表 · 点击查看表结构</span>
    </div>
    <div class="schema-grid">
      <button v-for="t in filteredTables" :key="t.table" class="schema-item" @click="openTable(t.table)">
        <b>{{ t.table }}</b>
        <span>{{ t.rows.toLocaleString() }} 行 · {{ t.columns.length }} 列</span>
      </button>
    </div>
    <div v-if="!filteredTables.length" class="chart-empty">没有匹配的表</div>
  </div>

  <div v-show="tab === 'roles'" class="card">
    <div class="card-head">
      <h3>岗位与可见范围</h3>
      <span class="card-note">行级隔离由 SQL 谓词注入实现</span>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead>
          <tr><th>姓名</th><th>岗位</th><th>所属组织</th><th>可见范围</th><th>利润类指标</th></tr>
        </thead>
        <tbody>
          <tr v-for="u in store.users" :key="u.user_id">
            <td>{{ u.name }}</td>
            <td>{{ u.role }}</td>
            <td>{{ u.org_name }}</td>
            <td>{{ SCOPE_TEXT[u.scope_type] }}</td>
            <td>
              <span v-if="FIN_ROLES.includes(u.role)" class="tag ok">可见</span>
              <span v-else class="tag">脱敏</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <TableDrawer
    v-model="drawerOpen"
    :table="activeTable"
    @select="(t) => { activeTable = t; drawerOpen = true }"
  />
</template>

<style scoped>
.tabs-line { display: flex; gap: 4px; margin-bottom: 14px; border-bottom: 1px solid var(--line); }
.tl-item {
  background: transparent; border: 0; border-bottom: 2px solid transparent;
  padding: 8px 13px; font-size: 13px; color: var(--ink-2); cursor: pointer; margin-bottom: -1px;
}
.tl-item.active { color: var(--brand); border-bottom-color: var(--brand); font-weight: 600; }
.search {
  border: 1px solid var(--line); background: var(--surface); border-radius: var(--r-sm);
  padding: 6px 11px; font-size: 12.5px; width: 210px; outline: none;
}
.search:focus { border-color: #a9c4e6; box-shadow: 0 0 0 3px rgba(31,95,169,.07); }
.metric-row { border-bottom: 1px solid var(--line-2); padding: 9px 4px; }
.metric-row summary { cursor: pointer; display: flex; gap: 10px; align-items: baseline; font-size: 12.5px; }
.metric-row summary::-webkit-details-marker { display: none; }
.m-name { font-weight: 600; flex: 0 0 148px; }
.m-cat { color: var(--ink-3); flex: 0 0 84px; font-size: 11.5px; }
.m-def { color: var(--ink-2); flex: 1; font-size: 12px; }
.m-unit { color: var(--ink-3); flex: 0 0 62px; text-align: right; font-size: 11.5px; }
.m-more { margin: 8px 0 2px 158px; font-size: 12px; color: var(--ink-2); line-height: 1.65; }

.schema-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(212px, 1fr)); gap: 9px; }
.schema-item {
  text-align: left; border: 1px solid var(--line-2); border-radius: var(--r-sm);
  padding: 9px 11px; background: var(--surface-2); font-size: 12px; cursor: pointer;
  transition: border-color .14s, background .14s;
}
.schema-item:hover { border-color: #c6d5e8; background: #f7fafd; }
.schema-item b { display: block; font-family: Consolas, monospace; font-size: 12.5px; }
.schema-item span { color: var(--ink-3); font-size: 11.5px; }
</style>
