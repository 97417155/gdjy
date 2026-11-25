<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppSidebar from '@/components/AppSidebar.vue'
import Toast from '@/components/Toast.vue'
import { bootstrap, notify } from '@/stores/session'

const loading = ref<boolean>(true)
const error = ref<string>('')

onMounted(async () => {
  try {
    await bootstrap()
  } catch (e) {
    error.value = (e as Error).message
    notify('初始化失败：' + (e as Error).message)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-if="loading" class="boot">正在加载经营数据…</div>
  <div v-else-if="error" class="boot">后端未就绪：{{ error }}<br /><span class="sub">请先运行 python run.py</span></div>
  <div v-else class="layout">
    <AppSidebar />
    <main class="main">
      <router-view />
    </main>
  </div>
  <Toast />
</template>

<style scoped>
.boot {
  height: 100%; display: flex; flex-direction: column; gap: 6px;
  align-items: center; justify-content: center; color: var(--ink-2); font-size: 13px;
}
</style>
