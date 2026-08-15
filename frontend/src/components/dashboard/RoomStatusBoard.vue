<!--
  The house at a glance: every room, one row per floor, coloured by the state
  that stops the desk first, with the same states counted along the top.

  This is the room rack's data, not a second copy of it — the same
  `rooms.get_room_rack` response the rest of the screen already loaded, and the
  same detail dialog on click, so a status changed from here is changed by the
  service that owns the transition. Nothing on this board asks the server a
  question of its own.

  The counters and the grid are read off *one* pass over *one* list, so they
  cannot disagree: every tile drawn below is counted exactly once above. That is
  the whole reason `board` is a single computed rather than two.

  Rooms with no floor recorded are not dropped; they gather under one group, so
  a property that has not filled the field still sees all of its inventory.
-->
<template>
  <DashboardCard :title="t('page.dashboard.board.title')" :padded="false" class="overflow-hidden">
    <!--
      The summary, where the legend used to be. It is a better legend than the
      legend was: each entry still carries its state's colour, and now also says
      how many rooms are in it.

      In the `header` slot rather than `action`, so the counts sit against the
      title and are read as part of it — the state of the house, then the rooms
      it is made of — instead of drifting to the far edge of a wide screen.
    -->
    <template #header>
      <div class="flex flex-wrap items-center gap-1.5">
        <span
          v-for="entry in summary"
          :key="entry.key"
          class="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-outline-gray-1
            bg-surface-white px-2 py-1 text-xs text-ink-gray-6 shadow-card"
        >
          <FeatherIcon
            :name="entry.icon"
            class="size-3.5 shrink-0"
            :style="{ color: entry.dot }"
            aria-hidden="true"
          />
          {{ entry.label }}
          <span class="font-semibold tabular-nums text-ink-gray-8">{{ entry.count }}</span>
        </span>
      </div>
    </template>

    <div class="px-5 pb-4">
      <p v-if="loading" class="flex items-center justify-center gap-2 py-6 text-p-sm text-ink-gray-5">
        <LoadingIndicator class="size-4" />
        {{ t('common.loading') }}
      </p>

      <p v-else-if="!board.floors.length" class="py-6 text-center text-p-sm text-ink-gray-5">
        {{ t('page.dashboard.board.empty') }}
      </p>

      <!--
        The grid scrolls inside its own frame, never the page.
        A property with thirty rooms on a floor is a scroll bar here and an
        unchanged dashboard everywhere else; the floor column stays pinned
        through it, because a room number with no floor beside it is unreadable.

        Columns are room *positions* on the floor, not room numbers — position 3
        on the fifth floor sits directly above position 3 on the fourth, which is
        the alignment that makes the board scannable down as well as across. The
        count is the busiest floor's, so no floor is ever truncated.
      -->
      <div v-else class="overflow-x-auto rounded-lg border border-outline-gray-1">
        <!-- `border-separate`, not `collapse`: a collapsed border belongs to the
             table rather than to the cell, and does not travel with a sticky
             cell as the grid scrolls under it. The row rules are therefore drawn
             on the cells themselves. -->
        <table class="w-full min-w-max border-separate border-spacing-0">
          <thead>
            <!--
              One heading, not one per position. A column number told the reader
              nothing a room number does not — the tile below it already says
              which room it is — and the band reads as a title for the grid.
            -->
            <tr class="bg-navy-800 text-white">
              <th
                scope="col"
                class="sticky start-0 z-20 w-44 bg-navy-800 px-3 py-2 text-start text-xs font-semibold uppercase tracking-wide"
              >
                {{ t('page.dashboard.board.floor') }}
              </th>
              <th :colspan="board.columns + 1" class="bg-navy-800 py-2" />
            </tr>
          </thead>

          <tbody>
            <tr v-for="floor in board.floors" :key="floor.key">
              <th
                scope="row"
                class="sticky start-0 z-10 w-44 border-t border-outline-gray-1 bg-surface-white
                  px-3 py-1.5 text-start font-medium"
              >
                <span class="flex items-center gap-2 text-p-sm text-ink-gray-7" :title="floor.label">
                  <FeatherIcon name="layers" class="size-3.5 shrink-0 text-ink-gray-4" aria-hidden="true" />
                  <span class="truncate">{{ floor.label }}</span>
                </span>
              </th>

              <!--
                The tile carries the width, not the cell. A table column in auto
                layout treats `width` as a suggestion and its content's minimum
                as law, so the slack cell below — which asks for 100% — squeezed
                every room column down to the width of the digits inside it. A
                fixed tile sets that minimum and the columns hold.
              -->
              <td
                v-for="position in board.columns"
                :key="position"
                data-room-cell
                class="border-t border-outline-gray-1 px-1 py-1.5 align-middle"
              >
                <button
                  v-if="floor.rooms[position - 1]"
                  type="button"
                  class="relative flex h-8 w-[4.5rem] items-center justify-center rounded-md text-p-sm font-semibold
                    leading-none tabular-nums ring-1 ring-inset transition
                    hover:shadow-card-hover hover:brightness-105
                    focus-visible:z-10 focus-visible:outline-none
                    focus-visible:shadow-[inset_0_0_0_2px_#ffffff,inset_0_0_0_4px_#171717]"
                  :style="{
                    backgroundColor: floor.rooms[position - 1].style.fill,
                    color: floor.rooms[position - 1].style.text,
                    '--tw-ring-color': floor.rooms[position - 1].style.ring,
                  }"
                  :title="floor.rooms[position - 1].title"
                  :aria-label="floor.rooms[position - 1].title"
                  @click="$emit('select', floor.rooms[position - 1].room)"
                >
                  <!--
                    Pinned rather than inline: the tile's width is what keeps the
                    columns aligned, and a logical inset keeps the corner correct
                    in RTL.

                    Every tile is one size, at rest and in every state. Hover
                    changes brightness and lifts a shadow, and the focus ring is
                    drawn *inside* the tile — an outset ring painted four pixels
                    of white and ink around the box, which read as the focused
                    room having grown while its neighbours had not.
                  -->
                  <FeatherIcon
                    v-if="floor.rooms[position - 1].style.glyph"
                    name="slash"
                    class="pointer-events-none absolute end-1 top-1 size-2.5 opacity-80"
                    aria-hidden="true"
                  />
                  {{ floor.rooms[position - 1].room.room_number }}
                </button>

                <!-- A floor shorter than the busiest one leaves its remaining
                     positions empty rather than borrowing another floor's. The
                     spacer holds the column's width so the floors above and
                     below it stay in step. -->
                <span v-else class="block h-8 w-[4.5rem]" aria-hidden="true" />
              </td>

              <!--
                The slack column. Room tracks are a fixed width, so on a screen
                wider than the grid the leftover has to go somewhere; given to
                this cell, the rooms stay packed against their floor label
                instead of being stretched across the card.
              -->
              <td class="w-full border-t border-outline-gray-1" />
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </DashboardCard>
</template>

