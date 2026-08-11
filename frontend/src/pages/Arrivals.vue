<!--
  Arrivals board for the property's business date, on the shared operational table.

  One request returns the whole day, so the filter and the search below are client
  side: a single property-day is small, and re-fetching per keystroke would only
  add latency. The table itself filters nothing — it renders the rows this page
  hands it, in the order it hands them.

  This screen still decides nothing about the hotel. Check-in remains a link to
  the screen that owns the readiness override and the billing instructions, and
  room assignment opens the dialog that reaches `reservations.assign_room`, which
  locks the room and re-checks it server side. Nothing here mutates state itself.

  16.7.1 adds the two verbs that end a booking — cancel and no-show — and they are
  the reason this file has a rule the other boards do not need. Both act on the
  WHOLE RESERVATION: `reservations.cancel` and `mark_no_show` transition the
  reservation and `_propagate_status` stamps every room line. This board is one row
  per room line, so a "cancel" on one row of a three-room booking cancels all three
  rooms and all three rows disappear. Neither verb is therefore a row action: both
  live only in the drawer, which states the scope from the row's `total_rooms`
  before the agent can reach either.

  Whether the verb is offered is the server's answer, restated: `allowed_transitions`
  comes back on the row and is never re-derived here. It is never used to *disable*
  anything either — the board is fetched once per load and never polled, so the set
  can be stale by the time it is read, and the server re-reads the status under a
  lock. A stale offer therefore fails cleanly and the refusal is shown in the
  server's own words.
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

    <div class="space-y-4 p-5">
      <div v-if="rows.length" class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div v-for="tile in tiles" :key="tile.key" class="rounded border border-outline-gray-1 px-3 py-2">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold text-ink-gray-9">{{ tile.value }}</p>
        </div>
      </div>

      <OperationalDataTable
        :columns="columns"
        :rows="visibleRows"
        row-key="key"
        :loading="board.loading"
        :error="board.error"
        :empty-message="emptyMessage"
        :actions="actions"
        searchable
        :search="search"
        :search-label="t('page.arrivals.search_label')"
        :aria-label="t('page.arrivals.title')"
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
              :label="t('page.arrivals.filter')"
              :options="filterOptions"
            />
          </div>
        </template>

        <!-- Retry stays with the page, which owns the request. -->
        <template #error="{ error }">
          <ErrorState :error="error" :on-retry="reload" />
        </template>

        <template #cell:reservation="{ row }">
          <RouterLink
            :to="{ name: 'Reservation', params: { id: row.reservation } }"
            class="font-medium text-ink-blue-3 hover:underline"
          >
            {{ row.reservation }}
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

        <!-- The ETA is the booking's, not the room line's: a three-room
             reservation arrives once. It is shown beside the arrival date rather
             than as a per-room commitment. -->
        <template #cell:eta="{ row }">
          <span>{{ formatDate(row.arrival_date) }}</span>
          <span v-if="row.arrival_time" class="ms-1 text-ink-gray-5">{{ shortTime(row.arrival_time) }}</span>
        </template>

        <template #cell:room_type="{ row }">{{ row.room_type_name || row.room_type }}</template>

        <template #cell:room_number="{ row }">
          <span v-if="row.room_number" class="font-medium text-ink-gray-9">{{ row.room_number }}</span>
          <span v-else class="text-ink-gray-5">{{ t('page.arrivals.no_room_yet') }}</span>
        </template>

        <!--
          Housekeeping is only one of the four room dimensions; it is the one that
          decides whether a guest can walk in, so it is the one shown here.
          Occupancy, maintenance and inventory stay separate signals on the room
          rack rather than being merged into a verdict.
        -->
        <template #cell:readiness="{ row }">
          <RoomStatusBadge v-if="row.assigned_room && row.housekeeping_status" :status="row.housekeeping_status" />
          <span v-else class="text-ink-gray-5">—</span>
        </template>

        <template #cell:guarantee_type="{ row }">
          <span v-if="row.guarantee_type && row.guarantee_type !== 'None'">{{ row.guarantee_type }}</span>
          <span v-else class="text-ink-gray-5">—</span>
        </template>

        <template #cell:pax="{ row }">{{ row.adults }}A {{ row.children }}C</template>

        <!--
          The deposit is owed once per booking and the server copies it onto every
          room line of that booking, so this is deliberately not a plain money
          column: three rows of a three-room reservation would read as three
          deposits. It is a qualified flag, and only when something is outstanding.
        -->
        <template #cell:deposit_outstanding="{ row }">
          <span v-if="row.deposit_outstanding > 0.005" class="inline-flex items-center gap-1 text-ink-amber-3">
            <MoneyDisplay :value="row.deposit_outstanding" :currency="row.currency" />
            <span class="text-xs">{{ t('page.arrivals.deposit_due') }}</span>
          </span>
          <span v-else class="text-ink-gray-5">—</span>
        </template>

        <!--
          The board is told that a guest is blacklisted; it is never told why, and
          the reason is permlevel-restricted to the roles that set it. The badge
          says an alert exists and nothing more. There is deliberately no
          "no alerts" state: this board never queries the alert register, so an
          empty cell is honest where a green tick would be a false clearance.
        -->
        <template #cell:alerts="{ row }">
          <AlertBadge
            v-if="hasField(row, 'is_blacklisted') && row.is_blacklisted"
            present
            severity="high"
            :label="t('common.blacklisted')"
          />
          <!--
            Three states here, not two, and the difference is the point. A cleared
            reader seeing the dash has been told this guest is not flagged; a
            reader the server did not clear for the flag has been told nothing.
            `hasField` separates them, so the second case does not borrow the
            first case's reassurance.
          -->
          <span v-else-if="hasField(row, 'is_blacklisted')" class="text-ink-gray-5">—</span>
          <span v-else class="text-ink-gray-4" :title="t('ui.alert_badge.restricted')">·</span>
        </template>
      </OperationalDataTable>
    </div>

    <!--
      Contextual detail without leaving the board. It carries the summary and the
      navigation; the one action that needs a dialog closes the panel first, so a
      dialog is never stacked inside it.
    -->
    <ActionDrawer
      v-model="drawerOpen"
      :title="selected?.guest_name || ''"
      :subtitle="selected ? `${selected.reservation} · ${selected.room_type_name || selected.room_type}` : ''"
    >
      <dl v-if="selected" class="space-y-3">
        <div v-for="item in detailItems" :key="item.label">
          <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ item.label }}</dt>
          <dd class="text-p-sm text-ink-gray-8">{{ item.value }}</dd>
        </div>
        <div v-if="selected.special_requests">
          <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.arrivals.notes') }}</dt>
          <dd class="text-p-sm text-ink-gray-8">{{ selected.special_requests }}</dd>
        </div>
      </dl>

      <!--
        The scope of the two ending verbs, stated in the panel that offers them and
        again inside the dialog that performs them. One short sentence repeated is
        the right trade for an action that can end three rooms from one row.
      -->
      <div
        v-if="canCancel(selected) || canNoShow(selected)"
        class="mt-4 rounded border border-outline-gray-1 p-3 text-p-sm text-ink-gray-6"
      >
        <p v-if="canCancel(selected)">{{ cancelScope }}</p>
        <p v-if="canNoShow(selected) && noShowScope" class="mt-1">{{ noShowScope }}</p>
      </div>

      <template #footer>
        <Button variant="subtle" @click="openReservation">{{ t('page.arrivals.action.open') }}</Button>
        <Button variant="subtle" @click="openGuest">{{ t('page.arrivals.action.guest_profile') }}</Button>
        <!-- Only where a folio actually exists: an arrival has none before
             check-in, and a checked-in row may have picked one up. -->
        <Button v-if="selected?.folio" variant="subtle" @click="openFolio">
          {{ t('page.arrivals.action.folio') }}
        </Button>
        <Button v-if="canAssign(selected)" variant="subtle" @click="assignFromDrawer">
          {{ t('page.arrivals.action.assign_room') }}
        </Button>
        <!-- Never disabled, only withheld: see the file header on stale offers. -->
        <Button v-if="canNoShow(selected)" variant="subtle" theme="red" @click="noShowFromDrawer">
          {{ t('page.arrivals.action.no_show') }}
        </Button>
        <Button v-if="canCancel(selected)" variant="subtle" theme="red" @click="cancelFromDrawer">
          {{ t('page.arrivals.action.cancel') }}
        </Button>
        <Button v-if="selected && !selected.is_checked_in" variant="solid" @click="openCheckIn">
          {{ t('page.arrivals.action.check_in') }}
        </Button>
      </template>
    </ActionDrawer>

    <AssignRoomDialog
      v-model="assignOpen"
      :reservation="assignTarget?.reservation || ''"
      :line="assignLine"
      @changed="reload"
    />

    <!--
      Both carry the room count so they can name the scope, and the currency so the
      policy charge the server returns reads in the booking's own money.
    -->
    <CancelReservationDialog
      v-model="cancelOpen"
      :reservation="actionTarget?.reservation || ''"
      :rooms="roomCount(actionTarget)"
      :currency="actionTarget?.currency || null"
      @cancelled="reload"
    />

    <MarkNoShowDialog
      v-model="noShowOpen"
      :reservation="actionTarget?.reservation || ''"
      :rooms="roomCount(actionTarget)"
      :currency="actionTarget?.currency || null"
      @marked="reload"
    />
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import AssignRoomDialog from '@/components/AssignRoomDialog.vue'
import CancelReservationDialog from '@/components/CancelReservationDialog.vue'
import MarkNoShowDialog from '@/components/MarkNoShowDialog.vue'
import PageHeader from '@/components/PageHeader.vue'
import RoomStatusBadge from '@/components/RoomStatusBadge.vue'
import ActionDrawer from '@/components/operational/ActionDrawer.vue'
import AlertBadge from '@/components/operational/AlertBadge.vue'
import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import { FRONT_DESK_ROLES, arrivalsBoardResource } from '@/resources/frontOffice'
import { hasField, vipStatusTheme } from '@/resources/guests'
import { NO_SHOW_ROLES, reservationStatusTheme } from '@/resources/reservations'
import { property } from '@/stores/property'
import { session } from '@/stores/session'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const router = useRouter()
const board = arrivalsBoardResource()

