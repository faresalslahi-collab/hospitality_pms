<!--
  The room service board: a queue of what the kitchen still has to cook.

  Oldest order first, because that is the one that has been waiting longest.
  Until now ordering had no screen at all and ran through the API, which meant
  a waiter could not take an order in this product. The rules are unchanged —
  the menu prices every line and delivery charges the folio once — but they are
  now reachable by the people who do the work.
-->
<template>
  <div>
    <PageHeader :title="t('page.kitchen.title')" :subtitle="t('page.kitchen.subtitle')">
      <template #actions>
        <Button v-if="canOrder" variant="solid" @click="createOpen = true">
          <template #prefix><FeatherIcon name="plus" class="size-4" /></template>
          {{ t('page.kitchen.new_order') }}
        </Button>
        <Button variant="subtle" :loading="board.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <LoadingState v-if="board.loading && !board.data" />
    <ErrorState v-else-if="board.error" :error="board.error" :on-retry="reload" />

    <div v-else class="space-y-4 p-5">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <div v-for="tile in tiles" :key="tile.key" class="rounded border border-outline-gray-1 px-3 py-2">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold text-ink-gray-9">{{ tile.value }}</p>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FormControl
          v-model="filter"
          type="select"
          :label="t('page.kitchen.filter')"
          :options="filterOptions"
        />
        <div class="flex items-end">
          <label class="flex items-center gap-2 text-p-sm text-ink-gray-7">
            <input v-model="includeClosed" type="checkbox" class="size-4" @change="reload" />
            {{ t('page.kitchen.show_delivered') }}
          </label>
        </div>
      </div>

      <EmptyState v-if="!orders.length" :message="t('page.kitchen.empty')" />
      <EmptyState v-else-if="!visibleOrders.length" :message="t('page.kitchen.filter_empty')" />

      <div v-else class="overflow-x-auto rounded border border-outline-gray-1">
        <table class="w-full min-w-max text-p-sm">
          <thead class="bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
            <tr>
              <th class="p-2 text-start">{{ t('page.kitchen.order') }}</th>
              <th class="p-2 text-start">{{ t('page.kitchen.room') }}</th>
              <th v-if="showGuest" class="p-2 text-start">{{ t('page.kitchen.guest') }}</th>
              <th class="p-2 text-start">{{ t('page.kitchen.type') }}</th>
              <th class="p-2 text-start">{{ t('page.kitchen.items') }}</th>
              <th class="p-2 text-start">{{ t('page.kitchen.placed_at') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.status') }}</th>
              <th class="p-2 text-end">{{ t('page.kitchen.total') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in visibleOrders"
              :key="row.name"
              class="cursor-pointer border-t border-outline-gray-1 hover:bg-surface-gray-1"
              @click="openOrder(row)"
            >
              <td class="p-2 font-medium text-ink-gray-9">{{ row.name }}</td>
              <td class="p-2">{{ row.room || '—' }}</td>
              <td v-if="showGuest" class="p-2">{{ row.guest_name || '—' }}</td>
              <td class="p-2">{{ row.order_type }}</td>
              <td class="p-2">{{ row.item_count }}</td>
              <td class="p-2 whitespace-nowrap">{{ formatDateTime(row.ordered_on) }}</td>
              <td class="p-2">
                <Badge
                  :theme="orderStatusTheme(row.order_status)"
                  variant="subtle"
                  :label="row.order_status"
                />
              </td>
              <td class="p-2 text-end whitespace-nowrap">
                {{ formatCurrency(row.total_amount, row.currency || property.currency.value) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <CreateRoomServiceOrderDialog v-model="createOpen" @created="onCreated" />
    <RoomServiceOrderDialog v-model="detailOpen" :order-name="selected" @changed="reload" />
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, FormControl, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import CreateRoomServiceOrderDialog from '@/components/CreateRoomServiceOrderDialog.vue'
import PageHeader from '@/components/PageHeader.vue'
import RoomServiceOrderDialog from '@/components/RoomServiceOrderDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { KITCHEN_ROLES, orderBoardResource, orderStatusTheme } from '@/resources/kitchen'
import { property } from '@/stores/property'
import { session } from '@/stores/session'
import { formatCurrency, formatDateTime } from '@/utils/format'
import { t } from '@/utils/i18n'

const board = orderBoardResource()

const createOpen = ref(false)
const detailOpen = ref(false)
const selected = ref('')
const filter = ref('all')
const includeClosed = ref(false)

const canOrder = computed(() => session.hasRole(KITCHEN_ROLES))

/** Predicates over the board already in memory; no filter re-fetches it. */
const FILTERS = {
  all: () => true,
  placed: (row) => row.order_status === 'Placed',
  preparing: (row) => row.order_status === 'Preparing',
  ready: (row) => row.order_status === 'Ready',
  delivered: (row) => row.order_status === 'Delivered',
}

// Computed, not a plain const: switching language must relabel the options.
const filterOptions = computed(() =>
  Object.keys(FILTERS).map((value) => ({ label: t(`page.kitchen.filter.${value}`), value })),
)

const orders = computed(() => board.data?.orders || [])
const visibleOrders = computed(() => orders.value.filter(FILTERS[filter.value] || FILTERS.all))

/**
 * Whether the server disclosed who the order is for.
 *
 * Since 16.7.4 the board omits `guest_name` for a caller who may not read Guest
 * — every kitchen role, which holds no Guest permission at any permlevel. The
 * column is dropped rather than filled with a dash, because a dash reads as "no
 * guest on this order", and a room service order always has one.
 *
 * Presence, never truthiness: a guest whose name happens to be blank is still a
 * disclosed guest.
 */
const showGuest = computed(() =>
  orders.value.some((order) => Object.prototype.hasOwnProperty.call(order, 'guest_name')),
)

const tiles = computed(() => {
  const s = board.data?.summary || {}

  return [
    { key: 'open', label: t('page.kitchen.open'), value: s.open ?? 0 },
    { key: 'placed', label: t('page.kitchen.placed'), value: s.placed ?? 0 },
    { key: 'preparing', label: t('page.kitchen.preparing'), value: s.preparing ?? 0 },
    { key: 'ready', label: t('page.kitchen.ready'), value: s.ready ?? 0 },
    {
      key: 'value',
      label: t('page.kitchen.open_value'),
      value: formatCurrency(s.open_value ?? 0, property.currency.value),
    },
  ]
})

function openOrder(row) {
  selected.value = row.name
  detailOpen.value = true
}

function onCreated() {
  toast.success(t('page.kitchen.order_placed'))
  reload()
}

function reload() {
  board.fetch({
    property: property.activeName.value,
    include_closed: includeClosed.value ? 1 : 0,
  })
}

watch(() => property.activeName.value, reload, { immediate: true })
</script>
