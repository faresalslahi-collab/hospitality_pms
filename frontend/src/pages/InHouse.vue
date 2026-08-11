<!--
  In-house board, on the shared operational table.

  This build modernises the board's table infrastructure and gives it the quick
  actions its data already supports. It is not the 16.7.1 In-House Command Centre,
  and it deliberately does not pretend to be: `stays.in_house` returns thirteen
  fields, and everything absent from them is absent from this screen.

  What that rules out, on purpose:

  - No balance column. The row carries no `balance` and no `folio_status`.
  - No checkout readiness badge. The row carries no `can_check_out` and no
    `blockers`, so any badge here would be a guess, and a guess about whether a
    guest may leave is the worst kind. Checkout is plain navigation to the screen
    that asks the server.
  - No alerts column. The row carries no `vip_status` and no `is_blacklisted`, and
    an empty column would read as a clearance this board never checked.

  The rate is shown in the active property's currency, as it was before this
  migration: the row carries no `currency` of its own. That is an assumption, and
  the fix — `currency` in `services.stays.get_in_house` — is recorded for 16.7.1.
-->
<template>
  <div>
    <PageHeader :title="t('page.in_house.title')" :subtitle="property.active.value?.property_name || ''">
      <template #actions>
        <Button variant="subtle" :loading="board.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <div class="space-y-4 p-5">
      <div v-if="stays.length" class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div v-for="tile in tiles" :key="tile.key" class="rounded border border-outline-gray-1 px-3 py-2">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold text-ink-gray-9">{{ tile.value }}</p>
        </div>
      </div>

      <OperationalDataTable
        :columns="columns"
        :rows="visibleRows"
        row-key="name"
        :loading="board.loading"
        :error="board.error"
        :empty-message="emptyMessage"
        :actions="actions"
        searchable
        :search="search"
        :search-label="t('page.in_house.search_label')"
        :aria-label="t('page.in_house.title')"
        sticky-header
        @search-change="search = $event"
        @row-action="onRowAction"
      >
        <template #toolbar>
          <div class="w-full sm:w-56">
            <FormControl
              v-model="filter"
              type="select"
              size="sm"
              :label="t('page.in_house.filter')"
              :options="filterOptions"
            />
          </div>
        </template>

        <template #error="{ error }">
          <ErrorState :error="error" :on-retry="reload" />
        </template>

        <!--
          `row.room` is the Hotel Room docname, which is the room code
          (PROPERTY-ROOMNUMBER) rather than the room number the other two boards
          show. The column keeps its existing neutral label; `room_number` in the
          endpoint is a 16.7.1 item.
        -->
        <template #cell:room="{ row }">
          <RouterLink
            :to="{ name: 'Stay', params: { id: row.name } }"
            class="font-medium text-ink-blue-3 hover:underline"
          >
            {{ row.room }}
          </RouterLink>
        </template>

        <template #cell:pax="{ row }">{{ row.adults }}A {{ row.children }}C</template>

        <!-- The property's currency, not the row's: the row does not carry one. -->
        <template #cell:room_rate="{ row }">
          <MoneyDisplay :value="row.room_rate" :currency="property.currency.value" />
        </template>
      </OperationalDataTable>
    </div>

    <ActionDrawer
      v-model="drawerOpen"
      :title="selected?.guest_name || ''"
      :subtitle="selected ? `${t('page.in_house.room')} ${selected.room}` : ''"
    >
      <dl v-if="selected" class="space-y-3">
        <div v-for="item in detailItems" :key="item.label">
          <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ item.label }}</dt>
          <dd class="text-p-sm text-ink-gray-8">{{ item.value }}</dd>
        </div>
        <div>
          <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.in_house.rate') }}</dt>
          <dd class="text-p-sm text-ink-gray-8">
            <MoneyDisplay :value="selected.room_rate" :currency="property.currency.value" />
          </dd>
        </div>
      </dl>

      <template #footer>
        <Button variant="subtle" @click="openStay">{{ t('page.in_house.action.open_stay') }}</Button>
        <Button variant="subtle" @click="openGuest">{{ t('page.in_house.action.guest_profile') }}</Button>
        <Button v-if="selected?.folio" variant="subtle" @click="openFolio">
          {{ t('page.in_house.action.folio') }}
        </Button>
        <template v-if="canOperate">
          <Button variant="subtle" @click="() => openStayDialog('move')">{{ t('page.stay.change_room') }}</Button>
          <Button variant="subtle" @click="() => openStayDialog('extend')">{{ t('page.stay.extend') }}</Button>
          <Button variant="subtle" @click="() => openStayDialog('shorten')">{{ t('page.stay.shorten') }}</Button>
        </template>
        <Button variant="solid" @click="openCheckout">{{ t('page.in_house.checkout') }}</Button>
      </template>
    </ActionDrawer>

    <ChangeRoomDialog v-model="moveOpen" :stay="stayTarget" @changed="reload" />
    <ExtendStayDialog v-model="extendOpen" :stay="stayTarget" @changed="reload" />
    <ShortenStayDialog v-model="shortenOpen" :stay="stayTarget" @changed="reload" />
  </div>