const filter = ref('all')
const search = ref('')

const drawerOpen = ref(false)
const selected = ref(null)

const assignOpen = ref(false)
const assignTarget = ref(null)

// The row a drawer action is being performed on. Held separately from `selected`
// so the panel can close — a dialog is never stacked inside it — without the
// dialog losing the reservation it is about to end.
const actionTarget = ref(null)
const cancelOpen = ref(false)
const noShowOpen = ref(false)

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

/**
 * Column descriptions, already translated.
 *
 * `guarantee_type` and `departure_date` are kept: both are on screen today and
 * both are decision inputs at the desk — the guarantee is how an agent knows
 * whether a card is on file.
 */
const columns = computed(() => [
  { key: 'reservation', label: t('page.arrivals.reservation'), primary: true, nowrap: true },
  { key: 'guest_name', label: t('page.arrivals.guest'), secondary: true },
  { key: 'eta', label: t('page.arrivals.eta'), field: 'arrival_date', nowrap: true },
  { key: 'departure_date', label: t('page.reservations.departure'), type: 'date', nowrap: true, hideBelow: 'xl' },
  { key: 'room_type', label: t('page.arrivals.room_type') },
  { key: 'room_number', label: t('page.arrivals.room'), nowrap: true },
  { key: 'readiness', label: t('page.arrivals.readiness'), field: 'housekeeping_status' },
  {
    key: 'reservation_status',
    label: t('page.reservations.status'),
    type: 'badge',
    theme: (row) => reservationStatusTheme(row.reservation_status),
  },
  { key: 'guarantee_type', label: t('page.arrivals.guarantee'), nowrap: true, hideBelow: 'xl' },
  { key: 'nights', label: t('page.arrivals.nights'), type: 'number', hideBelow: 'lg' },
  { key: 'pax', label: t('page.arrivals.pax'), field: 'adults', nowrap: true },
  { key: 'deposit_outstanding', label: t('page.arrivals.deposit'), nowrap: true },
  { key: 'alerts', label: t('page.arrivals.alerts'), field: 'is_blacklisted' },
])

