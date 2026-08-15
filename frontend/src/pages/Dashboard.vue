<!--
  Front Desk Command Center: the screen a receptionist works from, forty times a
  shift, for one property on its business date.

  The geography is fixed and does not move with the time of day — property and
  business date, the work counters, the four queues, the open work, the state of
  the house, tonight's audit, the rack, the money, the actions. Only the content
  changes. A panel that moves between the morning and the evening is a panel
  nobody learns.

  What this screen is *not* is a report. Booking-source mix and a room-revenue
  sparkline were removed in 16.7.1: nothing at a counter changes because 38% of
  tonight came from an OTA, and the trend needs two closed audits before it can
  be drawn at all. ADR and RevPAR are kept, demoted to one footer line, still
  named as the last *closed* audit's figures — a duty manager has nowhere else to
  read them in this release, and deleting them would be worse than demoting them.

  Every figure is the server's. The only derived value is the live occupancy
  percentage, which is labelled as live and is not a reportable figure.

  On request count: the counters are still one aggregate call. The boards, the
  in-house list, the rack and the audit are separate reads because they are
  separate screens' worth of data and separate permissions — a housekeeper who
  cannot read Reservation gets the rest of the dashboard rather than an error
  page. They are fetched once per load and never polled; the header's Refresh is
  the only thing that repeats them.
