<!--
  A short series of closed business dates, drawn as bars inside a KPI card.

  One series, so no legend: the card title names it. No axis and no value on
  every bar either — this is shape, not measurement, and the figure that
  matters is already set in the card as the headline. Each bar names its own
  date and value on hover and to assistive technology, which is where an exact
  reading belongs.
-->
<template>
  <svg
    v-if="bars.length"
    :viewBox="`0 0 ${width} ${height}`"
    class="h-full w-full"
    preserveAspectRatio="none"
    role="img"
    :aria-label="ariaLabel"
  >
    <rect
      v-for="bar in bars"
      :key="bar.key"
      :x="bar.x"
      :y="bar.y"
      :width="barWidth"
      :height="bar.height"
      :rx="2"
      :fill="bar.color"
    >
      <title>{{ bar.title }}</title>
    </rect>
  </svg>
</template>

<script setup>
import { computed } from 'vue'

import { PROGRESS_COLOR, TRACK_COLOR } from '@/components/dashboard/theme'

const props = defineProps({
  /** `[{ key, value, title }]`, oldest first. */
  points: { type: Array, default: () => [] },
  ariaLabel: { type: String, default: '' },
})

const height = 40
// A 2px channel of surface between bars, same spacer the donut uses.
const GAP = 2
const MIN_HEIGHT = 2

const barWidth = 8
const width = computed(() => Math.max(props.points.length, 1) * (barWidth + GAP) - GAP)

const peak = computed(() =>
  props.points.reduce((max, point) => Math.max(max, Math.abs(Number(point.value) || 0)), 0),
)

const bars = computed(() =>
  props.points.map((point, index) => {
    const value = Math.abs(Number(point.value) || 0)
    const scaled = peak.value ? (value / peak.value) * height : 0
    const barHeight = Math.max(scaled, MIN_HEIGHT)

    return {
      key: point.key ?? index,
      title: point.title || '',
      x: index * (barWidth + GAP),
      y: height - barHeight,
      height: barHeight,
      // A day with nothing posted is a fact, not a gap; it reads as the track.
      color: value ? PROGRESS_COLOR : TRACK_COLOR,
    }
  }),
)
</script>
