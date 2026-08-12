<!--
  Night Audit: the 3am business-date close. One person runs this screen, so it
  favours clarity over density — one clear statement of what is being closed,
  the day's figures, the exceptions that need attention, and the steps in the
  order they are meant to run.

  Close is disabled purely from the server's own `blocking_count`
  (`night_audit.get_current`); this screen never re-derives the
  blocking-severity rule that `night_audit.close()` itself enforces.
-->
<template>
  <div>
    <PageHeader :title="t('page.night_audit.title')" :subtitle="property.active.value?.property_name || ''">
      <template #actions>
        <Button variant="subtle" :loading="current.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
        <Button v-if="audit?.audit_status === 'Closed'" variant="subtle" theme="red" @click="reopenOpen = true">
          {{ t('page.night_audit.reopen') }}
        </Button>
      </template>
    </PageHeader>

    <LoadingState v-if="current.loading && !current.data" />

    <ErrorState v-else-if="current.error" :error="current.error" :on-retry="reload" />

    <div v-else class="space-y-5 p-5">
      <EmptyState v-if="!audit" :message="t('page.night_audit.no_audit')">
        <Button variant="solid" :loading="busy === 'start'" @click="doStart">
          {{ t('page.night_audit.start') }}
        </Button>
      </EmptyState>

      <template v-else>
        <ErrorMessage :message="actionError" />

        <!-- What is being closed, and where it stands, before anything else. -->
        <div class="flex flex-wrap items-center justify-between gap-4 rounded border border-outline-gray-1 p-4">
          <div>
            <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.night_audit.business_date') }}</p>
            <p class="text-2xl font-semibold text-ink-gray-9">{{ formatDate(audit.business_date) }}</p>
          </div>
          <div class="flex items-center gap-2">
            <Badge :theme="auditStatusTheme(audit.audit_status)" variant="subtle" :label="audit.audit_status" />
            <span v-if="audit.audit_status === 'Closed'" class="text-p-sm text-ink-gray-6">
              {{ t('page.night_audit.closed_statement', { date: formatDateTime(audit.closed_on) }) }}
            </span>
          </div>
        </div>

        <!-- The day's figures. -->
        <section>
          <h2 class="mb-2 text-base font-medium text-ink-gray-8">{{ t('page.night_audit.figures') }}</h2>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <div v-for="tile in figureTiles" :key="tile.key" class="rounded border border-outline-gray-1 px-3 py-2">
              <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
              <p class="mt-0.5 text-lg font-semibold" :class="tile.class || 'text-ink-gray-9'">{{ tile.value }}</p>
            </div>
          </div>
        </section>

        <!-- Exceptions: blocking ones must read as unmistakably different from warnings. -->
        <section>
          <h2 class="mb-2 text-base font-medium text-ink-gray-8">
            {{ t('page.night_audit.exceptions') }}
            <span class="text-p-sm font-normal text-ink-gray-5">({{ exceptions.length }})</span>
          </h2>

          <p v-if="!exceptions.length" class="text-p-sm text-ink-gray-6">{{ t('page.night_audit.no_exceptions') }}</p>

          <ul v-else class="space-y-2">
            <li
              v-for="row in exceptions"
              :key="row.name"
              class="flex flex-wrap items-start justify-between gap-3 rounded border p-3"
              :class="exceptionClass(row)"
            >
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <Badge :theme="severityTheme(row.severity)" variant="subtle" :label="row.severity" />
                  <span class="text-p-sm font-medium text-ink-gray-8">{{ row.type }}</span>
                  <Badge v-if="row.is_resolved" theme="green" variant="subtle" :label="t('page.night_audit.resolved')" />
                </div>
                <p class="mt-1 text-p-sm text-ink-gray-6">{{ row.description }}</p>
              </div>

              <Button v-if="!row.is_resolved" variant="subtle" @click="openException(row)">
                {{ t('page.night_audit.resolve') }}
              </Button>
            </li>
          </ul>
        </section>

        <!-- The close-out sequence, in the order it is meant to run. -->
        <section>
          <h2 class="mb-2 text-base font-medium text-ink-gray-8">{{ t('page.night_audit.steps') }}</h2>

          <ol class="space-y-2">
            <li
              v-for="(step, index) in steps"
              :key="step.key"
              class="flex flex-wrap items-center justify-between gap-3 rounded border p-3"
              :class="step.state === 'current' ? 'border-outline-blue-1 bg-surface-blue-1' : 'border-outline-gray-1'"
            >
              <div class="flex min-w-0 items-center gap-3">
                <span
                  class="flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-medium"
                  :class="step.state === 'done'
                    ? 'bg-surface-green-1 text-ink-green-3'
                    : step.state === 'current'
                      ? 'bg-surface-blue-2 text-ink-blue-3'
                      : 'bg-surface-gray-2 text-ink-gray-6'"
                >
                  <FeatherIcon v-if="step.state === 'done'" name="check" class="size-3.5" />
                  <span v-else>{{ index + 1 }}</span>
                </span>
                <div class="min-w-0">
                  <p class="font-medium text-ink-gray-9">{{ step.label }}</p>
                  <p class="text-p-sm text-ink-gray-6">{{ step.description }}</p>
                  <p v-if="step.key === 'close' && blockingCount > 0" class="mt-0.5 text-p-sm text-ink-red-3">
                    {{ t('page.night_audit.close_blocked', { count: blockingCount }) }}
                  </p>
                </div>
              </div>

              <Button
                variant="subtle"
                :theme="step.key === 'close' ? 'red' : 'gray'"
                :loading="busy === step.key"
                :disabled="step.key === 'close' && blockingCount > 0"
                @click="step.run"
              >
                {{ t('page.night_audit.run') }}
              </Button>
            </li>
          </ol>
        </section>
      </template>
    </div>

    <NightAuditExceptionDialog
      v-model="exceptionOpen"
      :audit="audit?.name"
      :exception="selectedException"
      @resolved="reload"
    />
    <NightAuditCloseDialog v-model="closeOpen" :audit="audit" @closed="reload" />
    <NightAuditReopenDialog v-model="reopenOpen" :audit="audit" @reopened="reload" />
  </div>