-->
<template>
  <!--
    The tinted canvas is this screen's, not the shell's: cards need a plane to
    sit on, and the boards that are still plain white pages would only be made
    to look unfinished by a background they were not designed against.
  -->
  <div class="min-h-full bg-navy-50">
    <PageHeader :title="t('page.dashboard.title')" :subtitle="subtitle">
      <template #actions>
        <Button variant="subtle" :loading="anyLoading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <!--
      The one global search box in the app, and it lives here.

      It used to sit in the shell above every page's title - including screens
      that already have their own, better-scoped search - so the Command Center
      opened on a text box rather than on the hotel and the date. It is now the
      page's, and only this page's: this is the screen somebody lands on without
      yet knowing which board answers their question. Everywhere else the page's
      own filter is the right control, and the shell renders nothing.

      Under the header, not over it, and outside the sticky area: it scrolls away
      with the page, available without competing with the counters below it.
      Rendered before the loading branch, because a desk searching for a guest
      should not have to wait for a rack.
    -->
    <div class="border-b border-outline-gray-1 bg-surface-white px-4 py-2.5 lg:px-5">
      <GlobalSearch class="w-full md:max-w-md" />
    </div>

    <LoadingState v-if="dashboard.loading && !dashboard.data" />
    <ErrorState v-else-if="dashboard.error" :error="dashboard.error" :on-retry="reload" />
    <EmptyState v-else-if="!dashboard.data" />

    <div v-else class="space-y-5 p-4 lg:p-5">
      <!--
        The day's position at the desk, counted in rooms.

        Rooms, not reservations, and work rather than totals: a three-room
        booking is three arrivals to work. The expected/departing totals and the
        in-house head count were removed in 16.7.1 — a total is a report, and the
        head count is F&B's number, not the desk's.
      -->
      <section aria-labelledby="command-center-counters">
        <h2 id="command-center-counters" class="mb-2.5 text-p-sm font-semibold text-ink-gray-7">
          {{ t('page.dashboard.section.front_desk') }}
        </h2>

        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7">
          <StatTile v-for="tile in frontDeskTiles" :key="tile.key" v-bind="tile" />
        </div>

        <!-- The one counter that needs a sentence: an unassigned line cannot be
             made ready, cannot be keyed and cannot be checked in. -->
        <p class="mt-2 text-xs text-ink-gray-5">{{ t('page.dashboard.unassigned_arrivals_hint') }}</p>
      </section>

      <!--
        The four queues, in the order the desk works them: who is arriving, who
        is leaving, which rooms are stopped, and who still owes money. These are
        working lists — each one links to the board that remains the authority.
      -->
      <section aria-labelledby="command-center-queues">
        <h2 id="command-center-queues" class="mb-2.5 text-p-sm font-semibold text-ink-gray-7">
          {{ t('page.dashboard.queues') }}
        </h2>

        <div class="grid gap-4 xl:grid-cols-2">
          <ArrivalsPanel :arrivals="arrivalRows" :limit="6" :loading="arrivals.loading && !arrivals.data" />
          <DeparturesPanel
            :departures="departureRows"
            :limit="6"
            :loading="departures.loading && !departures.data"
          />
          <RoomAttentionPanel
            :rooms="rackRooms"
            :arrivals="arrivalRows"
            :limit="6"
            :loading="rack.loading && !rack.data"
          />
          <InHousePanel
            :stays="inHouseRows"
            :in-house-rooms="frontOffice.in_house_rooms ?? 0"
            :due-out="frontOffice.due_out ?? 0"
            :loading="inHouse.loading && !inHouse.data"
          />
        </div>
      </section>

      <div class="grid gap-4 lg:grid-cols-3">
        <DashboardCard :title="t('page.dashboard.section.workload')" dense>
          <div class="grid gap-2.5 sm:grid-cols-3 lg:grid-cols-1">
            <component
              :is="item.to ? RouterLink : 'div'"
              v-for="item in workloadItems"
              :key="item.key"
              v-bind="item.to ? { to: item.to } : {}"
              class="flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors"
              :class="[item.surface, item.to ? 'hover:brightness-95' : '']"
            >
              <span
                class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-white"
                :class="item.tone"
                aria-hidden="true"
              >
                <FeatherIcon :name="item.icon" class="size-[18px]" />
              </span>
              <span class="min-w-0">
                <span class="block truncate text-p-sm font-medium text-ink-gray-7">{{ item.label }}</span>
                <span class="block text-xl font-semibold text-ink-gray-9">{{ item.value }}</span>
              </span>
              <span class="ms-auto shrink-0 text-xs text-ink-gray-5">{{ item.hint }}</span>
            </component>
          </div>
        </DashboardCard>

        <!--
          The house, restated in rooms. The percentage leads because it is the
          question the desk is asked; the rooms are underneath it because the
          rooms are what it can act on, and the audited figure is named and dated
          so nobody reads the live one as reportable (HPMS-DEC-030).
        -->
        <KpiCard
          :label="t('page.dashboard.live_occupancy')"
          :value="`${formatNumber(liveOccupancy, 1)}%`"
          :caption="t('page.dashboard.occupancy_caption', { occupied: rooms.occupied ?? 0, active: rooms.active ?? 0 })"
          :footnote="auditedOccupancy"
          icon="pie-chart"
          icon-class="bg-blue-50 text-blue-600"
        >
          <DonutChart
            :percentage="liveOccupancy"
            :size="64"
            :thickness="9"
            :aria-label="t('page.dashboard.occupancy_chart_label', { percent: formatNumber(liveOccupancy, 1) })"
          />

          <!-- What can actually be sold right now: the server's `assignable`,
               which has already applied all four status dimensions. -->
          <template #footer>
            <p class="flex items-baseline justify-between gap-2 border-t border-outline-gray-1 pt-2 text-xs">
              <span class="text-ink-gray-6">{{ t('page.dashboard.available') }}</span>
              <span class="text-p-base font-semibold tabular-nums text-ink-green-3">{{ rooms.assignable ?? 0 }}</span>
            </p>
          </template>
        </KpiCard>

        <NightAuditCard
          v-if="canSeeAudit"
          :audit="nightAudit.data?.audit || null"
          :blocking-count="nightAudit.data?.blocking_count || 0"
        />
      </div>

      <!-- The rack picture, below the queues: the rack is what the desk looks at,
           the queues are what it works from. -->
      <RoomStatusBoard
        :room-types="rack.data?.room_types || []"
        :loading="rack.loading && !rack.data"
        @select="openRoom"
      />

      <!--
        Money as one row rather than a card. Two figures the desk acts on, plus
        posted room revenue, which reads zero for most of the day by design and
        carries the sentence that says so.
      -->
      <!--
        Hidden outright when the server did not disclose `revenue`.

        The block is omitted for a caller who may not read Guest Folio, and
        `hasField` is the test rather than truthiness: rendering it anyway would
        print "Outstanding 0.00", which reads as "everybody has paid" and is a
        claim about the hotel's money that this caller was specifically not told.
        Ten roles land on this screen without Guest Folio read.
      -->
      <section
        v-if="revenueDisclosed"
        aria-labelledby="command-center-money"
        class="flex flex-wrap items-baseline gap-x-8 gap-y-2 rounded-xl border border-outline-gray-1
          bg-surface-white px-4 py-3 shadow-card"
      >
        <h2 id="command-center-money" class="text-p-sm font-semibold text-ink-gray-7">
          {{ t('page.dashboard.section.revenue') }}
        </h2>

        <dl class="flex flex-wrap items-baseline gap-x-8 gap-y-2">
          <div v-for="line in moneyLines" :key="line.key" class="flex items-baseline gap-2">
            <dt class="text-xs text-ink-gray-6">{{ line.label }}</dt>
            <dd class="text-p-base font-semibold" :class="line.tone">
              <MoneyDisplay :value="line.value" :currency="revenueCurrency" />
            </dd>
          </div>
        </dl>

        <p class="max-w-prose text-xs text-ink-gray-5">{{ t('page.dashboard.revenue_hint') }}</p>
      </section>

      <DashboardCard :title="t('page.dashboard.section.quick_actions')" dense>
        <div class="grid grid-cols-3 gap-2 sm:grid-cols-5 xl:grid-cols-10">
          <RouterLink
            v-for="action in quickActions"
            :key="action.key"
            :to="action.to"
            class="flex flex-col items-center gap-1.5 rounded-lg border border-outline-gray-1 px-2 py-3
              text-center transition-colors hover:border-outline-gray-2 hover:bg-surface-gray-1"
          >
            <FeatherIcon :name="action.icon" class="size-[18px] shrink-0 text-ink-gray-6" />
            <span class="text-xs font-medium leading-tight text-ink-gray-7">{{ action.label }}</span>
          </RouterLink>
        </div>
      </DashboardCard>

      <!--
        The demoted business intelligence: one line, still the last *closed*
        audit's figures, still dated. Kept because a duty manager has nowhere
        else in 16.7.1 to read occupancy, ADR and RevPAR — and dropped down here
        because none of the three changes what the desk does next.
      -->
      <div class="space-y-1">
        <p v-if="performance.available" class="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-ink-gray-6">
          <span class="font-medium text-ink-gray-7">{{ auditedCaption }}</span>
          <span v-for="figure in auditedFigures" :key="figure.key" class="flex items-baseline gap-1.5">
            {{ figure.label }}
            <span class="font-semibold tabular-nums text-ink-gray-8">{{ figure.value }}</span>
          </span>
        </p>

        <p class="text-xs text-ink-gray-5">
          {{ performance.available ? performanceHint : t('page.dashboard.performance_unavailable') }}
        </p>
      </div>
    </div>

    <RoomDetailDialog v-model="roomDialogOpen" :room="selectedRoom" @changed="reloadRack" />
  </div>
