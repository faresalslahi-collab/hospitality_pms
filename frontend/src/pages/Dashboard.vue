<!--
  Front office dashboard: what the shift on duty needs to know about the active
  property on its business date — the day's performance, arrivals and
  departures still to work, the state of the house, where tonight's close has
  got to, and what work is still open.

  Every figure is the server's. The only two derived here are the live
  occupancy percentage and the change against the previous audited day, and
  both are labelled as what they are.

  On request count: the KPI block is still one aggregate call, as it was. The
  boards, the rack and the audit are separate reads because they are separate
  screens' worth of data and separate permissions — a housekeeper who cannot
  read Reservation gets the rest of the dashboard rather than an error page.
  They are fetched once per load and never polled; the header's Refresh is the
  only thing that repeats them.
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

    <LoadingState v-if="dashboard.loading && !dashboard.data" />
    <ErrorState v-else-if="dashboard.error" :error="dashboard.error" :on-retry="reload" />
    <EmptyState v-else-if="!dashboard.data" />

    <div v-else class="space-y-4 p-4 lg:p-5">
      <!-- Performance, from the last closed Night Audit, and today's live house. -->
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <KpiCard
          :label="t('page.dashboard.occupancy')"
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
        </KpiCard>

        <KpiCard
          :label="t('page.dashboard.adr')"
          :value="performance.available ? formatNumber(performance.adr ?? 0, 2) : '—'"
          :prefix="performance.available ? performanceCurrency : ''"
          :caption="auditedCaption"
          :change="change('adr')"
          icon="tag"
          icon-class="bg-green-50 text-green-600"
        />

        <KpiCard
          :label="t('page.dashboard.revpar')"
          :value="performance.available ? formatNumber(performance.revpar ?? 0, 2) : '—'"
          :prefix="performance.available ? performanceCurrency : ''"
          :caption="auditedCaption"
          :change="change('revpar')"
          icon="trending-up"
          icon-class="bg-violet-50 text-violet-600"
        />

        <KpiCard
          :label="t('page.dashboard.room_revenue')"
          :value="performance.available ? formatNumber(performance.room_revenue ?? 0, 2) : '—'"
          :prefix="performance.available ? performanceCurrency : ''"
          :caption="auditedCaption"
          :change="change('room_revenue')"
          icon="dollar-sign"
          icon-class="bg-amber-50 text-amber-600"
        >
          <!-- No closed audits, no trend: an empty plot area would take height
               from the card for the sake of drawing nothing. -->
          <template v-if="revenueTrend.length" #footer>
            <div class="h-8 w-full">
              <MiniBars :points="revenueTrend" :aria-label="t('page.dashboard.revenue_trend_label')" />
            </div>
          </template>
        </KpiCard>

        <SourceMixCard class="sm:col-span-2 lg:col-span-2 xl:col-span-2" :arrivals="arrivalRows" />
      </div>

      <!-- The day's position at the desk, counted in rooms. -->
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7">
        <StatTile v-for="tile in frontDeskTiles" :key="tile.key" v-bind="tile" />
      </div>

      <div class="grid gap-4 lg:grid-cols-4">
        <NightAuditCard
          v-if="canSeeAudit"
          :audit="nightAudit.data?.audit || null"
          :blocking-count="nightAudit.data?.blocking_count || 0"
        />

        <RoomStatusBoard
          :class="canSeeAudit ? 'lg:col-span-3' : 'lg:col-span-4'"
          :room-types="rack.data?.room_types || []"
          :loading="rack.loading && !rack.data"
          @select="openRoom"
        />
      </div>

      <div class="grid gap-4 xl:grid-cols-2">
        <ArrivalsPanel :arrivals="arrivalRows" :loading="arrivals.loading && !arrivals.data" />
        <DeparturesPanel :departures="departureRows" :loading="departures.loading && !departures.data" />
      </div>

      <div class="grid gap-4 xl:grid-cols-3">
        <DashboardCard :title="t('page.dashboard.section.workload')" dense>
          <div class="grid gap-2.5 sm:grid-cols-3 xl:grid-cols-1">
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

        <!-- Posted against the business date so far, kept apart from the audited
             figures above so nobody reads one as the other. -->
        <DashboardCard
          :title="t('page.dashboard.section.revenue')"
          :subtitle="t('page.dashboard.revenue_subtitle')"
          dense
        >
          <dl class="space-y-2.5">
            <div
              v-for="line in revenueLines"
              :key="line.key"
              class="flex items-baseline justify-between gap-3 border-b border-outline-gray-1 pb-2.5 last:border-b-0 last:pb-0"
            >
              <dt class="min-w-0 truncate text-p-sm text-ink-gray-6">{{ line.label }}</dt>
              <dd class="shrink-0 text-p-base font-semibold tabular-nums" :class="line.tone">{{ line.value }}</dd>
            </div>
          </dl>
        </DashboardCard>

        <DashboardCard :title="t('page.dashboard.section.quick_actions')" dense>
          <div class="grid grid-cols-3 gap-2 sm:grid-cols-4 xl:grid-cols-3">
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
      </div>

      <p class="text-xs text-ink-gray-5">
        {{ performance.available ? performanceHint : t('page.dashboard.performance_unavailable') }}
      </p>
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
import KpiCard from '@/components/dashboard/KpiCard.vue'
import MiniBars from '@/components/dashboard/MiniBars.vue'
import NightAuditCard from '@/components/dashboard/NightAuditCard.vue'
import RoomStatusBoard from '@/components/dashboard/RoomStatusBoard.vue'
import SourceMixCard from '@/components/dashboard/SourceMixCard.vue'
import PageHeader from '@/components/PageHeader.vue'
import RoomDetailDialog from '@/components/RoomDetailDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import {
  arrivalsBoardResource,
  dashboardResource,
  departuresBoardResource,
  FRONT_DESK_ROLES,
} from '@/resources/frontOffice'
import { nightAuditCurrentResource, nightAuditHistoryResource } from '@/resources/nightAudit'
import { roomRackResource } from '@/resources/rooms'
import { visibleNavigation } from '@/router/navigation'
import { property } from '@/stores/property'
import { session } from '@/stores/session'
import { workload as workloadStore } from '@/stores/workload'
import { formatCurrency, formatDate, formatNumber } from '@/utils/format'
import { t } from '@/utils/i18n'

