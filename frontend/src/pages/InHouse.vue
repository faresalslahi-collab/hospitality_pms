<!--
  In-house board, on the shared operational table.

  16.7.1 moved this board onto the enriched endpoint. `api.stays.in_house` is now
  served by `front_office.get_in_house_board`, which assembles the row from the same
  bulk helpers the arrivals and departures boards use, so a room number, a folio
  balance and a checkout blocker mean the same thing on all three screens.
  `services.stays.get_in_house` was deliberately left alone — it is read by the
  dashboard and the night audit, where a wider field list is dead weight.

  What that made possible, and what it still does not license:

  - The balance is the folio service's own figure, rendered through `FolioBalance`.
    Nothing is summed here; split folios stay counted, never folded in, because a
    company-pay split is a different payer's debt.
  - The currency is the row's. The 16.7.0 workaround that showed the rate in the
    active property's currency is gone: the row carries `currency` now, and an
    amount is only ever labelled with the currency that arrived beside it.
  - `can_check_out` is the checkout service's verdict and is never recomputed. It
    is rendered only on a **Due Out** row. Mid-stay guests normally have a zero
    balance and an undisputed folio, so the verdict is true for most of the house,
    and a readiness badge on every In House row would read "the whole hotel is
    ready to leave". An In House row shows its balance and makes no claim about
    the door.
  - Alerts are a count and a grade, never a body. The alert text is free text
    about a guest who may be standing at the counter reading the screen; the
    guest endpoints authorise reading one, and this board never asks.
  - `is_blacklisted` is permission-gated and is ABSENT for a caller who is not
    cleared. Absence is "not disclosed to you", never "not blacklisted", so the
    flag is rendered only when the key is present and true and no negative is ever
    rendered in its place.
  - `id_verified` is shown as an exception only: a chip when identification was not
    captured, and nothing at all when it was. A column of green ticks would turn a
    compliance follow-up into decoration.
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
          `room_number` is the door number the desk says out loud. `row.room` is the
          Hotel Room docname (PROPERTY-ROOMNUMBER) and is the fallback, so a row
          whose room record is missing still identifies itself.
        -->
        <template #cell:room="{ row }">
          <RouterLink
            :to="{ name: 'Stay', params: { id: row.name } }"
            class="font-medium text-ink-blue-3 hover:underline"
          >
            {{ roomLabel(row) }}
          </RouterLink>
        </template>

        <template #cell:guest_name="{ row }">
          <span class="text-ink-gray-9">{{ row.guest_name }}</span>
          <Badge
            v-if="row.vip_status"
            class="ms-1"
            :theme="vipStatusTheme(row.vip_status)"
            variant="subtle"
            :label="row.vip_status"
          />
        </template>

        <template #cell:room_type="{ row }">{{ row.room_type_name || row.room_type }}</template>

        <template #cell:pax="{ row }">{{ row.adults }}A {{ row.children }}C</template>

        <!-- The row's own currency, never the property's. -->
        <template #cell:room_rate="{ row }">
          <MoneyDisplay :value="row.room_rate" :currency="row.currency" />
        </template>

        <!-- The folio service's balance, restated. Split folios are counted here
             exactly as the departures board counts them, and for the same reason. -->
        <template #cell:balance="{ row }">
          <FolioBalance :balance="row.balance ?? null" :currency="row.currency" :show-label="false" />
          <p v-if="row.related_folios > 0" class="mt-1 text-xs text-ink-gray-5">
            {{ t('page.departures.split_folios', { count: row.related_folios }) }}
          </p>
        </template>

        <!--
          Status, and — on a Due Out row only — the server's checkout verdict beside
          it. See the file header: on an In House row this board makes no claim
          about whether the guest may leave.
        -->
        <template #cell:stay_status="{ row }">
          <Badge :theme="stayStatusTheme(row.stay_status)" variant="subtle" :label="row.stay_status" />
          <template v-if="showsReadiness(row)">
            <Badge
              v-if="row.can_check_out"
              class="ms-1"
              theme="green"
              variant="subtle"
              :label="t('page.departures.ready')"
            />
            <Badge v-else class="ms-1" theme="orange" variant="subtle" :label="t('page.departures.blocked')" />
          </template>
        </template>

        <!--
          Attention, in three independent statements: a blacklist flag if it was
          disclosed, a count and grade of active alerts if the server counted any,
          and an outstanding-identification chip if there is one. No alert body, and
          no all-clear: an empty cell here says only that nothing was flagged.
        -->
        <template #cell:alerts="{ row }">
          <span class="inline-flex flex-wrap items-center gap-1">
            <AlertBadge
              v-if="isBlacklisted(row)"
              present
              severity="high"
              :label="t('common.blacklisted')"
            />
            <AlertBadge
              v-if="row.alert_count > 0"
              :count="row.alert_count"
              :severity="alertSeverity(row)"
            />
            <Badge
              v-if="row.id_verified === false"
              theme="orange"
              variant="subtle"
              :label="t('page.in_house.id_not_verified')"
              :title="t('page.in_house.id_not_verified_hint')"
            />
            <span v-if="!hasAttention(row)" class="text-ink-gray-5">—</span>
          </span>
        </template>
      </OperationalDataTable>
    </div>

    <ActionDrawer
      v-model="drawerOpen"
      :title="selected?.guest_name || ''"
      :subtitle="selected ? `${t('page.in_house.room')} ${roomLabel(selected)}` : ''"
    >
      <div v-if="selected" class="space-y-4">
        <FolioBalance :balance="selected.balance ?? null" :currency="selected.currency" size="md" />

        <dl class="space-y-3">
          <div v-for="item in detailItems" :key="item.label">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ item.label }}</dt>
            <dd class="text-p-sm text-ink-gray-8">{{ item.value }}</dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.in_house.rate') }}</dt>
            <dd class="text-p-sm text-ink-gray-8">
              <MoneyDisplay :value="selected.room_rate" :currency="selected.currency" />
            </dd>
          </div>
        </dl>

        <!-- Blockers arrive already worded and translated by the server, and are
             shown only where a readiness claim is made at all. -->
        <div v-if="showsReadiness(selected) && !selected.can_check_out && selected.blockers?.length">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.departures.blockers') }}</p>
          <ul class="mt-1 list-disc ps-4 text-p-sm text-ink-gray-7">
            <li v-for="(blocker, index) in selected.blockers" :key="index">{{ blocker }}</li>
          </ul>
        </div>

        <p v-if="selected.id_verified === false" class="text-p-sm text-ink-gray-6">
          {{ t('page.in_house.id_not_verified_hint') }}
        </p>
      </div>

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
          <Button variant="subtle" @click="() => openStayDialog('request')">
            {{ t('page.guest_services.create') }}
          </Button>
        </template>
        <Button variant="solid" @click="openCheckout">{{ t('page.in_house.checkout') }}</Button>
      </template>
    </ActionDrawer>

    <ChangeRoomDialog v-model="moveOpen" :stay="stayTarget" @changed="reload" />
    <ExtendStayDialog v-model="extendOpen" :stay="stayTarget" @changed="reload" />
    <ShortenStayDialog v-model="shortenOpen" :stay="stayTarget" @changed="reload" />

    <!--
      The row's context, prefilled. The four link fields stay editable; what they
      remove is the retyping, which is where a request gets attached to the wrong
      room and sends someone to the wrong door.
    -->
    <GuestRequestFormDialog
      v-model="requestOpen"
      :room="requestTarget?.room || ''"
      :guest="requestTarget?.guest || ''"
      :reservation="requestTarget?.reservation || ''"
      :stay="requestTarget?.name || ''"
    />
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import ChangeRoomDialog from '@/components/ChangeRoomDialog.vue'
import ExtendStayDialog from '@/components/ExtendStayDialog.vue'
import GuestRequestFormDialog from '@/components/GuestRequestFormDialog.vue'
import PageHeader from '@/components/PageHeader.vue'
import ShortenStayDialog from '@/components/ShortenStayDialog.vue'
import ActionDrawer from '@/components/operational/ActionDrawer.vue'
import AlertBadge from '@/components/operational/AlertBadge.vue'
import FolioBalance from '@/components/operational/FolioBalance.vue'
import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import { hasField, vipStatusTheme } from '@/resources/guests'
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