</template>

<script setup>
import { Button, FeatherIcon } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import ArrivalsPanel from '@/components/dashboard/ArrivalsPanel.vue'
import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import DeparturesPanel from '@/components/dashboard/DeparturesPanel.vue'
import DonutChart from '@/components/dashboard/DonutChart.vue'
import InHousePanel from '@/components/dashboard/InHousePanel.vue'
import KpiCard from '@/components/dashboard/KpiCard.vue'
import NightAuditCard from '@/components/dashboard/NightAuditCard.vue'
import RoomAttentionPanel from '@/components/dashboard/RoomAttentionPanel.vue'
import RoomStatusBoard from '@/components/dashboard/RoomStatusBoard.vue'
import StatTile from '@/components/dashboard/StatTile.vue'
import GlobalSearch from '@/components/operational/GlobalSearch.vue'
import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import PageHeader from '@/components/PageHeader.vue'
import RoomDetailDialog from '@/components/RoomDetailDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { hasField } from '@/resources/guests'
import {
  arrivalsBoardResource,
  dashboardResource,
  departuresBoardResource,
  FRONT_DESK_ROLES,
} from '@/resources/frontOffice'
import { nightAuditCurrentResource } from '@/resources/nightAudit'
import { roomRackResource } from '@/resources/rooms'
import { inHouseResource } from '@/resources/stays'
import { visibleNavigation } from '@/router/navigation'
import { property } from '@/stores/property'
import { session } from '@/stores/session'
import { workload as workloadStore } from '@/stores/workload'
import { formatCurrency, formatDate, formatNumber } from '@/utils/format'
import { t } from '@/utils/i18n'

const dashboard = dashboardResource()
const arrivals = arrivalsBoardResource()
const departures = departuresBoardResource()
const inHouse = inHouseResource()
const rack = roomRackResource()
const nightAudit = nightAuditCurrentResource()