<script setup>
import { FeatherIcon, LoadingIndicator } from 'frappe-ui'
import { computed } from 'vue'

import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import {
  ROOM_STATE_ICON,
  ROOM_STATE_LABEL_KEY,
  ROOM_STATE_LEGEND,
  ROOM_STATE_STYLE,
  roomStateKey,
} from '@/components/dashboard/theme'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The `room_types` block of a room rack response. */
  roomTypes: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

defineEmits(['select'])

// From the label map, not the legend: a blocked room draws like an out-of-service
// one but must not be called one, so there are more names than there are swatches.
const stateLabel = computed(() =>
  Object.fromEntries(
    Object.entries(ROOM_STATE_LABEL_KEY).map(([key, labelKey]) => [key, t(labelKey)]),
  ),
)

/**
 * The board: floors, the width of the widest one, and the state tally — all
 * from one pass over the rack.
 *
 * Floors run in the order a lift would take them, top of the building first. A
 * room stores its floor as a link whose name is a code the property chose —
 * `MF03` is a perfectly good floor code and a useless label — so the group is
 * titled with the floor's own name from the rack response and ordered by its
 * level. Where a property has recorded no level, the label is sorted on instead,
 * which at least keeps the order stable.
 *
 * Rooms are ordered within a floor by room number, compared numerically, so 10
 * follows 9 rather than 1. The rack has no per-room sequence field to prefer
 * over it.
 */
const board = computed(() => {
  const groups = new Map()
  const tally = new Map()

  for (const group of props.roomTypes) {
    for (const room of group.rooms || []) {
      const key = String(room.floor || '').trim() || '__none__'

      if (!groups.has(key)) {
        groups.set(key, {
          key,
          label: key === '__none__' ? t('page.dashboard.board.no_floor') : room.floor_name || key,
          level: room.floor_level ?? null,
          rooms: [],
        })
      }

      // The one place a room's displayed state is decided. `roomStateKey` follows
      // the server's own `_blocking_reason` order — maintenance, then inventory,
      // then occupancy, then housekeeping — so this board never invents a
      // precedence the rest of the system does not hold.
      const stateKey = roomStateKey(room)

      tally.set(stateKey, (tally.get(stateKey) || 0) + 1)

      groups.get(key).rooms.push({
        name: room.name,
        room,
        style: ROOM_STATE_STYLE[stateKey] || ROOM_STATE_STYLE.other,
        title: `${room.room_number} · ${stateLabel.value[stateKey] || ''}`,
      })
    }
  }

  const floors = [...groups.values()]
    .map((group) => ({
      ...group,
      rooms: group.rooms.sort((a, b) =>
        String(a.room.room_number).localeCompare(String(b.room.room_number), undefined, {
          numeric: true,
        }),
      ),
    }))
    .sort((a, b) => {
      // Unfloored rooms always last; they are a data gap, not a level.
      if (a.key === '__none__') return 1
      if (b.key === '__none__') return -1
      if (a.level !== null && b.level !== null) return b.level - a.level
      return a.label.localeCompare(b.label, undefined, { numeric: true })
    })

  return {
    floors,
    columns: floors.reduce((widest, floor) => Math.max(widest, floor.rooms.length), 0),
    tally,
  }
})

/**
 * One counter per state, over the rooms this board is drawing.
 *
 * The six legend states are always shown, at zero if that is the truth — a house
 * with nothing out of order should say so rather than leave the reader to notice
 * an absence.
 *
 * A blocked room gets a counter of its own, and only when there is one. It draws
 * exactly like an out-of-service room, deliberately (see `theme.js`), but it is
 * not out of service — it is stopped from sale — and folding it into that
 * counter would make the number wrong in the one direction that matters, by
 * reporting rooms as broken when they are merely held.
 */
const summary = computed(() => {
  const tally = board.value.tally
  const keys = ROOM_STATE_LEGEND.map((entry) => entry.key)

  if (tally.get('blocked')) keys.push('blocked')

  return keys.map((key) => ({
    key,
    label: stateLabel.value[key] || key,
    icon: ROOM_STATE_ICON[key] || 'circle',
    dot: (ROOM_STATE_STYLE[key] || ROOM_STATE_STYLE.other).dot,
    count: tally.get(key) || 0,
  }))
})
</script>
