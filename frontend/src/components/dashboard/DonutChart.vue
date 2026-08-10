<!--
  A donut, used two ways: one value against a track (occupancy, audit
  progress), or a small set of parts of a whole (where today's arrivals were
  booked).

  Deliberately thin-marked and unlabelled inside the ring. Identity comes from
  the legend beside it, which carries the name and the figure as text — three
  of the categorical slots sit below 3:1 against a white card, so the words are
  the reading and the colour only ties a row to an arc.

  Direction-agnostic: the ring starts at twelve o'clock and runs clockwise in
  both LTR and RTL, because a clock does.
-->
<template>
  <svg
    :viewBox="`0 0 ${size} ${size}`"
    :width="size"
    :height="size"
    class="shrink-0 overflow-visible"
    role="img"
    :aria-label="ariaLabel"
  >
    <g :transform="`rotate(-90 ${center} ${center})`">
      <circle
        :cx="center"
        :cy="center"
        :r="radius"
        fill="none"
        :stroke="trackColor"
        :stroke-width="thickness"
      />

      <circle
        v-for="arc in arcs"
        :key="arc.key"
        :cx="center"
        :cy="center"
        :r="radius"
        fill="none"
        :stroke="arc.color"
        :stroke-width="thickness"
        :stroke-linecap="arc.round ? 'round' : 'butt'"
        :stroke-dasharray="`${arc.length} ${circumference - arc.length}`"
        :stroke-dashoffset="-arc.offset"
      >
        <title v-if="arc.label">{{ arc.label }}</title>
      </circle>
    </g>

    <foreignObject v-if="$slots.default" :x="inset" :y="inset" :width="size - inset * 2" :height="size - inset * 2">
      <div class="flex h-full w-full flex-col items-center justify-center text-center leading-tight">
        <slot />
      </div>
    </foreignObject>
  </svg>
</template>

<script setup>
import { computed } from 'vue'

import { PROGRESS_COLOR, TRACK_COLOR } from '@/components/dashboard/theme'

const props = defineProps({
  /** Parts of a whole: `[{ key, label, value, color }]`. */
  segments: { type: Array, default: () => [] },
  /** Single value mode: 0..100, drawn with a rounded end against the track. */
  percentage: { type: Number, default: null },
  size: { type: Number, default: 120 },
  thickness: { type: Number, default: 14 },
  color: { type: String, default: PROGRESS_COLOR },
  trackColor: { type: String, default: TRACK_COLOR },
  ariaLabel: { type: String, default: '' },
})

/** A gap of surface between neighbouring arcs, so two fills never touch. */
const GAP = 2

const center = computed(() => props.size / 2)
const radius = computed(() => (props.size - props.thickness) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)
const inset = computed(() => props.thickness + 4)

const total = computed(() =>
  props.segments.reduce((sum, segment) => sum + Math.max(Number(segment.value) || 0, 0), 0),
)

const arcs = computed(() => {
  const c = circumference.value

  // Single value: one arc with a rounded end, which reads as a dial rather
  // than as a one-slice pie.
  if (props.percentage !== null) {
    const fraction = Math.min(Math.max(Number(props.percentage) || 0, 0), 100) / 100
    if (!fraction) return []

    return [{ key: 'value', color: props.color, length: c * fraction, offset: 0, round: true }]
  }

  if (!total.value) return []

  let offset = 0

  return props.segments
    .map((segment) => {
      const value = Math.max(Number(segment.value) || 0, 0)
      const span = (value / total.value) * c
      // Never let the gap eat a small slice entirely: a source with one
      // booking must still leave a mark.
      const length = Math.max(span - GAP, 1)
      const arc = { key: segment.key, label: segment.label, color: segment.color, length, offset }

      offset += span

      return arc
    })
    .filter((arc) => arc.length > 0)
})
</script>