</template>

<script setup>
import { Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import ChangeRoomDialog from '@/components/ChangeRoomDialog.vue'
import ExtendStayDialog from '@/components/ExtendStayDialog.vue'
import PageHeader from '@/components/PageHeader.vue'
import ShortenStayDialog from '@/components/ShortenStayDialog.vue'
import ActionDrawer from '@/components/operational/ActionDrawer.vue'
import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import { STAY_OPERATION_ROLES, inHouseResource, stayStatusTheme } from '@/resources/stays'
import { property } from '@/stores/property'
import { session } from '@/stores/session'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const router = useRouter()
const board = inHouseResource()

const filter = ref('all')
const search = ref('')

const drawerOpen = ref(false)
const selected = ref(null)

const moveOpen = ref(false)
const extendOpen = ref(false)
const shortenOpen = ref(false)
const stayTarget = ref(null)

/** Predicates over the rows already in memory. The board is one request. */
const FILTERS = {
  all: () => true,
  in_house: (row) => row.stay_status === 'In House',
  due_out: (row) => row.stay_status === 'Due Out',
}

const filterOptions = computed(() =>
  Object.keys(FILTERS).map((value) => ({ label: t(`page.in_house.filter.${value}`), value })),
)

const columns = computed(() => [
  { key: 'room', label: t('page.in_house.room'), primary: true, nowrap: true },
  { key: 'guest_name', label: t('page.reservations.guest'), secondary: true },
  { key: 'room_type', label: t('page.in_house.room_type'), hideBelow: 'xl' },
  { key: 'arrival_date', label: t('page.reservations.arrival'), type: 'date', nowrap: true },
  { key: 'departure_date', label: t('page.reservations.departure'), type: 'date', nowrap: true },
  { key: 'nights', label: t('page.in_house.nights'), type: 'number', hideBelow: 'lg' },
  { key: 'pax', label: t('page.in_house.pax'), field: 'adults', nowrap: true },
  {
    key: 'stay_status',
    label: t('page.reservations.status'),
    type: 'badge',
    theme: (row) => stayStatusTheme(row.stay_status),
  },
  { key: 'room_rate', label: t('page.in_house.rate'), type: 'money', nowrap: true },
])

/**
 * Row actions.
 *
 * Every stay change — move, extend, shorten — is reached through the drawer,
 * because all three open a dialog and a row with seven buttons is not a board any
 * more. Folio and Checkout stay inline, as they are today.
 */
const actions = computed(() => [
  { key: 'details', label: t('page.in_house.action.details'), icon: 'info' },
  {
    key: 'folio',
    label: t('page.in_house.action.folio'),
    available: (row) => Boolean(row.folio),
  },
  { key: 'checkout', label: t('page.in_house.checkout'), theme: 'blue' },
])

const stays = computed(() => board.data?.stays || [])

const visibleRows = computed(() => {
  const predicate = FILTERS[filter.value] || FILTERS.all
  const term = search.value.trim().toLowerCase()

  return stays.value.filter((row) => {
    if (!predicate(row)) return false
    if (!term) return true

    return [row.room, row.guest_name, row.room_type, row.name]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(term))
  })
})