/**
 * Row actions.
 *
 * Navigation carries no role check: the destination screen authorises its own
 * request and mirrors the role at the point where it mutates. Only the one
 * action that opens a mutating dialog from this board mirrors a role, and it
 * imports the existing constant rather than declaring a list here.
 *
 * Cancel and no-show are deliberately ABSENT from this list — see the file
 * header. Their scope is the reservation, not the row, so they are offered only
 * in the drawer, where the room count is on screen next to them.
 */
const actions = computed(() => [
  { key: 'details', label: t('page.arrivals.action.details'), icon: 'info' },
  {
    key: 'folio',
    label: t('page.arrivals.action.folio'),
    // An arrival has no folio until it becomes a stay, so this is offered only
    // where the row carries one. No folio identifier is invented from the stay.
    available: (row) => Boolean(row.folio),
  },
  {
    key: 'assign_room',
    label: t('page.arrivals.action.assign_room'),
    available: canAssign,
  },
  {
    key: 'check_in',
    label: t('page.arrivals.action.check_in'),
    theme: 'blue',
    available: (row) => !row.is_checked_in,
  },
])

const rows = computed(() => board.data?.rows || [])

/** Filter first, then the search term, both over rows already in memory. */
const visibleRows = computed(() => {
  const predicate = FILTERS[filter.value] || FILTERS.all
  const term = search.value.trim().toLowerCase()

  return rows.value.filter((row) => {
    if (!predicate(row)) return false
    if (!term) return true

    return [row.reservation, row.guest_name, row.room_number, row.room_type_name]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(term))
  })
})