const dashboard = dashboardResource()
const arrivals = arrivalsBoardResource()
const departures = departuresBoardResource()
const rack = roomRackResource()
const nightAudit = nightAuditCurrentResource()
const auditHistory = nightAuditHistoryResource()

// A fresh site returns zeros and `performance.available: false`, so every
// branch below reads through a default object rather than trusting the shape.
const rooms = computed(() => dashboard.data?.rooms || {})
const frontOffice = computed(() => dashboard.data?.front_office || {})
const revenue = computed(() => dashboard.data?.revenue || {})
const performance = computed(() => dashboard.data?.performance || {})
const workload = computed(() => dashboard.data?.workload || {})

const arrivalRows = computed(() => arrivals.data?.rows || [])
const departureRows = computed(() => departures.data?.rows || [])

const anyLoading = computed(() =>
  Boolean(dashboard.loading || arrivals.loading || departures.loading || rack.loading || nightAudit.loading),
)

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

const performanceCurrency = computed(() => performance.value.currency || revenueCurrency.value)

/**
 * Occupied against active inventory, right now.
 *
 * Deliberately separate from the audited occupancy: this one moves with every
 * check-in and is not a reportable figure. It leads the card because it is the
 * question the desk is actually asking; the audited figure sits under it,
 * named and dated (HPMS-DEC-030).
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
 * Closed audits, most recent first.
 *
 * Only closed ones: an audit still in progress has figures that are still
 * moving, and comparing against a moving number is how a dashboard reports a
 * collapse in ADR that is really a night audit half way through posting.
 */
