<!--
  Front office dashboard: what the shift on duty needs to know about the active
  property on its business date — arrivals and departures still to work, room
  inventory, last audited performance, what has been posted so far and what work
  is still open. One request feeds the whole screen; every figure is the
  server's, none is derived here except the live occupancy percentage, which is
  labelled as such.
-->
<template>
  <div>
    <PageHeader :title="t('page.dashboard.title')" :subtitle="subtitle">
      <template #actions>
        <Button variant="subtle" :loading="dashboard.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <LoadingState v-if="dashboard.loading && !dashboard.data" />
    <ErrorState v-else-if="dashboard.error" :error="dashboard.error" :on-retry="reload" />
    <EmptyState v-else-if="!dashboard.data" />

    <div v-else class="space-y-6 p-5">
      <section v-for="section in sections" :key="section.key" class="space-y-2">
        <h2 class="text-base font-medium text-ink-gray-8">{{ section.title }}</h2>

        <div v-if="section.tiles.length" class="grid grid-cols-2 gap-3" :class="section.columns">
          <!-- A tile is a link only where the user can actually reach the board. -->
          <component
            :is="tile.to ? RouterLink : 'div'"
            v-for="tile in section.tiles"
            :key="tile.key"
            v-bind="tile.to ? { to: tile.to } : {}"
            class="rounded border border-outline-gray-1 px-3 py-2"
            :class="[tile.span, tile.to ? 'transition-colors hover:bg-surface-gray-1' : '']"
          >
            <span class="block text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</span>
            <span class="mt-0.5 block text-lg font-semibold" :class="tile.tone || 'text-ink-gray-9'">
              {{ tile.value }}
            </span>
            <span v-if="tile.hint" class="mt-1 block text-xs text-ink-gray-5">{{ tile.hint }}</span>
          </component>
        </div>

        <p v-if="section.hint" class="max-w-3xl text-xs text-ink-gray-5">{{ section.hint }}</p>
      </section>

      <section class="space-y-2">
        <h2 class="text-base font-medium text-ink-gray-8">
          {{ t('page.dashboard.section.quick_actions') }}
        </h2>

        <div class="flex flex-wrap gap-2">
          <RouterLink
            v-for="action in quickActions"
            :key="action.key"
            :to="action.to"
            class="flex items-center gap-2 rounded border border-outline-gray-1 px-3 py-2 text-p-sm
              text-ink-gray-8 transition-colors hover:bg-surface-gray-1"
          >
            <FeatherIcon :name="action.icon" class="size-4 shrink-0 text-ink-gray-5" />
            {{ action.label }}
          </RouterLink>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { Button, FeatherIcon } from 'frappe-ui'
import { computed, watch } from 'vue'
import { RouterLink } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { dashboardResource, FRONT_DESK_ROLES } from '@/resources/frontOffice'
import { visibleNavigation } from '@/router/navigation'
import { property } from '@/stores/property'
import { session } from '@/stores/session'
import { formatCurrency, formatDate, formatNumber } from '@/utils/format'
import { t } from '@/utils/i18n'

const dashboard = dashboardResource()

// A fresh site returns zeros and `performance.available: false`, so every
// branch below reads through a default object rather than trusting the shape.
const rooms = computed(() => dashboard.data?.rooms || {})
const frontOffice = computed(() => dashboard.data?.front_office || {})
const revenue = computed(() => dashboard.data?.revenue || {})
const performance = computed(() => dashboard.data?.performance || {})
const workload = computed(() => dashboard.data?.workload || {})

const subtitle = computed(() => {
  const data = dashboard.data
  if (!data) return ''

  return t('page.dashboard.subtitle_property', {
    property: data.property_name || data.property || '',
    date: formatDate(data.business_date),
  })
})

/** Currency always comes from the payload; a bench may run several. */
const revenueCurrency = computed(
  () => revenue.value.currency || dashboard.data?.currency || property.currency.value,
)