/** Which "nothing here" the operator is looking at: no arrivals, or none matching. */
const emptyMessage = computed(() =>
  rows.value.length ? t('page.arrivals.filter_empty') : t('page.arrivals.empty'),
)

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

const detailItems = computed(() => {
  const row = selected.value
  if (!row) return []

  return [
    { label: t('page.reservations.status'), value: row.reservation_status },
    {
      label: t('page.reservations.arrival'),
      value: [formatDate(row.arrival_date), shortTime(row.arrival_time)].filter(Boolean).join(' '),
    },
    { label: t('page.reservations.departure'), value: formatDate(row.departure_date) },
    { label: t('page.arrivals.nights'), value: String(row.nights ?? '') },
    { label: t('page.arrivals.room'), value: row.room_number || t('page.arrivals.no_room_yet') },
    { label: t('page.arrivals.pax'), value: `${row.adults}A ${row.children}C` },
    { label: t('page.arrivals.guarantee'), value: row.guarantee_type || t('common.none') },
  ]
})

/** `18:00:00` reads as `18:00`; the seconds are noise on a board. */
function shortTime(value) {
  return value ? String(value).slice(0, 5) : ''
}

/**
 * Assignment is offered while the room line has no room and has not become a
 * stay. Once a stay exists the verb is a room move, which belongs to the stay,
 * not to `reservations.assign_room`. The role is mirrored only to decide whether
 * offering the control is worth it; the server re-checks it either way.
 */
function canAssign(row) {
  if (!row) return false

  return !row.assigned_room && !row.is_checked_in && session.hasRole(FRONT_DESK_ROLES)
}

/**
 * How many rooms the reservation holds, or `null` when the row does not say.
 *
 * Read from the row's `total_rooms`, which the reservations query has always
 * fetched and now puts on the row. It is never counted from the visible rows: a
 * filtered or searched board shows a subset, and "all 2 of its rooms" on a
 * three-room booking is exactly the misstatement the scope sentence exists to
 * prevent. An unknown count therefore withholds both verbs rather than guessing.
 */