const emptyMessage = computed(() =>
  stays.value.length ? t('page.in_house.filter_empty') : t('page.in_house.empty'),
)

const tiles = computed(() => {
  const s = board.data?.summary || {}

  return [
    { key: 'in_house', label: t('page.in_house.in_house'), value: s.in_house ?? 0 },
    { key: 'due_out', label: t('page.in_house.due_out'), value: s.due_out ?? 0 },
    { key: 'adults', label: t('page.availability.adults'), value: s.adults ?? 0 },
    { key: 'children', label: t('page.availability.children'), value: s.children ?? 0 },
  ]
})

const detailItems = computed(() => {
  const row = selected.value
  if (!row) return []

  return [
    { label: t('page.reservations.status'), value: row.stay_status },
    { label: t('page.in_house.stay'), value: row.name },
    { label: t('page.in_house.room_type'), value: row.room_type },
    { label: t('page.reservations.arrival'), value: formatDate(row.arrival_date) },
    { label: t('page.reservations.departure'), value: formatDate(row.departure_date) },
    { label: t('page.in_house.nights'), value: String(row.nights ?? '') },
    { label: t('page.in_house.pax'), value: `${row.adults}A ${row.children}C` },
  ]
})

/**
 * The stay-operation role, mirrored only to decide whether offering the three
 * mutating controls is worth it. No status test is needed: this board returns
 * only In House and Due Out stays, which is exactly what the services accept.
 * The server re-checks the role and the state regardless.
 */
const canOperate = computed(() => session.hasRole(STAY_OPERATION_ROLES))

/** An in-house row already carries every field the three stay dialogs read. */
function stayShape(row) {
  return {
    name: row.name,
    guest_name: row.guest_name,
    room: row.room,
    room_type: row.room_type,
    arrival_date: row.arrival_date,
    departure_date: row.departure_date,
  }
}

function onRowAction({ action, row }) {
  if (action === 'details') {
    selected.value = row
    drawerOpen.value = true
    return
  }

  if (action === 'folio') {
    router.push({ name: 'Folio', params: { id: row.folio } })
    return
  }

  if (action === 'checkout') {
    router.push({ name: 'Checkout', params: { stay: row.name } })
  }
}

/**
 * A dialog is never stacked inside the panel: the drawer closes first, so the
 * dialog owns the overlay, the Escape key and the focus trap on its own.
 */
function openStayDialog(kind) {
  stayTarget.value = stayShape(selected.value)
  drawerOpen.value = false

  if (kind === 'move') moveOpen.value = true
  if (kind === 'extend') extendOpen.value = true
  if (kind === 'shorten') shortenOpen.value = true
}

function openStay() {
  const row = selected.value
  drawerOpen.value = false
  router.push({ name: 'Stay', params: { id: row.name } })
}

function openGuest() {
  const row = selected.value
  drawerOpen.value = false
  router.push({ name: 'GuestProfile', params: { id: row.guest } })
}

function openFolio() {
  const row = selected.value
  drawerOpen.value = false
  router.push({ name: 'Folio', params: { id: row.folio } })
}

function openCheckout() {
  const row = selected.value
  drawerOpen.value = false
  router.push({ name: 'Checkout', params: { stay: row.name } })
}

function reload() {
  board.fetch({ property: property.activeName.value })
}

watch(() => property.activeName.value, reload, { immediate: true })
</script>
