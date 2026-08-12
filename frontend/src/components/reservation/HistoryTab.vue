<!--
  History: the booking's own record, written by the server and readable only.

  `Reservation Log` is a purpose-built audit DocType written inside
  `reservations._transition`, so this tab never goes near Frappe's `Version` rows —
  and never puts raw document JSON in front of a reservation agent, which is how a
  screen ends up disclosing fields nobody reviewed.

  **No raw blob reaches this component and none leaves it.** The endpoint filters
  each log row's `details` to an allow list before publishing it; this tab then
  renders those keys as labelled pairs. There is no `JSON.stringify` here, and a
  nested object — which cannot be stated as a pair — is dropped rather than printed,
  because "[object Object]" and a serialised blob are the same disclosure risk with
  different punctuation.

  There is no edit control, no delete and no "add note". A note about this booking
  belongs on the Notes tab, and the hint there says so: nothing an operator writes
  may look like part of the audit trail.
-->
<template>
  <div class="space-y-3">
    <p class="text-p-sm text-ink-gray-6">{{ t('page.reservation.history.immutable') }}</p>

    <OperationalDataTable
      :columns="columns"
      :rows="rows"
      row-key="name"
      :loading="loading"
      :error="error"
      :empty-message="t('page.reservation.history.empty')"
      :aria-label="t('page.reservation.tab.history')"
      dense
    >
      <!-- A permission failure is not a fault this user can retry out of. -->
      <template #error="{ error: rowError, details }">
        <PermissionDenied v-if="details.kind === 'permission'" :message="details.message" />
        <ErrorState v-else :error="rowError" :on-retry="onRetry" />
      </template>
    </OperationalDataTable>
  </div>
</template>

<script setup>
import { computed } from 'vue'

import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import PermissionDenied from '@/components/states/PermissionDenied.vue'
import { formatCurrency, formatDate, formatDateTime } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** `entries` from `get_history`, in the order the server sent them. */
  entries: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: [Object, String], default: null },
  /** The reservation's currency, for the two detail keys that are amounts. */
  currency: { type: String, default: null },
})

const emit = defineEmits(['retry'])

/**
 * Detail keys that read as a label and a value.
 *
 * Only keys with an existing translation are labelled; the rest fall back to the
 * server's own key name, which is honest and visible in review rather than being
 * dropped or given wording nobody approved.
 */
const DETAIL_LABEL_KEY = {
  room_type: 'page.arrivals.room_type',
  assigned_room: 'page.reservation.assigned',
  arrival_date: 'page.reservations.arrival',
  departure_date: 'page.reservations.departure',
  nights: 'page.reservations.nights',
  rate_plan: 'page.reservation.rooms.rate_plan',
}

/** Detail keys that are amounts, and already have a sentence that qualifies them. */
const DETAIL_SENTENCE_KEY = {
  cancellation_charge: 'page.arrivals.cancel_charge',
  no_show_charge: 'page.arrivals.no_show_charge',
}

const DATE_DETAIL_KEYS = new Set(['arrival_date', 'departure_date'])

const columns = computed(() => [
  { key: 'transition', label: t('page.reservation.history.change'), primary: true },
  { key: 'changed_by', label: t('page.reservation.history.who') },
  { key: 'when', label: t('page.reservation.history.when'), nowrap: true },
  { key: 'reason', label: t('page.reservation.history.reason') },
  { key: 'details', label: t('page.arrivals.action.details') },
])

/**
 * One row per log entry, every cell already a string.
 *
 * Formatted here rather than in a cell slot so the narrow card rendering shows the
 * same text as the table: a phone in a corridor is where an agent reads this.
 */
const rows = computed(() =>
  props.entries.map((entry) => ({
    name: entry.name,
    transition: transitionText(entry),
    changed_by: entry.changed_by || '',
    when: formatDateTime(entry.changed_at),
    reason: entry.reason || '',
    details: detailText(entry.details),
  })),
)

/** The first record of a booking has nothing to move from. */
function transitionText(entry) {
  if (!entry.from_status) return t('page.reservation.history.created')

  return t('page.reservation.history.transition', {
    from_status: entry.from_status,
    to_status: entry.to_status,
  })
}

function detailText(details) {
  if (!details || typeof details !== 'object') return ''

  return Object.entries(details)
    .map(([key, value]) => detailPair(key, value))
    .filter(Boolean)
    .join(' · ')
}

function detailPair(key, value) {
  if (value === null || value === undefined || value === '') return ''

  // A nested object cannot be stated as a pair, and printing it is the blob this
  // component exists to refuse.
  if (typeof value === 'object' && !Array.isArray(value)) return ''

  const sentence = DETAIL_SENTENCE_KEY[key]

  if (sentence) return t(sentence, { amount: formatCurrency(value, props.currency) })

  const labelKey = DETAIL_LABEL_KEY[key]
  const label = labelKey ? t(labelKey) : key

  return `${label}: ${detailValue(key, value)}`
}

function detailValue(key, value) {
  if (typeof value === 'boolean') return t(value ? 'common.yes' : 'common.no')
  if (Array.isArray(value)) return value.join(', ')
  if (DATE_DETAIL_KEYS.has(key)) return formatDate(value)

  return String(value)
}

function onRetry() {
  emit('retry')
}
</script>
