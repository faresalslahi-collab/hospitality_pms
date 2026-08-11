<!--
  Rooms the desk has to do something about, ranked by what stops a guest first.

  The ranking is the whole point. Front desk order, worst first:

    1. a room needed today that cannot take its guest — assigned to an arrival
       on the business date and either not ready or not assignable. It is the
       only room state with a guest attached and a clock running;
    2. vacant and not ready — the rooms housekeeping has still to release. Keyed
       on vacant plus housekeeping, never on "dirty" alone: dirty counts occupied
       stayovers too, and a queue keyed on it lists most of the hotel every
       morning;
    3. out of order, out of service, under maintenance — lost inventory to be
       honest about rather than work for the desk, so it is a named list with no
       control on it. Those statuses belong to maintenance and to managers;
    4. blocked, not assignable, stop sell — a room the desk can see on the rack
       and may not sell. It has to know why.

  Each row shows one leading reason plus secondary chips, and the leading reason
  is picked in `api/rooms._blocking_reason`'s own order — maintenance, inventory,
  occupancy, housekeeping. A room can be vacant, dirty *and* out of service at
  once; merging those into one status sends an attendant to a room the desk still
  cannot sell. Every reason is a word, never a colour alone.

  Housekeeping's own screen keeps what belongs to it: DND, Service Refused,
  cleaning credits, and a Maintenance Required flag on a room that is still
  sellable. This panel decides nothing and mutates nothing.
-->
<template>
  <DashboardCard :title="t('page.dashboard.attention_panel')" :padded="false">
    <template #action>
      <RouterLink
        :to="{ name: 'RoomRack' }"
        class="flex items-center gap-1 text-p-sm font-medium text-ink-blue-3 hover:underline"
      >
        {{ t('page.dashboard.view_all') }}
        <FeatherIcon name="chevron-right" class="size-3.5 flip-rtl" aria-hidden="true" />
      </RouterLink>
    </template>

    <p v-if="loading" class="flex items-center gap-2 px-5 pb-5 pt-1 text-p-sm text-ink-gray-5">
      <LoadingIndicator class="size-4" />
      {{ t('common.loading') }}
    </p>

    <p v-else-if="!rows.length" class="px-5 pb-5 pt-1 text-p-sm text-ink-gray-5">
      {{ t('page.dashboard.attention_empty') }}
    </p>

    <div v-else>
      <div class="overflow-x-auto">
        <table class="w-full text-p-sm">
          <thead class="border-y border-outline-gray-1 bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
            <tr>
              <th class="px-5 py-2 text-start font-medium">{{ t('page.in_house.room') }}</th>
              <th class="px-3 py-2 text-start font-medium">{{ t('page.arrivals.guest') }}</th>
              <th class="w-full px-3 py-2 text-start font-medium">{{ t('page.dashboard.attention_reason') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.key"
              class="border-b border-outline-gray-1 last:border-b-0 hover:bg-surface-gray-1"
            >
              <td class="whitespace-nowrap px-5 py-2.5">
                <span data-attention-room class="font-medium tabular-nums text-ink-gray-8">
                  {{ row.room_number }}
                </span>
                <span v-if="row.room_type_name" class="block max-w-[6rem] truncate text-xs text-ink-gray-5">
                  {{ row.room_type_name }}
                </span>
              </td>
              <!--
                A guest only appears on the rows that have one. An empty cell on a
                maintenance row would read as missing data rather than as a room
                nobody is waiting for, so it says so.
              -->
              <td class="max-w-[8rem] px-3 py-2.5">
                <span v-if="row.guest_name" class="block truncate text-ink-gray-8" :title="row.guest_name">
                  {{ row.guest_name }}
                </span>
                <span v-else class="text-ink-gray-4" aria-hidden="true">—</span>
              </td>
              <!--
                One leading reason, then the rest as chips: the desk reads why the
                room is stopped first, and still sees the other two dimensions it
                will have to clear before the room can be sold.
              -->
              <td class="px-3 py-2.5">
                <span class="flex flex-wrap items-center gap-1.5">
                  <Badge
                    data-attention-reason
                    :theme="row.reason.theme"
                    variant="subtle"
                    :label="row.reason.label"
                  />
                  <Badge
                    v-for="chip in row.chips"
                    :key="chip"
                    data-attention-chip
                    theme="gray"
                    variant="subtle"
                    :label="chip"
                  />
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- A capped queue says what it is a slice of, so nobody works five rooms
           believing there were only five. -->
      <p v-if="total > rows.length" class="px-5 pb-4 pt-2.5 text-xs text-ink-gray-5">
        {{ t('page.dashboard.showing_first', { count: rows.length, total }) }}
      </p>
    </div>
  </DashboardCard>
</template>

<script setup>
import { Badge, FeatherIcon, LoadingIndicator } from 'frappe-ui'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import { BLOCKING_INVENTORY } from '@/components/dashboard/theme'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** Every room of the property, flattened from a room rack response. */
  rooms: { type: Array, default: () => [] },
  /** The `rows` block of an arrivals board response, for the business date. */
  arrivals: { type: Array, default: () => [] },
  /** Five to eight rows: past that it stops being a queue and becomes a report. */
  limit: { type: Number, default: 6 },
  loading: { type: Boolean, default: false },
})

