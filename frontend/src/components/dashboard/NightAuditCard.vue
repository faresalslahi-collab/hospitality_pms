<!--
  Where tonight's close has got to.

  Progress is read off the audit's own status, using the same state order the
  Night Audit screen uses to decide which step is current — one order, in one
  place, so the ring and the step rail can never tell different stories. The
  ring is a position in a five-state workflow, not a measurement of work done,
  and the status word under it is what actually names the state.

  Nothing here runs a step. The audit screen holds the locks and the roles.
-->
<template>
  <DashboardCard :title="t('page.dashboard.audit.title')">
    <div v-if="!audit" class="flex flex-col items-center py-6 text-center">
      <FeatherIcon name="moon" class="size-6 text-ink-gray-4" aria-hidden="true" />
      <p class="mt-2 text-p-sm text-ink-gray-5">{{ t('page.dashboard.audit.none') }}</p>
    </div>

    <div v-else class="flex flex-col items-center">
      <DonutChart
        :percentage="progress"
        :size="132"
        :thickness="13"
        :aria-label="t('page.dashboard.audit.progress_label', { percent: progress, status: statusLabel })"
      >
        <span class="text-2xl font-semibold tracking-tight text-ink-gray-9">{{ progress }}%</span>
        <span class="mt-0.5 text-xs font-medium" :class="statusClass">{{ statusLabel }}</span>
      </DonutChart>

      <dl class="mt-3 w-full space-y-1 text-center text-xs text-ink-gray-6">
        <div>
          <dt class="inline">{{ t('page.dashboard.audit.business_date') }}:</dt>
          <dd class="ms-1 inline font-medium text-ink-gray-8">{{ formatDate(audit.business_date) }}</dd>
        </div>
        <div v-if="audit.started_on">
          <dt class="inline">{{ t('page.dashboard.audit.started') }}:</dt>
          <dd class="ms-1 inline font-medium text-ink-gray-8">{{ formatDateTime(audit.started_on) }}</dd>
        </div>
        <div v-if="audit.started_by">
          <dt class="inline">{{ t('page.dashboard.audit.by') }}:</dt>
          <dd class="ms-1 inline font-medium text-ink-gray-8">{{ audit.started_by }}</dd>
        </div>
      </dl>

      <!-- Blocking exceptions are the reason a close does not happen; they are
           never left to be discovered on the audit screen. -->
      <p
        v-if="blockingCount"
        class="mt-2.5 flex items-center gap-1.5 rounded-lg bg-surface-red-1 px-2.5 py-1.5 text-xs font-medium text-ink-red-4"
      >
        <FeatherIcon name="alert-triangle" class="size-3.5 shrink-0" aria-hidden="true" />
        {{ t('page.dashboard.audit.blocking', { count: blockingCount }) }}
      </p>

      <RouterLink
        :to="{ name: 'NightAudit' }"
        class="mt-3 flex w-full items-center justify-center gap-1 rounded-lg border border-outline-gray-2
          px-3 py-1.5 text-p-sm font-medium text-ink-gray-8 transition-colors hover:bg-surface-gray-2"
      >
        {{ t('page.dashboard.audit.open') }}
        <FeatherIcon name="chevron-right" class="size-3.5 flip-rtl" aria-hidden="true" />
      </RouterLink>
    </div>
  </DashboardCard>
</template>

<script setup>
import { FeatherIcon } from 'frappe-ui'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import DonutChart from '@/components/dashboard/DonutChart.vue'
import { formatDate, formatDateTime } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The `audit` block of a `night_audit.get_current` response, or null. */
  audit: { type: Object, default: null },
  blockingCount: { type: Number, default: 0 },
})

/** The audit state machine, in order (Workflow Matrix section 7). */
const STATUS_ORDER = ['Open', 'Reviewing', 'Posting', 'Ready to Close', 'Closed']

const STATUS_TONE = {
  Open: 'text-ink-gray-6',
  Reviewing: 'text-ink-blue-3',
  Posting: 'text-ink-blue-3',
  'Ready to Close': 'text-ink-green-3',
  Closed: 'text-ink-green-3',
}

const status = computed(() => props.audit?.audit_status || 'Open')

const progress = computed(() => {
  const index = STATUS_ORDER.indexOf(status.value)

  return Math.round((Math.max(index, 0) / (STATUS_ORDER.length - 1)) * 100)
})

const statusClass = computed(() => STATUS_TONE[status.value] || 'text-ink-gray-6')

const statusLabel = computed(() => t(`page.dashboard.audit.status.${keyOf(status.value)}`))

function keyOf(value) {
  return String(value).toLowerCase().replaceAll(' ', '_')
}
</script>