</template>

<script setup>
import { Badge, Button, ErrorMessage, FeatherIcon } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import NightAuditCloseDialog from '@/components/NightAuditCloseDialog.vue'
import NightAuditExceptionDialog from '@/components/NightAuditExceptionDialog.vue'
import NightAuditReopenDialog from '@/components/NightAuditReopenDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { hasField } from '@/resources/guests'
import {
  auditStatusTheme,
  markDueOutsResource,
  markNoShowsResource,
  nightAuditCurrentResource,
  postRoomChargesResource,
  reconcileNightAuditResource,
  reviewNightAuditResource,
  severityTheme,
  startNightAuditResource,
} from '@/resources/nightAudit'
import { property } from '@/stores/property'
import { normaliseError } from '@/utils/errors'
import { formatCurrency, formatDate, formatDateTime, formatNumber } from '@/utils/format'
import { t } from '@/utils/i18n'

const current = nightAuditCurrentResource()
const startResource = startNightAuditResource()
const reviewResource = reviewNightAuditResource()
const noShowsResource = markNoShowsResource()
const postChargesResource = postRoomChargesResource()
const dueOutsResource = markDueOutsResource()
const reconcileResource = reconcileNightAuditResource()

const busy = ref('')
const actionError = ref('')
const exceptionOpen = ref(false)
const selectedException = ref(null)
const closeOpen = ref(false)
const reopenOpen = ref(false)

const audit = computed(() => current.data?.audit || null)
const exceptions = computed(() => current.data?.exceptions || [])
const counts = computed(() => current.data?.counts || {})
const figures = computed(() => current.data?.figures || {})
const blockingCount = computed(() => current.data?.blocking_count ?? 0)

const figureTiles = computed(() => {
  const c = counts.value
  const f = figures.value
  const currency = f.currency

  return [
    { key: 'arrivals_expected', label: t('page.night_audit.arrivals_expected'), value: c.arrivals_expected ?? 0 },
    { key: 'arrivals_completed', label: t('page.night_audit.arrivals_completed'), value: c.arrivals_completed ?? 0 },
    { key: 'departures_expected', label: t('page.night_audit.departures_expected'), value: c.departures_expected ?? 0 },
    { key: 'departures_completed', label: t('page.night_audit.departures_completed'), value: c.departures_completed ?? 0 },
    { key: 'in_house_rooms', label: t('page.night_audit.in_house_rooms'), value: c.in_house_rooms ?? 0 },
    { key: 'rooms_charged', label: t('page.night_audit.rooms_charged'), value: c.rooms_charged ?? 0 },
    { key: 'charges_posted', label: t('page.night_audit.charges_posted'), value: c.charges_posted ?? 0 },
    {
      key: 'postings_failed',
      label: t('page.night_audit.postings_failed'),
      value: c.postings_failed ?? 0,
      class: c.postings_failed ? 'text-ink-red-3' : 'text-ink-gray-9',
    },
    // The three folio-derived totals are omitted by the server for a caller
    // without Guest Folio read (16.7.5-R1B), so they are spliced in only when
    // disclosed. `?? 0` here would print "Outstanding balance QAR 0.00" and read
    // as "nothing is owed" — the same lie `Dashboard.vue` and `Checkout.vue`
    // guard against. Only six roles reach this screen today and all six hold
    // Guest Folio read, so this is defence against the next nav change rather
    // than a live leak.
    ...(hasField(f, 'room_revenue')
      ? [{ key: 'room_revenue', label: t('page.night_audit.room_revenue'), value: formatCurrency(f.room_revenue, currency) }]
      : []),
    ...(hasField(f, 'payments_received')
      ? [{ key: 'payments_received', label: t('page.night_audit.payments_received'), value: formatCurrency(f.payments_received, currency) }]
      : []),
    ...(hasField(f, 'outstanding_balance')
      ? [
          {
            key: 'outstanding_balance',
            label: t('page.night_audit.outstanding_balance'),
            value: formatCurrency(f.outstanding_balance, currency),
          },
        ]
      : []),
    { key: 'occupancy', label: t('page.night_audit.occupancy'), value: `${formatNumber(f.occupancy_percentage ?? 0, 1)}%` },
    { key: 'adr', label: t('page.night_audit.adr'), value: formatCurrency(f.adr ?? 0, currency) },
    { key: 'revpar', label: t('page.night_audit.revpar'), value: formatCurrency(f.revpar ?? 0, currency) },
  ]
})