// A fresh site returns zeros and `performance.available: false`, so every
// branch below reads through a default object rather than trusting the shape.
const rooms = computed(() => dashboard.data?.rooms || {})
const frontOffice = computed(() => dashboard.data?.front_office || {})
const revenue = computed(() => dashboard.data?.revenue || {})

/**
 * Whether this caller was told the folio-derived money at all.
 *
 * The `revenue` block is spliced out of the response for a caller without Guest
 * Folio read, so its absence means "not disclosed to your role" and never "the
 * day was quiet". `hasField` and not truthiness for exactly that reason: an
 * empty object is falsy and `?? 0` would render three confident zeros.
 */
const revenueDisclosed = computed(() => hasField(dashboard.data, 'revenue'))
const performance = computed(() => dashboard.data?.performance || {})
const workload = computed(() => dashboard.data?.workload || {})

const arrivalRows = computed(() => arrivals.data?.rows || [])
const departureRows = computed(() => departures.data?.rows || [])
const inHouseRows = computed(() => inHouse.data?.stays || [])

/** Every room of the property, flat: the attention queue ranks across the house. */
const rackRooms = computed(() =>
  (rack.data?.room_types || []).flatMap((group) => group.rooms || []),
)

const anyLoading = computed(() =>
  Boolean(
    dashboard.loading ||
      arrivals.loading ||
      departures.loading ||
      inHouse.loading ||
      rack.loading ||
      nightAudit.loading,
  ),
)

/**
 * Property and today's date - the *calendar* date, in the property's own zone.
 *
 * The business date used to be repeated here, and the navigation rail three
 * inches away was already showing it. Two copies of one figure is not emphasis;
 * it is a screen with nothing to say about what day it actually is, which is
 * exactly the question a desk asks when the two have come apart. The rail keeps
 * the operating day and now carries the lag warning beside it; the header
 * answers the other question.
 *
 * This is a civil date and nothing operational reads it: every posting, filter
 * and default on this screen still comes from the server's business date
 * (CLAUDE.md, "Dates: which kind, and when"). The zone is the property's, never
 * the browser's - a Doha hotel is on Doha's calendar whoever is looking at it.
 */
const subtitle = computed(() => {
  const data = dashboard.data
  if (!data) return ''

  return t('page.dashboard.subtitle_property', {
    property: data.property_name || data.property || '',
    date: formatDate(property.today.value, { weekday: 'long' }),
  })
})

/** Currency always comes from the payload; a bench may run several. */
const revenueCurrency = computed(
  () => revenue.value.currency || dashboard.data?.currency || property.currency.value,
)

const performanceCurrency = computed(() => performance.value.currency || revenueCurrency.value)

/**
 * Occupied against active inventory, right now.
 *
 * Deliberately separate from the audited occupancy: this one moves with every
 * check-in and is not a reportable figure. It leads the card because it is the
 * question the desk is actually asking; the audited figure sits under it, named
 * and dated (HPMS-DEC-030).
 */
const liveOccupancy = computed(() => {
  const active = Number(rooms.value.active || 0)
  const occupied = Number(rooms.value.occupied || 0)

  return active ? (occupied / active) * 100 : 0
})

const auditedCaption = computed(() =>
  performance.value.available
    ? t('page.dashboard.audited_on', { date: formatDate(performance.value.business_date) })
    : t('page.dashboard.not_audited'),
)

const auditedOccupancy = computed(() =>
  performance.value.available
    ? t('page.dashboard.audited_occupancy', {
        value: `${formatNumber(performance.value.occupancy_percentage ?? 0, 1)}%`,
        date: formatDate(performance.value.business_date),
      })
    : '',
)

const performanceHint = computed(() =>
  t('page.dashboard.performance_hint', { date: formatDate(performance.value.business_date) }),
)

/**
 * Occupancy, ADR and RevPAR from the last closed audit, as one line.
 *
 * Rendered as label/value pairs rather than an assembled sentence, so an Arabic
 * session gets its own digits and its own ordering without this page splicing
 * strings together.
 */
const auditedFigures = computed(() => {
  const p = performance.value

  return [
    {
      key: 'occupancy',
      label: t('page.dashboard.occupancy'),
      value: `${formatNumber(p.occupancy_percentage ?? 0, 1)}%`,
    },
    {
      key: 'adr',
      label: t('page.dashboard.adr'),
      value: formatCurrency(p.adr ?? 0, performanceCurrency.value),
    },
    {
      key: 'revpar',
      label: t('page.dashboard.revpar'),
      value: formatCurrency(p.revpar ?? 0, performanceCurrency.value),
    },
  ]
})