const requestOpen = ref(false)
const requestTarget = ref(null)

/** The stay status this board treats as "leaving today". */
const DUE_OUT = 'Due Out'

/**
 * The server's alert vocabulary, mapped onto `AlertBadge`'s three grades.
 *
 * The server grades an alert Info / Warning / Critical; the badge speaks
 * low / medium / high. Anything else — including the empty string the server
 * sends for an ungraded row — maps to nothing, and the badge then shows a
 * neutral count rather than borrowing a severity colour it was never given.
 */
const ALERT_SEVERITY = {
  Critical: 'high',
  Warning: 'medium',
  Info: 'low',
}

/** Predicates over the rows already in memory. The board is one request. */
const FILTERS = {
  all: () => true,
  in_house: (row) => row.stay_status === 'In House',
  due_out: (row) => row.stay_status === DUE_OUT,
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
  { key: 'room_rate', label: t('page.in_house.rate'), type: 'money', nowrap: true, hideBelow: 'xl' },
  { key: 'balance', label: t('page.in_house.balance'), nowrap: true },
  { key: 'stay_status', label: t('page.reservations.status'), field: 'stay_status' },
  { key: 'alerts', label: t('page.in_house.alerts'), field: 'alert_count' },
])

/**
 * Row actions.
 *
 * Every stay change — move, extend, shorten, and now a guest request — is reached
 * through the drawer, because all four open a dialog and a row with seven buttons
 * is not a board any more. Folio and Checkout stay inline, as they are today.
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

    return [row.room_number, row.room, row.guest_name, row.room_type_name, row.room_type, row.name, row.folio]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(term))
  })
})

const emptyMessage = computed(() =>
  stays.value.length ? t('page.in_house.filter_empty') : t('page.in_house.empty'),
)

/**
 * The house at a glance.
 *
 * `ready_to_check_out` is deliberately not a tile, for the same reason the
 * readiness badge is withheld from an In House row: most of the house is
 * technically clear to leave at any moment, and a tile saying so invites the
 * desk to read it as departures.
 */
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
    { label: t('page.in_house.reservation'), value: row.reservation || '—' },
    { label: t('page.in_house.room_type'), value: row.room_type_name || row.room_type || '—' },
    { label: t('page.reservations.arrival'), value: formatDate(row.arrival_date) },
    { label: t('page.reservations.departure'), value: formatDate(row.departure_date) },
    { label: t('page.in_house.nights'), value: String(row.nights ?? '') },
    { label: t('page.in_house.pax'), value: `${row.adults}A ${row.children}C` },
    { label: t('page.in_house.folio'), value: row.folio || '—' },
  ]
})

