<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { routes } from '@/router'
import type { AppRouteMeta } from '@/router'
import { store, currentUser, setUser, notify, refreshScope } from '@/stores/session'

const route = useRoute()
const router = useRouter()

const icons: Record<AppRouteMeta['icon'], string> = {
  dashboard: 'M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM9 9h5v5H9z',
  chat: 'M2.5 4.2c0-.9.7-1.7 1.7-1.7h7.6c.9 0 1.7.7 1.7 1.7v4.6c0 .9-.7 1.7-1.7 1.7H7l-3.2 2.3c-.3.2-.7 0-.7-.4v-1.9h-.6c-.5 0-.9-.4-.9-.9V4.2z',
  report: 'M4 2.2h5.4L13 5.8v8c0 .6-.5 1-1 1H4c-.6 0-1-.4-1-1V3.2c0-.6.4-1 1-1z',
  data: 'M8 2c2.9 0 5.2.9 5.2 2.1S10.9 6.2 8 6.2 2.8 5.3 2.8 4.1 5.1 2 8 2zM2.8 4v8c0 1.2 2.3 2.1 5.2 2.1s5.2-.9 5.2-2.1V4',
  audit: 'M3 2.5h10c.6 0 1 .4 1 1v9c0 .6-.4 1-1 1H3c-.6 0-1-.4-1-1v-9c0-.6.4-1 1-1z',
}
const OUTLINE: AppRouteMeta['icon'][] = ['data', 'audit']

/** 只渲染配置了 meta 的业务路由，未匹配重定向项直接过滤掉 */
const navRoutes = computed(() =>
  routes.filter((r): r is typeof r & { meta: AppRouteMeta } => Boolean(r.name && r.meta)),
)

const meta = computed(() => store.meta)

async function onUserChange(e: Event): Promise<void> {
  const id = (e.target as HTMLSelectElement).value
  setUser(id)
  try {
    await refreshScope()
  } catch {
    /* 侧栏范围刷新失败不阻断 */
  }
  notify('已切换身份，数据范围同步更新')
}

function go(name: string): void {
  router.push({ name })
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="logo">GD</div>
      <div>
        <div class="brand-name">广东院经营分析</div>
        <div class="brand-sub">报告生成 · 项目画像问数</div>
      </div>
    </div>

    <nav class="nav">
      <button
        v-for="r in navRoutes"
        :key="String(r.name)"
        class="nav-item"
        :class="{ active: route.name === r.name }"
        @click="go(String(r.name))"
      >
        <svg viewBox="0 0 16 16" width="15" height="15">
          <path
            :d="icons[r.meta.icon]"
            :fill="OUTLINE.includes(r.meta.icon) ? 'none' : 'currentColor'"
            :stroke="OUTLINE.includes(r.meta.icon) ? 'currentColor' : 'none'"
            :stroke-width="OUTLINE.includes(r.meta.icon) ? 1.2 : 0"
          />
        </svg>
        <span>{{ r.meta.title }}</span>
      </button>
    </nav>

    <div class="side-bottom">
      <div class="who">
        <div class="who-avatar">{{ (currentUser.name || '—').slice(0, 1) }}</div>
        <div>
          <div class="who-name">{{ currentUser.name || '—' }}</div>
          <div class="who-role">{{ currentUser.role || '—' }}</div>
        </div>
      </div>
      <div class="who-scope"><span class="dot"></span>{{ store.scope || '—' }}</div>
      <label class="switch-user">
        <span>切换身份</span>
        <select :value="store.userId" @change="onUserChange">
          <option v-for="u in store.users" :key="u.user_id" :value="u.user_id">
            {{ u.role }} · {{ u.name }}
          </option>
        </select>
      </label>
      <div class="side-meta" v-if="meta">
        {{ meta.tables }} 张表 · {{ meta.metrics }} 个指标<br />
        {{ meta.llm.online ? '模型 ' + meta.llm.model : '内置规则引擎（离线）' }}<br />
        知识库 {{ meta.kb.files }} 篇 · Oracle 11g 方言
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 224px; flex: 0 0 224px; background: var(--surface);
  border-right: 1px solid var(--line); display: flex; flex-direction: column;
  padding: 18px 12px 14px; position: sticky; top: 0; height: 100vh;
}
.brand { display: flex; align-items: center; gap: 10px; padding: 0 6px 18px; }
.logo {
  width: 34px; height: 34px; border-radius: 9px; flex: 0 0 34px;
  background: linear-gradient(160deg, var(--brand), #2b6cb8);
  color: #fff; font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center;
}
.brand-name { font-size: 14px; font-weight: 600; }
.brand-sub { font-size: 11px; color: var(--ink-3); line-height: 1.4; }
.nav { display: flex; flex-direction: column; gap: 2px; }
.nav-item {
  display: flex; align-items: center; gap: 10px; background: transparent; border: 0;
  cursor: pointer; padding: 9px 10px; border-radius: var(--r-sm);
  color: var(--ink-2); font-size: 13px; text-align: left; transition: background .14s, color .14s;
}
.nav-item svg { opacity: .78; }
.nav-item:hover { background: var(--surface-2); color: var(--ink); }
.nav-item.active { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
.nav-item.active svg { opacity: 1; }
.side-bottom { margin-top: auto; padding: 10px 4px 0; border-top: 1px solid var(--line-2); }
.who { display: flex; align-items: center; gap: 9px; }
.who-avatar {
  width: 30px; height: 30px; border-radius: 9px; flex: 0 0 30px;
  background: var(--brand-soft); color: var(--brand);
  display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600;
}
.who-name { font-size: 12.5px; font-weight: 600; }
.who-role { font-size: 11px; color: var(--ink-3); }
.who-scope {
  margin-top: 8px; display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ink-2);
  background: var(--surface-2); border: 1px solid var(--line-2); border-radius: 7px; padding: 5px 8px;
}
.who-scope .dot { width: 5px; height: 5px; border-radius: 50%; background: #3aa06b; }
.switch-user { display: flex; flex-direction: column; gap: 4px; margin-top: 10px; font-size: 11px; color: var(--ink-3); }
.switch-user select { width: 100%; }
.side-meta { margin-top: 10px; font-size: 10.5px; color: var(--ink-3); line-height: 1.55; }
</style>
