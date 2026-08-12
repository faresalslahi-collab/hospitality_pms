<!--
  Reservations: every booking this guest is on, paged from the server.

  Gated on `Reservation.read`, not on the guest being readable — the page never
  renders this tab at all unless `disclosure.reservation` is true, and the
  endpoint refuses independently, so the check exists on both sides of the wire
  rather than only in the UI.

  Scoped to the caller's permitted properties by the server. A guest is
  estate-wide (the same person stays in Doha this year and Dubai next) but their
  bookings belong to properties, and a desk restricted to one of them sees one of
  them.

  Rows include bookings where the guest travelled as a companion rather than as
  the lead name, because a history that quietly drops those reads as "no
  history" rather than as a partial one.

  No folio figure and no corporate detail appears here, however plainly a row
  "belongs" to the same guest: those are different DocTypes with different reader
  sets, and the tab that owns each is gated separately.
-->
<template>
  <OperationalDataTable
    :columns="columns"
    :rows="rows"
    row-key="name"
    :loading="loading"
    :error="error"
    :page="page"
    :page-length="pageLength"
    :empty-message="t('page.guest_profile.no_reservations')"
    :aria-label="t('page.guest_profile.tab.reservations')"
    :actions="actions"
    clickable-rows
    dense
    @page-change="$emit('page-change', $event)"
    @row-click="open"
    @row-action="onRowAction"
  >
    <template #error="{ error: rowError, details }">
      <PermissionDenied v-if="details.kind === 'permission'" :message="details.message" />
      <ErrorState v-else :error="rowError" :on-retry="onRetry" />
    </template>
  </OperationalDataTable>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import PermissionDenied from '@/components/states/PermissionDenied.vue'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  reservations: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: [Object, String], default: null },
  page: { type: Number, default: 1 },
  pageLength: { type: Number, default: 20 },
})

const emit = defineEmits(['page-change', 'retry'])

const router = useRouter()

const columns = computed(() => [
  { key: 'name', label: t('page.guest_profile.reservation'), primary: true },
  { key: 'property', label: t('page.guest_profile.property'), hideBelow: 'md' },
  { key: 'reservation_status', label: t('page.guest_profile.status') },
  { key: 'arrival_date', label: t('page.guest_profile.arrival'), nowrap: true },
  { key: 'departure_date', label: t('page.guest_profile.departure'), nowrap: true },
  { key: 'total_rooms', label: t('page.guest_profile.rooms'), align: 'end' },
  { key: 'booking_source', label: t('page.guest_profile.booking_source'), hideBelow: 'lg' },
])

const actions = computed(() => [
  { key: 'open', label: t('page.guest_profile.open_reservation') },
])

const rows = computed(() =>
  (props.reservations || []).map((row) => ({
    name: row.name,
    property: row.property || '',
    reservation_status: row.reservation_status || '',
    arrival_date: row.arrival_date ? formatDate(row.arrival_date) : '',
    departure_date: row.departure_date ? formatDate(row.departure_date) : '',
    total_rooms: row.total_rooms == null ? '' : String(row.total_rooms),
    booking_source: row.booking_source || '',
  })),
)

/** Into the 16.7.2 Reservation Workspace, by route name. */
function open(row) {
  router.push({ name: 'Reservation', params: { id: row.name } })
}

function onRowAction({ row }) {
  open(row)
}

function onRetry() {
  emit('retry')
}
</script>
