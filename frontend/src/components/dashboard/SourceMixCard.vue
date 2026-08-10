<!--
  Where the day's arrivals were booked.

  Counted from the arrivals board the dashboard already loaded, so this is
  today's arriving rooms by source and is titled as exactly that. It is not a
  period booking mix and does not pretend to be one: the hotel's channel
  production is a reporting question with its own date range, and answering it
  from a front desk screen would put a number on the wall that no report would
  agree with.

  Slots are assigned in a fixed order and never cycled. Past the sixth source
  the tail folds into one "other" slice rather than inventing a seventh hue.
-->
<template>
  <DashboardCard :title="t('page.dashboard.sources.title')" :subtitle="t('page.dashboard.sources.subtitle')" dense>
    <p v-if="!slices.length" class="py-4 text-p-sm text-ink-gray-5">
      {{ t('page.dashboard.sources.empty') }}
    </p>

    <div v-else class="flex items-center gap-4">
      <DonutChart
        :segments="slices"
        :size="104"
        :thickness="16"
        :aria-label="t('page.dashboard.sources.chart_label')"
      />

      <!-- The legend carries the name and the share as text: colour ties a row
           to an arc, it never has to carry the reading on its own. -->
      <ul class="min-w-0 flex-1 space-y-1.5">
        <li v-for="slice in slices" :key="slice.key" class="flex items-center gap-2 text-p-sm">
          <span class="size-2.5 shrink-0 rounded-full" :style="{ backgroundColor: slice.color }" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate text-ink-gray-7">{{ slice.label }}</span>
          <span class="shrink-0 font-medium tabular-nums text-ink-gray-8">{{ slice.share }}%</span>
        </li>
      </ul>
    </div>
  </DashboardCard>
</template>

<script setup>
import { computed } from 'vue'

import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import DonutChart from '@/components/dashboard/DonutChart.vue'
import { SERIES_COLORS } from '@/components/dashboard/theme'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The `rows` block of an arrivals board response. */
  arrivals: { type: Array, default: () => [] },
})

/** One slot is held back for the tail, so "other" is always the last colour. */
const NAMED_SLOTS = SERIES_COLORS.length - 1

const slices = computed(() => {
  const counts = new Map()

  for (const row of props.arrivals) {
    const source = (row.booking_source || '').trim() || t('page.dashboard.sources.unspecified')

    counts.set(source, (counts.get(source) || 0) + 1)
  }

  const total = props.arrivals.length
  if (!total) return []

  const ordered = [...counts.entries()].sort((a, b) => b[1] - a[1])
  const named = ordered.slice(0, NAMED_SLOTS)
  const tail = ordered.slice(NAMED_SLOTS)

  const slices = named.map(([label, value], index) => ({
    key: label,
    label,
    value,
    color: SERIES_COLORS[index],
    share: Math.round((value / total) * 100),
  }))

  if (tail.length) {
    const value = tail.reduce((sum, [, count]) => sum + count, 0)

    slices.push({
      key: '__other__',
      label: t('page.dashboard.sources.other', { count: tail.length }),
      value,
      color: SERIES_COLORS[SERIES_COLORS.length - 1],
      share: Math.round((value / total) * 100),
    })
  }

  return slices
})
</script>