/** Sections the user may open, by navigation key. */
const reachable = computed(() => new Set(visibleNavigation(session).map((item) => item.key)))

const canSeeAudit = computed(() => reachable.value.has('night_audit'))

/**
 * The work counters, in rooms.
 *
 * Every one of these is a queue somebody has to empty. `arrivals_unassigned` is
 * the most time-critical of them and is new in 16.7.1; it is read defensively
 * because a bench mid-deploy may still be serving the older payload.
 */
const frontDeskTiles = computed(() => {
  const f = frontOffice.value
  const r = rooms.value
  const arrivalsTo = { name: 'Arrivals' }
  const departuresTo = { name: 'Departures' }
  const inHouseTo = { name: 'InHouse' }
  const rackTo = { name: 'RoomRack' }

  return [
    {
      key: 'arrivals_pending',
      label: t('page.dashboard.pending_check_ins'),
      value: f.arrivals_pending ?? 0,
      icon: 'bell',
      iconClass: 'bg-amber-50 text-amber-600',
      tone: 'text-ink-amber-3',
      to: arrivalsTo,
    },
    {
      key: 'arrivals_unassigned',
      label: t('page.dashboard.unassigned_arrivals'),
      value: f.arrivals_unassigned ?? 0,
      icon: 'user-x',
      iconClass: 'bg-red-50 text-red-600',
      tone: 'text-ink-red-3',
      to: arrivalsTo,
    },
    {
      // Vacant rooms housekeeping has not released. Counted on the server's
      // `vacant_not_ready`, never on `dirty`: dirty includes occupied stayovers,
      // and a "not ready" tile that counted those would read as most of the
      // hotel every morning. `vacant_not_ready` rather than `vacant_dirty`
      // because the attention queue below also lists In Progress and Inspection
      // Pending rooms, and a tile reading lower than the list under it is a
      // screen arguing with itself. Falls back to `vacant_dirty` so an older
      // payload still shows a number rather than a zero.
      key: 'rooms_not_ready',
      label: t('page.dashboard.rooms_not_ready'),
      value: r.vacant_not_ready ?? r.vacant_dirty ?? 0,
      icon: 'alert-triangle',
      iconClass: 'bg-amber-50 text-amber-600',
      tone: 'text-ink-amber-3',
      to: rackTo,
    },
    {
      key: 'departures_pending',
      label: t('page.dashboard.pending_check_outs'),
      value: f.departures_pending ?? 0,
      icon: 'clock',
      iconClass: 'bg-amber-50 text-amber-600',
      tone: 'text-ink-amber-3',
      to: departuresTo,
    },
    {
      key: 'due_out',
      label: t('page.dashboard.due_out'),
      value: f.due_out ?? 0,
      icon: 'briefcase',
      iconClass: 'bg-violet-50 text-violet-600',
      to: inHouseTo,
    },
    {
      // What can be sold this minute: the server's own `assignable`, which has
      // already applied all four status dimensions.
      key: 'assignable',
      label: t('page.dashboard.available'),
      value: r.assignable ?? 0,
      icon: 'check-circle',
      iconClass: 'bg-green-50 text-green-600',
      tone: 'text-ink-green-3',
      to: rackTo,
    },
    {
      key: 'in_house_rooms',
      label: t('page.dashboard.in_house_rooms'),
      value: f.in_house_rooms ?? 0,
      icon: 'home',
      iconClass: 'bg-blue-50 text-blue-600',
      to: inHouseTo,
    },
  ]
})

const workloadItems = computed(() => {
  const w = workload.value
  const open = reachable.value
  const linkIf = (key, route) => (open.has(key) ? { name: route } : null)

  return [
    {
      key: 'housekeeping',
      label: t('page.dashboard.housekeeping_open'),
      value: w.housekeeping_open ?? 0,
      hint: t('page.dashboard.work.pending'),
      icon: 'clipboard',
      tone: 'text-blue-600',
      surface: 'bg-blue-50',
      to: linkIf('housekeeping', 'Housekeeping'),
    },
    {
      key: 'maintenance',
      label: t('page.dashboard.maintenance_open'),
      value: w.maintenance_open ?? 0,
      hint: t('page.dashboard.work.open'),
      icon: 'tool',
      tone: 'text-amber-600',
      surface: 'bg-amber-50',
      to: linkIf('maintenance', 'Maintenance'),
    },
    {
      key: 'guest_requests',
      label: t('page.dashboard.guest_requests_open'),
      value: w.guest_requests_open ?? 0,
      hint: t('page.dashboard.work.open'),
      icon: 'message-circle',
      tone: 'text-violet-600',
      surface: 'bg-violet-50',
      to: linkIf('guest_services', 'GuestServices'),
    },
  ]
})

