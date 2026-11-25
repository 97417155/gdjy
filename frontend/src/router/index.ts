import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

export interface AppRouteMeta {
  title: string
  icon: 'dashboard' | 'chat' | 'report' | 'data' | 'audit'
}

export type AppRoute = RouteRecordRaw & { meta?: AppRouteMeta }

export const routes: AppRoute[] = [
  { path: '/', name: 'dashboard', meta: { title: '经营驾驶舱', icon: 'dashboard' }, component: () => import('@/views/DashboardView.vue') },
  { path: '/chat', name: 'chat', meta: { title: '智能问答', icon: 'chat' }, component: () => import('@/views/ChatView.vue') },
  { path: '/report', name: 'report', meta: { title: '经营报告', icon: 'report' }, component: () => import('@/views/ReportView.vue') },
  { path: '/data', name: 'data', meta: { title: '数据与权限', icon: 'data' }, component: () => import('@/views/DataView.vue') },
  { path: '/audit', name: 'audit', meta: { title: '查询审计', icon: 'audit' }, component: () => import('@/views/AuditView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})