/**
 * Occupied against active inventory, right now.
 *
 * Deliberately separate from the audited occupancy in the performance section:
 * this one moves with every check-in and is not a reportable figure.
 */
const liveOccupancy = computed(() => {
  const active = Number(rooms.value.active || 0)
  const occupied = Number(rooms.value.occupied || 0)

  return active ? (occupied / active) * 100 : 0
})

const GREEN = 'text-ink-green-3'
const AMBER = 'text-ink-amber-3'
const RED = 'text-ink-red-3'

/** One bordered figure. `to` makes it a link, `hint` adds a muted line under it. */
function makeTile(key, labelKey, value, extra = {}) {
  return { key, label: t(labelKey), value: value ?? 0, ...extra }
}

function makeAction(key, labelKey, icon, route) {
  return { key, label: t(labelKey), icon, to: { name: route } }
}

/** Sections the user may open, by navigation key. */
const reachable = computed(() => new Set(visibleNavigation(session).map((item) => item.key)))

const frontDeskTiles = computed(() => {
  const f = frontOffice.value
  const arrivals = { name: 'Arrivals' }
  const departures = { name: 'Departures' }
  const inHouse = { name: 'InHouse' }

  return [
    makeTile('arrivals', 'page.dashboard.arrivals_today', f.arrivals_expected, { to: arrivals }),
    makeTile('arrivals_pending', 'page.dashboard.pending_check_ins', f.arrivals_pending, {
      to: arrivals,
      tone: AMBER,
    }),
    makeTile('departures', 'page.dashboard.departures_today', f.departures_expected, {
      to: departures,
    }),
    makeTile('departures_pending', 'page.dashboard.pending_check_outs', f.departures_pending, {
      to: departures,
      tone: AMBER,
    }),
    makeTile('in_house_rooms', 'page.dashboard.in_house_rooms', f.in_house_rooms, { to: inHouse }),
    makeTile('in_house_guests', 'page.dashboard.in_house_guests', f.in_house_guests, { to: inHouse }),
    makeTile('due_out', 'page.dashboard.due_out', f.due_out, { to: inHouse }),
  ]
})

const roomTiles = computed(() => {
  const r = rooms.value
  const to = { name: 'RoomRack' }

  return [
    makeTile('total', 'page.dashboard.total_rooms', r.total, { to }),
    makeTile('occupied', 'page.dashboard.occupied', r.occupied, { to, tone: AMBER }),
    makeTile('assignable', 'page.dashboard.available', r.assignable, { to, tone: GREEN }),
    makeTile('vacant_clean', 'page.dashboard.vacant_clean', r.vacant_clean, { to, tone: GREEN }),
    makeTile('vacant_dirty', 'page.dashboard.vacant_dirty', r.vacant_dirty, { to, tone: RED }),
    makeTile('out_of_order', 'page.dashboard.out_of_order', r.out_of_order, { to, tone: RED }),
    makeTile('out_of_service', 'page.dashboard.out_of_service', r.out_of_service, { to, tone: RED }),
    makeTile('blocked', 'page.dashboard.blocked', r.blocked, { to, tone: RED }),
    makeTile('live', 'page.dashboard.live_occupancy', `${formatNumber(liveOccupancy.value, 1)}%`, {
      hint: t('page.dashboard.live_occupancy_hint'),
      span: 'col-span-2',
    }),
  ]
})

// Nothing at all is shown until an audit has closed: a zero here would read as
// an occupancy of zero rather than "not yet measured".
const performanceTiles = computed(() => {
  const p = performance.value
  if (!p.available) return []

  const money = (value) => formatCurrency(value ?? 0, p.currency)

  return [
    makeTile(
      'occupancy',
      'page.dashboard.occupancy',
      `${formatNumber(p.occupancy_percentage ?? 0, 2)}%`,
    ),
    makeTile('adr', 'page.dashboard.adr', money(p.adr)),
    makeTile('revpar', 'page.dashboard.revpar', money(p.revpar)),
    makeTile('room_revenue', 'page.dashboard.room_revenue', money(p.room_revenue)),
  ]
})

