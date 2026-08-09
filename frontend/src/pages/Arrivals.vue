<!--
  Arrivals board for the property's business date.

  One request returns the whole day, so the filter below is client side: a single
  property-day is small and re-fetching per filter would only add latency.

  This screen decides nothing. Check-in and room assignment are links to the
  screens that own those rules; nothing here mutates state.
-->
<template>
  <div>
    <PageHeader :title="t('page.arrivals.title')" :subtitle="property.active.value?.property_name || ''">
      <template #actions>
        <Button variant="subtle" :loading="board.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <LoadingState v-if="board.loading && !board.data" />
    <ErrorState v-else-if="board.error" :error="board.error" :on-retry="reload" />
    <EmptyState v-else-if="!rows.length" :message="t('page.arrivals.empty')" />

    <div v-else class="space-y-4 p-5">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div v-for="tile in tiles" :key="tile.key" class="rounded border border-outline-gray-1 px-3 py-2">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold text-ink-gray-9">{{ tile.value }}</p>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FormControl v-model="filter" type="select" :label="t('page.arrivals.filter')" :options="filterOptions" />
      </div>

      <EmptyState v-if="!visibleRows.length" :message="t('page.arrivals.filter_empty')" />

      <div v-else class="overflow-x-auto rounded border border-outline-gray-1">
        <table class="w-full min-w-max text-p-sm">
          <thead class="bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
            <tr>
              <th class="p-2 text-start">{{ t('page.arrivals.reservation') }}</th>
              <th class="p-2 text-start">{{ t('page.arrivals.guest') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.arrival') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.departure') }}</th>
              <th class="p-2 text-start">{{ t('page.arrivals.room_type') }}</th>
              <th class="p-2 text-start">{{ t('page.arrivals.room') }}</th>
              <th class="p-2 text-start">{{ t('page.arrivals.readiness') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.status') }}</th>
              <th class="p-2 text-start">{{ t('page.arrivals.guarantee') }}</th>
              <th class="p-2 text-start">{{ t('page.arrivals.deposit') }}</th>
              <th class="p-2 text-start">{{ t('page.arrivals.pax') }}</th>
              <th class="p-2 text-end">{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in visibleRows" :key="row.key" class="border-t border-outline-gray-1">
              <td class="p-2 font-medium whitespace-nowrap">
                <RouterLink
                  :to="{ name: 'Reservation', params: { id: row.reservation } }"
                  class="text-ink-blue-3 hover:underline"
                >
                  {{ row.reservation }}
                </RouterLink>
              </td>
              <td class="p-2">
                <span class="text-ink-gray-9">{{ row.guest_name }}</span>
                <Badge
                  v-if="row.vip_status"
                  class="ms-1"
                  :theme="vipStatusTheme(row.vip_status)"
                  variant="subtle"
                  :label="row.vip_status"
                />
                <Badge
                  v-if="row.is_blacklisted"
                  class="ms-1"
                  theme="red"
                  variant="subtle"
                  :label="t('common.blacklisted')"
                />
              </td>
              <td class="p-2 whitespace-nowrap">{{ formatDate(row.arrival_date) }}</td>
              <td class="p-2 whitespace-nowrap">{{ formatDate(row.departure_date) }}</td>
              <td class="p-2">{{ row.room_type_name || row.room_type }}</td>
              <td class="p-2 whitespace-nowrap">
                <span v-if="row.room_number" class="font-medium text-ink-gray-9">{{ row.room_number }}</span>
                <span v-else class="text-ink-gray-5">{{ t('page.arrivals.no_room_yet') }}</span>
              </td>
              <!--
                Housekeeping is only one of the four room dimensions; it is the
                one that decides whether a guest can walk in, so it is the one
                shown here. Occupancy, maintenance and inventory stay separate
                signals on the room rack rather than being merged into a verdict.
              -->
              <td class="p-2">
                <RoomStatusBadge v-if="row.assigned_room && row.housekeeping_status" :status="row.housekeeping_status" />
                <span v-else class="text-ink-gray-5">—</span>
              </td>
              <td class="p-2">
                <Badge
                  :theme="reservationStatusTheme(row.reservation_status)"
                  variant="subtle"
                  :label="row.reservation_status"
                />
              </td>
              <td class="p-2 whitespace-nowrap">
                <span v-if="row.guarantee_type && row.guarantee_type !== 'None'">{{ row.guarantee_type }}</span>
                <span v-else class="text-ink-gray-5">—</span>
              </td>
              <td class="p-2 whitespace-nowrap">
                <span v-if="row.deposit_outstanding > 0.005" class="text-ink-amber-3">
                  {{ t('page.arrivals.deposit_outstanding', { amount: formatCurrency(row.deposit_outstanding, row.currency) }) }}
                </span>
                <span v-else class="text-ink-gray-5">—</span>
              </td>
              <td class="p-2 whitespace-nowrap">{{ row.adults }}A {{ row.children }}C</td>
              <td class="p-2 text-end whitespace-nowrap">
                <RouterLink
                  :to="{ name: 'Reservation', params: { id: row.reservation } }"
                  class="text-ink-blue-3 hover:underline"
                >
                  {{ t('page.arrivals.action.open') }}
                </RouterLink>
                <!-- Room assignment lives on the reservation screen, which holds the lock. -->
                <RouterLink
                  v-if="!row.assigned_room && !row.is_checked_in"
                  :to="{ name: 'Reservation', params: { id: row.reservation } }"
                  class="ms-3 text-ink-blue-3 hover:underline"
                >
                  {{ t('page.arrivals.action.assign_room') }}
                </RouterLink>
                <RouterLink
                  v-if="!row.is_checked_in"
                  :to="{ name: 'CheckIn', params: { reservation: row.reservation } }"
                  class="ms-3 text-ink-blue-3 hover:underline"
                >
                  {{ t('page.arrivals.action.check_in') }}
                </RouterLink>
                <Badge
                  v-else
                  class="ms-3"
                  theme="green"
                  variant="subtle"
                  :label="t('page.arrivals.checked_in')"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import RoomStatusBadge from '@/components/RoomStatusBadge.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { arrivalsBoardResource } from '@/resources/frontOffice'
import { vipStatusTheme } from '@/resources/guests'
import { reservationStatusTheme } from '@/resources/reservations'
import { property } from '@/stores/property'
import { formatCurrency, formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const board = arrivalsBoardResource()

const filter = ref('all')

/** Each filter is a predicate over a row; the board itself is never re-fetched. */
const FILTERS = {
  all: () => true,
  confirmed: (row) => row.reservation_status === 'Confirmed',
  guaranteed: (row) => row.reservation_status === 'Guaranteed',
  assigned: (row) => Boolean(row.assigned_room),
  unassigned: (row) => !row.assigned_room,
  ready: (row) => Boolean(row.room_ready),
  not_ready: (row) => Boolean(row.assigned_room) && !row.room_ready,
  pending: (row) => !row.is_checked_in,
  checked_in: (row) => Boolean(row.is_checked_in),
}

// Computed, not a plain const: the language switcher changes the locale in
// place without reloading, so labels built once would stay in the old language.
const filterOptions = computed(() =>
  Object.keys(FILTERS).map((value) => ({ label: t(`page.arrivals.filter.${value}`), value })),
)

const rows = computed(() => board.data?.rows || [])

const visibleRows = computed(() => rows.value.filter(FILTERS[filter.value] || FILTERS.all))

const tiles = computed(() => {
  const s = board.data?.summary || {}

  return [
    { key: 'total', label: t('page.arrivals.total'), value: s.total ?? 0 },
    { key: 'pending', label: t('page.arrivals.pending'), value: s.pending ?? 0 },
    { key: 'checked_in', label: t('page.arrivals.checked_in'), value: s.checked_in ?? 0 },
    { key: 'assigned', label: t('page.arrivals.assigned'), value: s.assigned ?? 0 },
    { key: 'unassigned', label: t('page.arrivals.unassigned'), value: s.unassigned ?? 0 },
    { key: 'ready', label: t('page.arrivals.ready'), value: s.ready ?? 0 },
    { key: 'not_ready', label: t('page.arrivals.not_ready'), value: s.not_ready ?? 0 },
    { key: 'vip', label: t('page.arrivals.vip'), value: s.vip ?? 0 },
  ]
})

function reload() {
  board.fetch({ property: property.activeName.value })
}

watch(() => property.activeName.value, reload, { immediate: true })
</script>
