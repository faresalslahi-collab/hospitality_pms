<!--
  Departures board for the property's business date.

  One request returns the whole day, including each stay's checkout blockers,
  which the server has already worded and translated. The filter below is client
  side for the same reason as the arrivals board.

  `can_check_out` is the server's answer and is never recomputed here. A blocked
  stay still shows its Check out link, because the checkout screen is where a
  manager resolves the blocker; the badge explains why it is not a clean exit.
-->
<template>
  <div>
    <PageHeader :title="t('page.departures.title')" :subtitle="property.active.value?.property_name || ''">
      <template #actions>
        <Button variant="subtle" :loading="board.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <LoadingState v-if="board.loading && !board.data" />
    <ErrorState v-else-if="board.error" :error="board.error" :on-retry="reload" />
    <EmptyState v-else-if="!rows.length" :message="t('page.departures.empty')" />

    <div v-else class="space-y-4 p-5">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div v-for="tile in tiles" :key="tile.key" class="rounded border border-outline-gray-1 px-3 py-2">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold text-ink-gray-9">{{ tile.value }}</p>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FormControl v-model="filter" type="select" :label="t('page.departures.filter')" :options="filterOptions" />
      </div>

      <EmptyState v-if="!visibleRows.length" :message="t('page.departures.filter_empty')" />

      <div v-else class="overflow-x-auto rounded border border-outline-gray-1">
        <table class="w-full min-w-max text-p-sm">
          <thead class="bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
            <tr>
              <th class="p-2 text-start">{{ t('page.departures.guest') }}</th>
              <th class="p-2 text-start">{{ t('page.departures.room') }}</th>
              <th class="p-2 text-start">{{ t('page.departures.stay') }}</th>
              <th class="p-2 text-start">{{ t('page.departures.folio') }}</th>
              <th class="p-2 text-start">{{ t('page.departures.balance') }}</th>
              <th class="p-2 text-start">{{ t('page.departures.status') }}</th>
              <th class="p-2 text-start">{{ t('page.departures.readiness') }}</th>
              <th class="p-2 text-end">{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in visibleRows" :key="row.key" class="border-t border-outline-gray-1 align-top">
              <td class="p-2">
                <span class="text-ink-gray-9">{{ row.guest_name }}</span>
                <Badge
                  v-if="row.vip_status"
                  class="ms-1"
                  :theme="vipStatusTheme(row.vip_status)"
                  variant="subtle"
                  :label="row.vip_status"
                />
              </td>
              <td class="p-2 font-medium whitespace-nowrap">
                <RouterLink
                  :to="{ name: 'Stay', params: { id: row.stay } }"
                  class="text-ink-blue-3 hover:underline"
                >
                  {{ row.room_number }}
                </RouterLink>
              </td>
              <td class="p-2 whitespace-nowrap">
                <span>{{ formatDate(row.arrival_date) }} – {{ formatDate(row.departure_date) }}</span>
                <span class="ms-2 text-ink-gray-5">{{ row.nights }} {{ t('page.reservations.nights') }}</span>
              </td>
              <td class="p-2 whitespace-nowrap">
                <RouterLink
                  v-if="row.folio"
                  :to="{ name: 'Folio', params: { id: row.folio } }"
                  class="text-ink-blue-3 hover:underline"
                >
                  {{ row.folio }}
                </RouterLink>
                <span v-else class="text-ink-gray-5">—</span>
              </td>
              <!-- Split folios are counted, not summed into the primary balance: the
                   two numbers settle separately and merging them would mislead. -->
              <td class="p-2 whitespace-nowrap">
                <Badge
                  :theme="balanceTheme(row.balance)"
                  variant="subtle"
                  :label="formatCurrency(row.balance, row.currency)"
                />
                <p v-if="row.related_folios > 0" class="mt-1 text-xs text-ink-gray-5">
                  {{ t('page.departures.split_folios', { count: row.related_folios }) }}
                </p>
              </td>
              <td class="p-2">
                <Badge :theme="stayStatusTheme(row.stay_status)" variant="subtle" :label="row.stay_status" />
              </td>
              <td class="p-2">
                <Badge
                  v-if="row.is_checked_out"
                  theme="gray"
                  variant="subtle"
                  :label="t('page.departures.checked_out')"
                />
                <Badge
                  v-else-if="row.can_check_out"
                  theme="green"
                  variant="subtle"
                  :label="t('page.departures.ready')"
                />
                <template v-else>
                  <Badge theme="orange" variant="subtle" :label="t('page.departures.blocked')" />
                  <!-- Blockers arrive already worded and translated by the server. -->
                  <ul v-if="row.blockers?.length" class="mt-1 list-disc ps-4 text-xs text-ink-gray-6">
                    <li v-for="(blocker, index) in row.blockers" :key="index">{{ blocker }}</li>
                  </ul>
                </template>
              </td>
              <td class="p-2 text-end whitespace-nowrap">
                <RouterLink
                  v-if="row.folio"
                  :to="{ name: 'Folio', params: { id: row.folio } }"
                  class="text-ink-blue-3 hover:underline"
                >
                  {{ t('page.departures.action.open_folio') }}
                </RouterLink>
                <RouterLink
                  v-if="!row.is_checked_out"
                  :to="{ name: 'Checkout', params: { stay: row.stay } }"
                  class="ms-3 text-ink-blue-3 hover:underline"
                >
                  {{ t('page.departures.action.checkout') }}
                </RouterLink>
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
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { balanceTheme, departuresBoardResource } from '@/resources/frontOffice'
import { stayStatusTheme } from '@/resources/stays'
import { vipStatusTheme } from '@/resources/guests'
import { property } from '@/stores/property'
import { formatCurrency, formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const board = departuresBoardResource()

const filter = ref('all')

/** Predicates over the rows already in memory; no filter re-fetches the board. */
const FILTERS = {
  all: () => true,
  due_out: (row) => !row.is_checked_out,
  ready: (row) => Boolean(row.can_check_out),
  balance_pending: (row) => Math.abs(Number(row.balance || 0) + Number(row.related_balance || 0)) > 0.005,
  checked_out: (row) => Boolean(row.is_checked_out),
}

// Computed, not a plain const: the language switcher changes the locale in
// place without reloading, so labels built once would stay in the old language.
const filterOptions = computed(() =>
  Object.keys(FILTERS).map((value) => ({ label: t(`page.departures.filter.${value}`), value })),
)

const rows = computed(() => board.data?.rows || [])

const visibleRows = computed(() => rows.value.filter(FILTERS[filter.value] || FILTERS.all))

const tiles = computed(() => {
  const s = board.data?.summary || {}
  const currency = board.data?.currency || property.currency.value

  return [
    { key: 'total', label: t('page.departures.total'), value: s.total ?? 0 },
    { key: 'due_out', label: t('page.departures.due_out'), value: s.due_out ?? 0 },
    { key: 'checked_out', label: t('page.departures.checked_out'), value: s.checked_out ?? 0 },
    { key: 'ready', label: t('page.departures.ready'), value: s.ready ?? 0 },
    { key: 'blocked', label: t('page.departures.blocked'), value: s.blocked ?? 0 },
    { key: 'balance_pending', label: t('page.departures.balance_pending'), value: s.balance_pending ?? 0 },
    {
      key: 'outstanding',
      label: t('page.departures.outstanding'),
      value: formatCurrency(s.outstanding_balance ?? 0, currency),
    },
  ]
})

function reload() {
  board.fetch({ property: property.activeName.value })
}

watch(() => property.activeName.value, reload, { immediate: true })
</script>
