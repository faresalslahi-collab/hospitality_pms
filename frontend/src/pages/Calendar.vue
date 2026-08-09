<!--
  Reservation calendar: rooms down the side, dates across the top, occupancy
  drawn as bars.

  Both axes are bounded so a 500-room property stays cheap. The server returns
  one page of rooms (25) over a capped date window, and occupancy arrives as
  date ranges, so a week-long stay is one element rather than seven. Paging
  replaces the visible page instead of accumulating it, and every view change is
  a single request.
-->
<template>
  <div>
    <PageHeader :title="t('page.calendar.title')" :subtitle="t('page.calendar.subtitle')">
      <template #actions>
        <Button variant="subtle" :loading="grid.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <div class="space-y-4 p-5">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FormControl v-model="fromDate" type="date" :label="t('page.calendar.from')" />
        <FormControl
          v-model.number="filters.days"
          type="select"
          :label="t('page.calendar.days')"
          :options="dayOptions"
        />
        <FormControl
          v-model="filters.roomType"
          type="select"
          :label="t('page.calendar.room_type')"
          :options="roomTypeOptions"
        />

        <div class="flex flex-wrap items-end gap-2">
          <Button variant="subtle" @click="goToday">{{ t('common.today') }}</Button>
          <Button variant="subtle" @click="shiftWindow(-1)">
            <template #prefix><FeatherIcon name="chevron-left" class="size-4 flip-rtl" /></template>
            {{ t('common.previous') }}
          </Button>
          <Button variant="subtle" @click="shiftWindow(1)">
            <template #suffix><FeatherIcon name="chevron-right" class="size-4 flip-rtl" /></template>
            {{ t('common.next') }}
          </Button>
        </div>
      </div>

      <LoadingState v-if="grid.loading && !grid.data" />

      <ErrorState v-else-if="grid.error" :error="grid.error" :on-retry="reload" />

      <EmptyState v-else-if="!rows.length" :message="t('page.calendar.empty')" />

      <div v-else class="space-y-4">
        <p v-if="capped" class="text-p-sm text-ink-gray-6">
          {{ t('page.calendar.window_capped', { days: dates.length }) }}
        </p>

        <!-- Only this container scrolls sideways; the page body never does. -->
        <div class="overflow-x-auto rounded border border-outline-gray-1">
          <div class="min-w-max">
            <div class="flex border-b border-outline-gray-1 bg-surface-gray-1">
              <div
                class="sticky start-0 z-10 w-36 shrink-0 border-e border-outline-gray-1 bg-surface-gray-1 p-2 text-xs uppercase tracking-wide text-ink-gray-5"
              >
                {{ t('page.calendar.room') }}
              </div>

              <div class="grid" :style="{ gridTemplateColumns: columnTemplate }">
                <div
                  v-for="date in dates"
                  :key="date"
                  class="border-e border-outline-gray-1 px-1 py-2 text-center last:border-e-0"
                >
                  <span class="block text-xs font-medium text-ink-gray-8">{{ dayLabel(date) }}</span>
                  <span class="block text-xs text-ink-gray-5">{{ weekdayLabel(date) }}</span>
                </div>
              </div>
            </div>

            <div
              v-for="row in rows"
              :key="row.room.name"
              class="flex border-b border-outline-gray-1 last:border-b-0"
            >
              <div
                class="sticky start-0 z-10 w-36 shrink-0 border-e border-outline-gray-1 bg-surface-white p-2"
              >
                <p class="truncate text-p-sm font-medium text-ink-gray-9">{{ row.room.room_number }}</p>
                <p class="truncate text-xs text-ink-gray-5">
                  {{ row.room.room_type_name || row.room.room_type }}
                </p>
              </div>

              <!--
                One CSS grid per room row. Bars are placed with grid-column,
                which mirrors on its own under RTL; positioning them with
                left/right offsets would not.
              -->
              <div class="grid" :style="rowStyle(row)">
                <div
                  v-for="(date, index) in dates"
                  :key="date"
                  class="border-e border-outline-gray-1 last:border-e-0"
                  :style="{ gridColumn: String(index + 1), gridRow: '1 / -1' }"
                />

                <component
                  :is="segment.reservation ? 'button' : 'div'"
                  v-for="segment in row.segments"
                  :key="segment.key"
                  :type="segment.reservation ? 'button' : null"
                  :title="segment.title"
                  class="m-0.5 flex items-center overflow-hidden rounded border px-1.5 text-xs"
                  :class="[segment.classes, segment.reservation ? 'hover:opacity-80' : '']"
                  :style="segment.style"
                  @click="open(segment)"
                >
                  <span class="truncate">{{ segment.label }}</span>
                </component>
              </div>
            </div>
          </div>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-p-sm text-ink-gray-6">
            {{ t('page.calendar.rooms_shown', { shown: rows.length, total: grid.data.total_rooms }) }}
          </p>

          <div class="flex items-center gap-2">
            <Button v-if="page.start > 0" variant="subtle" :loading="grid.loading" @click="turnPage(-1)">
              <template #prefix><FeatherIcon name="chevron-left" class="size-4 flip-rtl" /></template>
              {{ t('common.previous') }}
            </Button>
            <Button
              v-if="grid.data.has_more"
              variant="subtle"
              :loading="grid.loading"
              @click="turnPage(1)"
            >
              {{ t('common.load_more') }}
            </Button>
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-4">
          <span class="text-xs uppercase tracking-wide text-ink-gray-5">
            {{ t('page.calendar.legend') }}
          </span>
          <span
            v-for="item in legend"
            :key="item.kind"
            class="flex items-center gap-1.5 text-p-sm text-ink-gray-7"
          >
            <span class="size-3 rounded border" :class="barClasses(item.kind)" />
            {{ t(item.key) }}
          </span>
        </div>

        <section v-if="unassigned.length" class="space-y-2">
          <div>
            <h2 class="text-base font-medium text-ink-gray-8">{{ t('page.calendar.unassigned') }}</h2>
            <p class="mt-0.5 text-p-sm text-ink-gray-6">{{ t('page.calendar.unassigned_hint') }}</p>
          </div>

          <div class="divide-y divide-outline-gray-1 rounded border border-outline-gray-1">
            <button
              v-for="item in unassigned"
              :key="item.key"
              type="button"
              class="flex w-full flex-wrap items-center justify-between gap-3 p-2 text-start hover:bg-surface-gray-1"
              @click="openReservation(item.reservation)"
            >
              <span class="min-w-0">
                <span class="block truncate text-p-sm font-medium text-ink-gray-9">{{ item.label }}</span>
                <span class="block truncate text-xs text-ink-gray-5">
                  {{ item.room_type_name || item.room_type }}
                </span>
              </span>

              <span class="text-p-sm whitespace-nowrap text-ink-gray-6">
                {{ formatDate(item.from_date) }} – {{ formatDate(item.to_date) }}
                <span class="text-ink-gray-5">
                  ({{ t('page.calendar.nights', { count: nightsBetween(item.from_date, item.to_date) }) }})
                </span>
              </span>

              <Badge variant="subtle" :theme="reservationStatusTheme(item.status)" :label="item.status" />
            </button>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { CALENDAR_BAR_THEME, calendarGridResource } from '@/resources/frontOffice'