/**
 * The money strip: what came in, and what is still owed.
 *
 * Posted room revenue keeps its place and its sentence — `_revenue_today` posts
 * room charges at the Night Audit, so it reads zero for most of the day by
 * design — but it gets no headline, because a figure that is honestly zero until
 * midnight cannot lead a screen.
 */
const moneyLines = computed(() => {
  const r = revenue.value

  return [
    {
      key: 'payments',
      label: t('page.dashboard.payments_received'),
      value: r.payments_received ?? 0,
      tone: 'text-ink-green-3',
    },
    {
      key: 'outstanding',
      label: t('page.dashboard.outstanding_balance'),
      value: r.outstanding_balance ?? 0,
      tone: 'text-ink-amber-3',
    },
    {
      key: 'room_revenue',
      label: t('page.dashboard.room_revenue'),
      value: r.room_revenue_posted ?? 0,
      tone: 'text-ink-gray-7',
    },
  ]
})

function makeAction(key, labelKey, icon, route) {
  return { key, label: t(labelKey), icon, to: { name: route } }
}

const quickActions = computed(() => {
  const actions = []
  const open = reachable.value

  // Offered only to roles the reservation service accepts; the server refuses
  // the rest anyway, and an action that always fails is worse than none.
  if (session.hasRole(FRONT_DESK_ROLES)) {
    actions.push(
      makeAction('new', 'page.dashboard.action.new_reservation', 'plus-circle', 'ReservationNew'),
    )
  }

  // A walk-in is an arrival nobody knew was coming, and it is the second most
  // common thing a counter does. Gated on the same roles the sidebar gates the
  // walk-in screen with.
  if (open.has('walk_in')) {
    actions.push(makeAction('walk_in', 'page.dashboard.action.walk_in', 'user-plus', 'WalkIn'))
  }

  // "Find a guest" is a different question from "find a reservation": one is
  // asked about somebody standing at the counter, the other about a booking.
  if (open.has('guests')) {
    actions.push(makeAction('guest_search', 'page.dashboard.action.guest_search', 'user', 'Guests'))
  }

  return actions.concat([
    makeAction('search', 'page.dashboard.action.search_reservation', 'search', 'Reservations'),
    makeAction('arrivals', 'page.dashboard.action.arrivals', 'log-in', 'Arrivals'),
    makeAction('departures', 'page.dashboard.action.departures', 'log-out', 'Departures'),
    makeAction('in_house', 'page.dashboard.action.in_house', 'users', 'InHouse'),
    makeAction('room_rack', 'page.dashboard.action.room_rack', 'grid', 'RoomRack'),
    makeAction('availability', 'page.dashboard.action.availability', 'calendar', 'Availability'),
    makeAction('calendar', 'page.dashboard.action.calendar', 'columns', 'Calendar'),
  ])
})

const roomDialogOpen = ref(false)
const selectedRoom = ref(null)

function openRoom(room) {
  selectedRoom.value = room
  roomDialogOpen.value = true
}

function reloadRack() {
  rack.fetch({ property: property.activeName.value })
}

function reload() {
  const params = { property: property.activeName.value }

  dashboard.fetch(params)
  arrivals.fetch(params)
  departures.fetch(params)
  inHouse.fetch(params)
  rack.fetch(params)

  // Gated on the same role filter the sidebar uses: the audit endpoint refuses a
  // user without Night Audit read, and a refusal the screen asked for anyway is
  // an error message nobody can act on.
  if (canSeeAudit.value) {
    nightAudit.fetch(params)
  }
}

// The badges in the navigation come from the counts this screen already loads
// rather than from a request of their own.
watch(
  () => dashboard.data?.workload,
  (counts) => counts && workloadStore.set(counts),
)

// Every figure is scoped to one property, so switching property reloads rather
// than leaving another property's numbers on screen.
watch(() => property.activeName.value, reload, { immediate: true })
</script>
