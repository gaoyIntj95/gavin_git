<template>
  <article class="group relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl">
    <div class="pointer-events-none absolute inset-x-0 top-0 h-1 bg-gradient-to-r" :class="toneTopClass"></div>

    <div class="mb-4 flex items-start justify-between gap-3">
      <h3 class="text-base font-semibold text-slate-700">{{ title }}</h3>
      <Sparkline :data="trend" :color="lineColor" />
    </div>

    <div class="mb-1 flex items-start gap-2">
      <span class="text-[2.15rem] font-extrabold leading-none tracking-tight text-slate-900">{{ value }}</span>
      <span v-if="unit" class="mt-0.5 text-xs font-medium text-slate-400">{{ unit }}</span>
    </div>

    <p class="mt-3 text-sm text-slate-500">{{ sub1 }}</p>
    <p class="mt-1 text-sm text-slate-500">{{ sub2 }}</p>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Sparkline from './Sparkline.vue'

const props = withDefaults(
  defineProps<{
    title: string
    value: string
    unit?: string
    sub1?: string
    sub2?: string
    trend: number[]
    tone?: 'blue' | 'green' | 'orange'
  }>(),
  {
    unit: '',
    sub1: '',
    sub2: '',
    tone: 'blue',
  },
)

const lineColor = computed(() => {
  if (props.tone === 'green') return '#16a34a'
  if (props.tone === 'orange') return '#f59e0b'
  return '#2563eb'
})

const toneTopClass = computed(() => {
  if (props.tone === 'green') return 'from-emerald-400 to-emerald-200'
  if (props.tone === 'orange') return 'from-amber-400 to-amber-200'
  return 'from-blue-500 to-blue-200'
})
</script>