/** The door number where the row has one; the room docname otherwise. */
function roomLabel(row) {
  return row?.room_number || row?.room || ''
}

/**
 * Whether this row makes a checkout claim at all.
 *
 * Only a stay that is leaving today. `can_check_out` is true for most of the
 * house on any given morning, so restating it on every row would turn a useful
 * departures signal into noise that reads as a hotel-wide verdict.
 */
function showsReadiness(row) {
  return row?.stay_status === DUE_OUT
}

/**
 * The blacklist flag, and only when it was disclosed.
 *
 * `is_blacklisted` is permission-gated: the key is absent for a caller who is not
 * cleared, which means "not disclosed to you". A truthiness test alone would read
 * that as a clearance, so the key's presence is checked first with the same
 * `hasField` helper the guest screens use.
 */
function isBlacklisted(row) {
  return hasField(row, 'is_blacklisted') && Boolean(row.is_blacklisted)
}

/** The badge's grade, or '' when the server graded nothing. */
function alertSeverity(row) {
  return ALERT_SEVERITY[row?.alert_severity] || ''
}

/** Whether anything at all is flagged, so an unflagged row reads as a dash. */
function hasAttention(row) {
  return isBlacklisted(row) || row?.alert_count > 0 || row?.id_verified === false
}

/**
 * The stay-operation role, mirrored only to decide whether offering the mutating
 * controls is worth it. No status test is needed: this board returns only In House
 * and Due Out stays, which is exactly what the services accept. The server
 * re-checks the role and the state regardless.
 */
const canOperate = computed(() => session.hasRole(STAY_OPERATION_ROLES))

/** An in-house row already carries every field the three stay dialogs read. */
function stayShape(row) {
  return {
    name: row.name,
    guest_name: row.guest_name,
    room: roomLabel(row),
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
  const row = selected.value

  stayTarget.value = stayShape(row)
  // The request dialog reads the row itself rather than the stay shape: it wants
  // the guest and the reservation, which a stay dialog has no use for.
  requestTarget.value = row
  drawerOpen.value = false

  if (kind === 'move') moveOpen.value = true
  if (kind === 'extend') extendOpen.value = true
  if (kind === 'shorten') shortenOpen.value = true
  if (kind === 'request') requestOpen.value = true
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