import { reservationStatusTheme } from '@/resources/reservations'
import { property } from '@/stores/property'
import { formatDate, toServerDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const ROOMS_PER_PAGE = 25

const BAR_CLASSES = {
  green: 'border-outline-green-2 bg-surface-green-2 text-ink-green-3',
  blue: 'border-outline-blue-1 bg-surface-blue-1 text-ink-blue-3',
  red: 'border-outline-red-2 bg-surface-red-1 text-ink-red-3',
}

const router = useRouter()
const grid = calendarGridResource()

const filters = reactive({ from: null, days: 14, roomType: '' })
const page = reactive({ start: 0 })

const legend = [
  { kind: 'stay', key: 'page.calendar.legend.stay' },
  { kind: 'reservation', key: 'page.calendar.legend.reservation' },
  { kind: 'block', key: 'page.calendar.legend.block' },
]

const dayOptions = [7, 14, 21, 28].map((value) => ({ label: String(value), value }))

/**
 * The window start.
 *
 * Left unset until the user picks a date so that it follows the property's
 * business date, which is not necessarily today and arrives with the property.
 */
const fromDate = computed({
  get: () => filters.from || toServerDate(property.businessDate.value) || toServerDate(new Date()),
  set: (value) => {
    filters.from = value || null
  },
})

const days = computed(() => Number(filters.days) || 14)
const toDate = computed(() => shiftDays(fromDate.value, days.value - 1))

const dates = computed(() => grid.data?.dates || [])
const unassigned = computed(() => grid.data?.unassigned || [])
const capped = computed(() => Boolean(dates.value.length) && dates.value.length < days.value)

const columnTemplate = computed(() => {
  const count = dates.value.length
  const width = count <= 7 ? '5.5rem' : count <= 14 ? '4.25rem' : '3.5rem'

  return `repeat(${count}, ${width})`
})

const roomTypeOptions = computed(() => [
  { label: t('page.calendar.all_room_types'), value: '' },
  ...(grid.data?.room_types || []).map((type) => ({
    label: type.room_type_name || type.name,
    value: type.name,
  })),
])

/** One entry per visible room, with its bars already placed in the grid. */
const rows = computed(() => {
  const window = dates.value
  if (!window.length) return []

  const bars = grid.data?.bars || []

  return (grid.data?.rooms || []).map((room) => {
    const placed = place(
      bars.filter((bar) => bar.room === room.name),
      window,
    )

    const segments = placed.map((item) => ({
      key: item.bar.key,
      label: item.bar.label,
      title: item.bar.reason || item.bar.label,
      // A block is not a reservation to open; it is a reason to show.
      reservation: item.bar.kind === 'block' ? null : item.bar.reservation || null,
      classes: barClasses(item.bar.kind),
      style: {
        gridColumn: `${item.start + 1} / ${item.end + 2}`,
        gridRow: String(item.lane + 1),
      },
    }))

    return { room, segments, lanes: placed.reduce((max, item) => Math.max(max, item.lane + 1), 1) }
  })
})

/**
 * Where a bar sits in the visible columns.
 *
 * A bar is a date range that may overhang the window at either end, so both
 * ends are clamped to what is on screen. The range covers whole nights: a guest
 * departing on the 9th does not occupy the night of the 9th, so the last
 * occupied column is the one before `to_date`. A range that collapses that way
 * still gets one column, otherwise same-day rows would be invisible.
 */
function span(bar, window) {
  const last = window.length - 1

  const first = bar.from_date > window[0] ? window.indexOf(bar.from_date) : 0
  const start = first < 0 ? 0 : first

  const end = bar.to_date > window[last] ? last : window.indexOf(bar.to_date) - 1

  return { start, end: Math.max(end, start) }
}

/**
 * Place a room's bars into lanes.
 *
 * A room is not double sold, but a maintenance block can be laid over a stay,
 * and one bar hidden behind another would misread as a free room. Overlapping
 * bars therefore stack into extra grid rows instead of sharing one.
 */
function place(bars, window) {
  const laneEnds = []

  return [...bars]
    .sort((a, b) => (a.from_date === b.from_date ? 0 : a.from_date < b.from_date ? -1 : 1))
    .map((bar) => {
      const { start, end } = span(bar, window)

      let lane = laneEnds.findIndex((occupied) => occupied < start)
      if (lane < 0) lane = laneEnds.length
      laneEnds[lane] = end

      return { bar, lane, start, end }
    })
}

function rowStyle(row) {
  return {
    gridTemplateColumns: columnTemplate.value,
    gridTemplateRows: `repeat(${row.lanes}, minmax(1.75rem, auto))`,
  }
}

function barClasses(kind) {
  return BAR_CLASSES[CALENDAR_BAR_THEME[kind]] || 'border-outline-gray-2 bg-surface-gray-2 text-ink-gray-7'
}

function dayLabel(date) {
  return formatDate(date, { day: '2-digit', month: 'short', year: undefined })
}

function weekdayLabel(date) {
  return formatDate(date, { weekday: 'short', day: undefined, month: undefined, year: undefined })
}

/** Parse an ISO date as local midnight; `new Date('2026-08-08')` is UTC. */
function parseDate(value) {
  return new Date(`${value}T00:00:00`)
}

function shiftDays(value, amount) {
  const date = parseDate(value)
  date.setDate(date.getDate() + amount)

  return toServerDate(date)
}

function nightsBetween(from, to) {
  return Math.max(1, Math.round((parseDate(to) - parseDate(from)) / 86400000))
}

function open(segment) {
  if (segment.reservation) openReservation(segment.reservation)
}

function openReservation(name) {
  if (name) router.push({ name: 'Reservation', params: { id: name } })
}

function goToday() {
  filters.from = toServerDate(property.businessDate.value)
}

function shiftWindow(direction) {
  fromDate.value = shiftDays(fromDate.value, direction * days.value)
}

/** Room paging replaces the page; this screen never grows an unbounded DOM. */
function turnPage(direction) {
  page.start = Math.max(0, page.start + direction * ROOMS_PER_PAGE)
  reload()
}

function reload() {
  grid.fetch({
    property: property.activeName.value,
    from_date: toServerDate(parseDate(fromDate.value)),
    to_date: toDate.value,
    room_type: filters.roomType || undefined,
    start: page.start,
    limit: ROOMS_PER_PAGE,
  })
}

// One watcher over every input to the view, so a change that moves two of them
// at once (switching property also moves the business date) is still one
// request. Any of them invalidates the current page of rooms.
watch(
  [() => property.activeName.value, fromDate, days, () => filters.roomType],
  () => {
    page.start = 0
    reload()
  },
  { immediate: true },
)
</script>
