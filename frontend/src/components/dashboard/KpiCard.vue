<!--
  One headline figure, with room for a small visual beside it.

  The change line is optional and only ever rendered from two figures that
  actually exist: the last two closed Night Audits. A dashboard that always
  shows an arrow invents one on the day it has nothing to compare against.
-->
<template>
  <DashboardCard :title="label" :icon="icon" :icon-class="iconClass" dense>
  <div class="flex h-full flex-col">
    <!-- Bottom-aligned so a card carrying a chart and a card carrying only a
         figure still set their headline on the same line across the row. The
         row takes the slack; the footer keeps its own height. -->
    <div class="flex min-h-[4.5rem] flex-1 items-end justify-between gap-3">
      <div class="min-w-0">
        <p class="flex items-baseline gap-1.5">
          <span v-if="prefix" class="text-p-sm font-medium text-ink-gray-5">{{ prefix }}</span>
          <span class="truncate text-2xl font-semibold tracking-tight text-ink-gray-9 2xl:text-3xl">
            {{ value }}
          </span>
        </p>

        <p v-if="caption" class="mt-1 text-xs leading-tight text-ink-gray-5">{{ caption }}</p>
        <p v-if="footnote" class="mt-0.5 text-xs leading-tight text-ink-gray-5">{{ footnote }}</p>

        <!--
          Direction is carried by the word as well as the triangle and the
          colour, so the line still reads when colour does not.
        -->
        <p v-if="delta" class="mt-1.5 flex items-center gap-1 text-xs font-medium" :class="delta.class">
          <FeatherIcon :name="delta.icon" class="size-3.5 shrink-0" aria-hidden="true" />
          <span class="truncate">{{ delta.text }}</span>
        </p>
      </div>

      <div class="shrink-0">
        <slot />
      </div>
    </div>

    <!-- A visual that needs the card's whole width rather than the space left
         beside the figure. A five-figure amount and a chart do not both fit in
         a sixth of a screen, and the figure is the one that must not shrink. -->
    <div v-if="$slots.footer" class="mt-2.5 shrink-0">
      <slot name="footer" />
    </div>
  </div>
  </DashboardCard>
</template>

<script setup>
import { FeatherIcon } from 'frappe-ui'
import { computed } from 'vue'

import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import { formatNumber } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  /** Currency code or unit shown small, before the figure. */
  prefix: { type: String, default: '' },
  caption: { type: String, default: '' },
  /** A second muted line, for a related figure the headline is not. */
  footnote: { type: String, default: '' },
  icon: { type: String, default: '' },
  iconClass: { type: String, default: 'bg-blue-50 text-blue-600' },
  /** Percentage change against the previous closed business date, or null. */
  change: { type: Number, default: null },
  changeLabel: { type: String, default: '' },
})

const delta = computed(() => {
  if (props.change === null || props.change === undefined || !Number.isFinite(props.change)) return null

  const value = Number(props.change)
  const label = props.changeLabel || t('page.dashboard.vs_previous')
  const magnitude = `${formatNumber(Math.abs(value), 1)}%`

  if (Math.abs(value) < 0.05) {
    return {
      icon: 'minus',
      class: 'text-ink-gray-5',
      text: t('page.dashboard.change_flat', { label }),
    }
  }

  const rising = value > 0

  return {
    icon: rising ? 'trending-up' : 'trending-down',
    class: rising ? 'text-ink-green-3' : 'text-ink-red-3',
    text: rising
      ? t('page.dashboard.change_up', { value: magnitude, label })
      : t('page.dashboard.change_down', { value: magnitude, label }),
  }
})
</script>
