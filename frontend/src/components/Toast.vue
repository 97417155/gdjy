<script setup lang="ts">
import { store } from '@/stores/session'
</script>

<template>
  <div class="toast" :class="{ show: store.toast.visible }">{{ store.toast.text }}</div>
</template>