const STATUS_INDEX = { Open: 0, Reviewing: 1, Posting: 2, 'Ready to Close': 3, Closed: 4 }
const STEP_STATUS_INDEX = {
  start: 0,
  review: 1,
  mark_no_shows: 1,
  post_room_charges: 2,
  mark_due_outs: 2,
  reconcile: 3,
  close: 4,
}

function stepState(key) {
  const currentIndex = STATUS_INDEX[audit.value?.audit_status] ?? 0
  const own = STEP_STATUS_INDEX[key]

  if (own < currentIndex) return 'done'
  if (own === currentIndex) return 'current'
  return 'pending'
}

const steps = computed(() => [
  {
    key: 'start',
    label: t('page.night_audit.step_start'),
    description: t('page.night_audit.step_start_desc'),
    state: stepState('start'),
    run: doStart,
  },
  {
    key: 'review',
    label: t('page.night_audit.step_review'),
    description: t('page.night_audit.step_review_desc'),
    state: stepState('review'),
    run: () => run('review', () => reviewResource.submit({ audit: audit.value.name })),
  },
  {
    key: 'mark_no_shows',
    label: t('page.night_audit.step_no_shows'),
    description: t('page.night_audit.step_no_shows_desc'),
    state: stepState('mark_no_shows'),
    run: () => run('mark_no_shows', () => noShowsResource.submit({ audit: audit.value.name })),
  },
  {
    key: 'post_room_charges',
    label: t('page.night_audit.step_post_charges'),
    description: t('page.night_audit.step_post_charges_desc'),
    state: stepState('post_room_charges'),
    run: () => run('post_room_charges', () => postChargesResource.submit({ audit: audit.value.name })),
  },
  {
    key: 'mark_due_outs',
    label: t('page.night_audit.step_due_outs'),
    description: t('page.night_audit.step_due_outs_desc'),
    state: stepState('mark_due_outs'),
    run: () => run('mark_due_outs', () => dueOutsResource.submit({ audit: audit.value.name })),
  },
  {
    key: 'reconcile',
    label: t('page.night_audit.step_reconcile'),
    description: t('page.night_audit.step_reconcile_desc'),
    state: stepState('reconcile'),
    run: () => run('reconcile', () => reconcileResource.submit({ audit: audit.value.name })),
  },
  {
    key: 'close',
    label: t('page.night_audit.step_close'),
    description: t('page.night_audit.step_close_desc'),
    state: stepState('close'),
    // Closing the business date always asks for explicit confirmation
    // (Frontend Standards section 8); the button here only opens that dialog.
    run: () => {
      closeOpen.value = true
    },
  },
])

function exceptionClass(row) {
  if (row.is_resolved) return 'border-outline-gray-1 opacity-70'
  if (row.severity === 'Blocking') return 'border-outline-red-1 bg-surface-red-1'
  if (row.severity === 'Warning') return 'border-outline-amber-1 bg-surface-amber-1'
  return 'border-outline-gray-1'
}

function reload() {
  current.fetch({ property: property.activeName.value })
}

async function run(key, fn) {
  busy.value = key
  actionError.value = ''

  try {
    await fn()
    reload()
  } catch (error) {
    actionError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

function doStart() {
  return run('start', () => startResource.submit({ property: property.activeName.value }))
}

function openException(row) {
  selectedException.value = row
  exceptionOpen.value = true
}

watch(() => property.activeName.value, reload, { immediate: true })
</script>