/** Mirrors `services.rooms`: the states each dimension calls normal or blocking. */
const READY_HOUSEKEEPING = new Set(['Clean', 'Inspected'])
const BLOCKING_MAINTENANCE = new Set(['Under Maintenance', 'Out of Service', 'Out of Order'])
const OCCUPIED_STATES = new Set(['Occupied', 'House Use'])

/**
 * Housekeeping states that stop a *sale* rather than a housekeeper.
 *
 * DND and Service Refused are excluded on purpose: they are housekeeping's own
 * exceptions to chase on housekeeping's own screen, and a desk queue that listed
 * them would be asking the wrong department for the wrong thing.
 */
const UNREADY_HOUSEKEEPING = new Set(['Dirty', 'In Progress', 'Inspection Pending'])

/** Rank order, worst first. Named so the sort reads as the decision it is. */
const RANK = {
  arrival_blocked: 0,
  vacant_not_ready: 1,
  maintenance: 2,
  inventory: 3,
}

/**
 * Why this room cannot take a guest, in `api/rooms._blocking_reason`'s order.
 *
 * The status value itself is the reason text: it is the server's own word for
 * the state, already the label every other screen shows for it, so the queue and
 * the room detail dialog cannot end up calling the same state two things.
 */
function blockingReason(state) {
  if (BLOCKING_MAINTENANCE.has(state.maintenance_status)) {
    return { dimension: 'maintenance', status: state.maintenance_status }
  }

  if (BLOCKING_INVENTORY.has(state.inventory_status)) {
    return { dimension: 'inventory', status: state.inventory_status }
  }

  if (OCCUPIED_STATES.has(state.occupancy_status)) {
    return { dimension: 'occupancy', status: state.occupancy_status }
  }

  if (state.housekeeping_status && !READY_HOUSEKEEPING.has(state.housekeeping_status)) {
    return { dimension: 'housekeeping', status: state.housekeeping_status }
  }

  return null
}

/** Every blocking state on the room except the one already leading the row. */
function secondaryChips(state, leading) {
  const chips = []

  if (BLOCKING_MAINTENANCE.has(state.maintenance_status)) chips.push(state.maintenance_status)
  if (BLOCKING_INVENTORY.has(state.inventory_status)) chips.push(state.inventory_status)
  if (OCCUPIED_STATES.has(state.occupancy_status)) chips.push(state.occupancy_status)
  if (state.housekeeping_status && !READY_HOUSEKEEPING.has(state.housekeeping_status)) {
    chips.push(state.housekeeping_status)
  }

  return chips.filter((chip) => chip !== leading)
}

const REASON_THEME = {
  arrival_blocked: 'red',
  vacant_not_ready: 'orange',
  maintenance: 'red',
  inventory: 'gray',
}

/**
 * The queue, worst first.
 *
 * Arrivals are read before rooms, and a room already listed against its arrival
 * is not listed again: the same room twice would double the apparent size of the
 * queue and split one piece of work across two lines.
 */
const ranked = computed(() => {
  const rows = []
  const seenRooms = new Set()

  for (const arrival of props.arrivals) {
    // A guest already in the room has no readiness problem left to solve, and an
    // unassigned line is the work counter strip's business, not a room's.
    if (!arrival.assigned_room || arrival.is_checked_in) continue
    if (arrival.room_ready && arrival.room_assignable) continue

    const reason = blockingReason(arrival)

    seenRooms.add(arrival.assigned_room)

    rows.push({
      key: `arrival:${arrival.key ?? arrival.assigned_room}`,
      rank: RANK.arrival_blocked,
      room_number: arrival.room_number || arrival.assigned_room,
      room_type_name: arrival.room_type_name || arrival.room_type || '',
      guest_name: arrival.guest_name || '',
      reason: {
        theme: REASON_THEME.arrival_blocked,
        // No status on the row at all still has an honest answer: the server said
        // the room is not ready, which is what the desk is being told here.
        label: reason ? reason.status : t('page.arrivals.not_ready'),
      },
      chips: reason ? secondaryChips(arrival, reason.status) : [],
    })
  }

  for (const room of props.rooms) {
    if (room.is_active === false || seenRooms.has(room.name)) continue

    const reason = blockingReason(room)
    if (!reason) continue

    // An occupied room is the house working as intended: the desk sees it on the
    // rack and works the stayover from the in-house board.
    if (reason.dimension === 'occupancy') continue

    // Housekeeping only counts against a room nobody is in. A dirty stayover is
    // tomorrow's clean, not tonight's lost sale.
    if (reason.dimension === 'housekeeping') {
      if (room.occupancy_status !== 'Vacant') continue
      if (!UNREADY_HOUSEKEEPING.has(reason.status)) continue
    }

    const rank = reason.dimension === 'housekeeping' ? RANK.vacant_not_ready : RANK[reason.dimension]

    rows.push({
      key: `room:${room.name}`,
      rank,
      room_number: room.room_number || room.name,
      room_type_name: room.room_type_name || room.room_type || '',
      guest_name: '',
      reason: {
        theme: reason.dimension === 'housekeeping' ? REASON_THEME.vacant_not_ready : REASON_THEME[reason.dimension],
        label: reason.status,
      },
      chips: secondaryChips(room, reason.status),
    })
  }

  return rows.sort(
    (a, b) =>
      a.rank - b.rank ||
      String(a.room_number).localeCompare(String(b.room_number), undefined, { numeric: true }),
  )
})

const total = computed(() => ranked.value.length)

const rows = computed(() => ranked.value.slice(0, props.limit))
</script>
