<template>
  <svg :viewBox="`0 0 ${width} ${height}`" class="h-10 w-[130px]">
    <polyline
      fill="none"
      :stroke="color"
      stroke-width="2.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      :points="points"
    />
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    data: number[]
    color?: string
    width?: number
    height?: number
  }>(),
  {
    color: '#2563eb',
    width: 130,
    height: 42,
  },
)

const points = computed(() => {
  const min = Math.min(...props.data)
  const max = Math.max(...props.data)
  const safe = max - min || 1
  const step = props.width / (props.data.length - 1)

  return props.data
    .map((value, index) => `${index * step},${props.height - ((value - min) / safe) * (props.height - 6) - 3}`)
    .join(' ')
})
</script>