const revenueTiles = computed(() => {
  const r = revenue.value
  const money = (value) => formatCurrency(value ?? 0, revenueCurrency.value)

  return [
    makeTile('room_revenue', 'page.dashboard.room_revenue', money(r.room_revenue_posted)),
    makeTile('payments', 'page.dashboard.payments_received', money(r.payments_received), {
      tone: GREEN,
    }),
    makeTile('outstanding', 'page.dashboard.outstanding_balance', money(r.outstanding_balance), {
      tone: AMBER,
    }),
  ]
})

const workloadTiles = computed(() => {
  const w = workload.value
  const open = reachable.value
  const linkIf = (key, route) => (open.has(key) ? { name: route } : null)

  return [
    makeTile('housekeeping', 'page.dashboard.housekeeping_open', w.housekeeping_open, {
      to: linkIf('housekeeping', 'Housekeeping'),
    }),
    makeTile('maintenance', 'page.dashboard.maintenance_open', w.maintenance_open, {
      to: linkIf('maintenance', 'Maintenance'),
    }),
    makeTile('guest_requests', 'page.dashboard.guest_requests_open', w.guest_requests_open, {
      to: linkIf('guest_services', 'GuestServices'),
    }),
  ]
})

const sections = computed(() => [
  {
    key: 'front_desk',
    title: t('page.dashboard.section.front_desk'),
    columns: 'sm:grid-cols-4 lg:grid-cols-7',
    tiles: frontDeskTiles.value,
  },
  {
    key: 'rooms',
    title: t('page.dashboard.section.rooms'),
    columns: 'sm:grid-cols-4 lg:grid-cols-5',
    tiles: roomTiles.value,
  },
  {
    key: 'performance',
    title: t('page.dashboard.section.performance'),
    columns: 'sm:grid-cols-4',
    tiles: performanceTiles.value,
    hint: performance.value.available
      ? t('page.dashboard.performance_hint', { date: formatDate(performance.value.business_date) })
      : t('page.dashboard.performance_unavailable'),
  },
  {
    key: 'revenue',
    title: t('page.dashboard.section.revenue'),
    columns: 'sm:grid-cols-3',
    tiles: revenueTiles.value,
    hint: t('page.dashboard.revenue_hint'),
  },
  {
    key: 'workload',
    title: t('page.dashboard.section.workload'),
    columns: 'sm:grid-cols-3',
    tiles: workloadTiles.value,
  },
])

const quickActions = computed(() => {
  const actions = []

  // Offered only to roles the reservation service accepts; the server refuses
  // the rest anyway, and an action that always fails is worse than none.
  if (session.hasRole(FRONT_DESK_ROLES)) {
    actions.push(
      makeAction('new', 'page.dashboard.action.new_reservation', 'plus-circle', 'ReservationNew'),
    )
  }

  return actions.concat([
    makeAction('search', 'page.dashboard.action.search_reservation', 'book-open', 'Reservations'),
    makeAction('arrivals', 'page.dashboard.action.arrivals', 'log-in', 'Arrivals'),
    makeAction('departures', 'page.dashboard.action.departures', 'log-out', 'Departures'),
    makeAction('in_house', 'page.dashboard.action.in_house', 'users', 'InHouse'),
    makeAction('room_rack', 'page.dashboard.action.room_rack', 'grid', 'RoomRack'),
    makeAction('availability', 'page.dashboard.action.availability', 'search', 'Availability'),
    makeAction('calendar', 'page.dashboard.action.calendar', 'calendar', 'Calendar'),
  ])
})

function reload() {
  dashboard.fetch({ property: property.activeName.value })
}

// Every figure is scoped to one property, so switching property reloads rather
// than leaving another property's numbers on screen.
watch(() => property.activeName.value, reload, { immediate: true })
</script>
