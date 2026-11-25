<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ status?: string }>(), { status: '草稿' })
const STATES = ['草稿', '已校验', '待审批', '已通过', '已推送'] as const
const idx = computed(() => Math.max(0, STATES.indexOf(props.status as typeof STATES[number])))
</script>

<template>
  <div class="stepper">
    <template v-for="(s, i) in STATES" :key="s">
      <div class="step" :class="i < idx ? 'done' : i === idx ? 'active' : ''">
        <span class="dot">{{ i < idx ? '✓' : i + 1 }}</span>{{ s }}
      </div>
      <div v-if="i < STATES.length - 1" class="step-line" :class="{ done: i < idx }"></div>
    </template>
  </div>
</template>

<style scoped>
.stepper { display: flex; align-items: center; margin: 16px 0 4px; }
.step { display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--ink-3); }
.step .dot {
  width: 17px; height: 17px; border-radius: 50%; border: 1px solid var(--line);
  background: var(--surface); display: flex; align-items: center; justify-content: center;
  font-size: 9.5px; color: var(--ink-3);
}
.step.done { color: var(--brand); }
.step.done .dot { background: var(--brand); border-color: var(--brand); color: #fff; }
.step.active { color: var(--brand); font-weight: 600; }
.step.active .dot { border-color: var(--brand); color: var(--brand); }
.step-line { flex: 1; height: 1px; background: var(--line); margin: 0 10px; min-width: 18px; }
.step-line.done { background: var(--brand); }
</style>