function roomCount(row) {
  const total = Number(row?.total_rooms)

  return Number.isFinite(total) && total > 0 ? total : null
}

/**
 * Whether the server offered this transition for the row.
 *
 * The state machine is not mirrored here in any form: `allowed_transitions` is
 * the server's own answer, and a row that does not carry it gets no offer rather
 * than a locally reconstructed one. Used to decide what to *show* only; nothing
 * is disabled on it, because the set is as old as the last board fetch.
 */
function serverOffers(row, target) {
  return Array.isArray(row?.allowed_transitions) && row.allowed_transitions.includes(target)
}

/**
 * Cancellation is offered to the front desk on a booking the server still lets
 * go, and never on one that is already in house — a checked-in room line is a
 * stay, and ending it is a checkout, not a cancellation. The role mirrors
 * `FRONT_DESK_ROLES`; the server re-checks it, and re-checks the override roles
 * a late or in-policy-window cancellation additionally needs.
 */
function canCancel(row) {
  if (!row || row.is_checked_in) return false
  if (roomCount(row) === null) return false

  return serverOffers(row, 'Cancelled') && session.hasRole(FRONT_DESK_ROLES)
}

/**
 * A no-show is a narrower verb than a cancellation, and deliberately not a
 * front-desk one: `NO_SHOW_ROLES` on the server excludes Front Office Agent, so
 * mirroring `FRONT_DESK_ROLES` here would put a control in front of an agent
 * that `require_role` refuses every time.
 */
function canNoShow(row) {
  if (!row || row.is_checked_in) return false
  if (roomCount(row) === null) return false

  return serverOffers(row, 'No Show') && session.hasRole(NO_SHOW_ROLES)
}

/** The scope sentences, named by the room count the row carries. */
const cancelScope = computed(() => {
  const rooms = roomCount(selected.value)

  return rooms > 1
    ? t('page.arrivals.cancel_whole_reservation', { count: rooms })
    : t('page.arrivals.cancel_single_room')
})

// Only the multi-room wording exists for a no-show, and it is the only case that
// needs stating: a one-room reservation has no hidden reach to warn about.
const noShowScope = computed(() => {
  const rooms = roomCount(selected.value)

  return rooms > 1 ? t('page.arrivals.no_show_whole_reservation', { count: rooms }) : ''
})

/** The room line, in the shape AssignRoomDialog reads it. */
const assignLine = computed(() => {
  const row = assignTarget.value
  if (!row) return null

  return {
    name: row.room_line,
    room_type: row.room_type,
    arrival_date: row.arrival_date,
    departure_date: row.departure_date,
  }
})

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

  if (action === 'assign_room') {
    openAssign(row)
    return
  }

  if (action === 'check_in') {
    router.push({ name: 'CheckIn', params: { reservation: row.reservation } })
  }
}

function openAssign(row) {
  assignTarget.value = row
  assignOpen.value = true
}

/**
 * A dialog is never stacked inside the panel: the drawer closes first, which
 * also returns focus to the row action that opened it before the dialog takes
 * focus of its own.
 */
function assignFromDrawer() {
  const row = selected.value
  drawerOpen.value = false
  openAssign(row)
}

/** Same rule as above for the two ending verbs: the panel closes first. */
function cancelFromDrawer() {
  actionTarget.value = selected.value
  drawerOpen.value = false
  cancelOpen.value = true
}

function noShowFromDrawer() {
  actionTarget.value = selected.value
  drawerOpen.value = false
  noShowOpen.value = true
}

function openReservation() {
  const row = selected.value
  drawerOpen.value = false
  router.push({ name: 'Reservation', params: { id: row.reservation } })
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

function openCheckIn() {
  const row = selected.value
  drawerOpen.value = false
  router.push({ name: 'CheckIn', params: { reservation: row.reservation } })
}

function reload() {
  board.fetch({ property: property.activeName.value })
}

watch(() => property.activeName.value, reload, { immediate: true })
</script>