const closedAudits = computed(() =>
  (auditHistory.data?.audits || []).filter((audit) => audit.audit_status === 'Closed'),
)

/** Percentage change of one audited figure against the previous audited day. */
function change(field) {
  const [latest, previous] = closedAudits.value

  if (!latest || !previous) return null

  const from = Number(previous[field] || 0)
  const to = Number(latest[field] || 0)

  // No baseline means no percentage: "up from zero" is not a percentage, and
  // rendering one would put an infinity on the wall.
  if (Math.abs(from) < 0.005) return null

  return ((to - from) / Math.abs(from)) * 100
}

/** Room revenue over the recent closed days, oldest first. */
const revenueTrend = computed(() =>
  [...closedAudits.value]
    .slice(0, 7)
    .reverse()
    .map((audit) => ({
      key: audit.name,
      value: Number(audit.room_revenue || 0),
      title: `${formatDate(audit.business_date)} · ${formatCurrency(audit.room_revenue ?? 0, audit.currency || performanceCurrency.value)}`,
    })),
)

/** Sections the user may open, by navigation key. */
const reachable = computed(() => new Set(visibleNavigation(session).map((item) => item.key)))

const canSeeAudit = computed(() => reachable.value.has('night_audit'))

const frontDeskTiles = computed(() => {
  const f = frontOffice.value
  const arrivalsTo = { name: 'Arrivals' }
  const departuresTo = { name: 'Departures' }
  const inHouse = { name: 'InHouse' }

  return [
    {
      key: 'arrivals',
      label: t('page.dashboard.arrivals_today'),
      value: f.arrivals_expected ?? 0,
      icon: 'log-in',
      iconClass: 'bg-blue-50 text-blue-600',
      to: arrivalsTo,
    },
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
      key: 'departures',
      label: t('page.dashboard.departures_today'),
      value: f.departures_expected ?? 0,
      icon: 'log-out',
      iconClass: 'bg-green-50 text-green-600',
      to: departuresTo,
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
      key: 'in_house_rooms',
      label: t('page.dashboard.in_house_rooms'),
      value: f.in_house_rooms ?? 0,
      icon: 'home',
      iconClass: 'bg-blue-50 text-blue-600',
      to: inHouse,
    },
    {
      key: 'in_house_guests',
      label: t('page.dashboard.in_house_guests'),
      value: f.in_house_guests ?? 0,
      icon: 'users',
      iconClass: 'bg-blue-50 text-blue-600',
      to: inHouse,
    },
    {
      key: 'due_out',
      label: t('page.dashboard.due_out'),
      value: f.due_out ?? 0,
      icon: 'briefcase',
      iconClass: 'bg-violet-50 text-violet-600',
      to: inHouse,
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

const revenueLines = computed(() => {
  const r = revenue.value
  const money = (value) => formatCurrency(value ?? 0, revenueCurrency.value)

  return [
    {
      key: 'room_revenue',
      label: t('page.dashboard.room_revenue'),
      value: money(r.room_revenue_posted),
      tone: 'text-ink-gray-9',
    },
    {
      key: 'payments',
      label: t('page.dashboard.payments_received'),
      value: money(r.payments_received),
      tone: 'text-ink-green-3',
    },
    {
      key: 'outstanding',
      label: t('page.dashboard.outstanding_balance'),
      value: money(r.outstanding_balance),
      tone: 'text-ink-amber-3',
    },
  ]
})

function makeAction(key, labelKey, icon, route) {
  return { key, label: t(labelKey), icon, to: { name: route } }
}

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
  rack.fetch(params)

  // Gated on the same role filter the sidebar uses: the audit endpoints refuse
  // a user without Night Audit read, and a refusal the screen asked for anyway
  // is an error message nobody can act on.
  if (canSeeAudit.value) {
    nightAudit.fetch(params)
    auditHistory.fetch({ ...params, limit: 8 })
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
