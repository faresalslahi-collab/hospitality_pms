<!--
  Stays: where this guest has actually slept, paged from the server.

  Gated on `Stay.read` and scoped to permitted properties, independently of the
  Reservations tab beside it — the two DocTypes have different writer sets and
  the product has already shipped one board that assumed otherwise.

  `room` is the room the guest was really in. Since 16.7.3 that is also the room
  the inventory row names, and the type with it: `change_room` used to move the
  Stay and leave `Reservation Room.room_type` naming the type the booking was
  made for, so a guest upgraded into a suite stayed "in" a standard room as far
  as availability was concerned. The booked room is a reservation concept and is
  shown on the Reservations tab, where it is labelled as such — the two are not
  presented as the same thing.

  No balance and no folio total appears here. A stay row carries its folio's
  identifier only when the caller may read Guest Folio, and the money itself
  lives on the Folios tab behind its own gate.
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
    :empty-message="t('page.guest_profile.no_stays')"
    :aria-label="t('page.guest_profile.tab.stays')"
    dense
    @page-change="$emit('page-change', $event)"
  >
    <template #error="{ error: rowError, details }">
      <PermissionDenied v-if="details.kind === 'permission'" :message="details.message" />
      <ErrorState v-else :error="rowError" :on-retry="onRetry" />
    </template>
  </OperationalDataTable>
</template>

<script setup>
import { computed } from 'vue'

import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import PermissionDenied from '@/components/states/PermissionDenied.vue'
import { formatDate, formatDateTime } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  stays: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: [Object, String], default: null },
  page: { type: Number, default: 1 },
  pageLength: { type: Number, default: 20 },
})

const emit = defineEmits(['page-change', 'retry'])

const columns = computed(() => [
  { key: 'name', label: t('page.guest_profile.stay'), primary: true },
  { key: 'property', label: t('page.guest_profile.property'), hideBelow: 'md' },
  { key: 'room', label: t('page.guest_profile.room') },
  { key: 'room_type', label: t('page.guest_profile.room_type'), hideBelow: 'lg' },
  { key: 'stay_status', label: t('page.guest_profile.status') },
  { key: 'arrival_date', label: t('page.guest_profile.arrival'), nowrap: true },
  { key: 'departure_date', label: t('page.guest_profile.departure'), nowrap: true },
  { key: 'checked_out_on', label: t('page.guest_profile.checked_out'), hideBelow: 'lg', nowrap: true },
])

const rows = computed(() =>
  (props.stays || []).map((row) => ({
    name: row.name,
    property: row.property || '',
    room: row.room || '',
    room_type: row.room_type || '',
    stay_status: row.stay_status || '',
    arrival_date: row.arrival_date ? formatDate(row.arrival_date) : '',
    departure_date: row.departure_date ? formatDate(row.departure_date) : '',
    checked_out_on: row.checked_out_on ? formatDateTime(row.checked_out_on) : '',
  })),
)

function onRetry() {
  emit('retry')
}
</script>
