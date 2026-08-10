<!--
  The house at a glance: every room, grouped by floor, coloured by the state
  that stops the desk first.

  This is the room rack's data, not a second copy of it — the same
  `rooms.get_room_rack` response, and the same detail dialog on click, so a
  status changed from here is changed by the service that owns the transition.

  Rooms with no floor recorded are not dropped; they gather under one group, so
  a property that has not filled the field still sees all of its inventory.
-->
<template>
  <DashboardCard :title="t('page.dashboard.board.title')" :padded="false" class="overflow-hidden">
    <template #action>
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span
          v-for="entry in legend"
          :key="entry.key"
          class="flex items-center gap-1.5 whitespace-nowrap text-xs text-ink-gray-6"
        >
          <span class="size-2.5 shrink-0 rounded-full" :style="{ backgroundColor: entry.dot }" aria-hidden="true" />
          {{ entry.label }}
        </span>
      </div>
    </template>

    <div class="px-5 pb-4">
      <p v-if="loading" class="flex items-center justify-center gap-2 py-6 text-p-sm text-ink-gray-5">
        <LoadingIndicator class="size-4" />
        {{ t('common.loading') }}
      </p>

      <p v-else-if="!floors.length" class="py-6 text-center text-p-sm text-ink-gray-5">
        {{ t('page.dashboard.board.empty') }}
      </p>

      <!--
        Chips sit on a grid of fixed 3.5rem tracks rather than in a flex row.
        Every floor's grid is the same width, so it resolves to the same number
        of tracks and room N on one floor sits directly above room N on the next
        — which a packed flex row cannot guarantee, because any chip that is
        wider than its neighbours pushes the whole rest of that floor out of step.

        The width has to be fixed for that to hold, so the glyph marking an
        unsellable room is taken out of the flow and pinned to the chip's corner.
        In the flow it added its own width plus a gap and was exactly what broke
        the alignment.
      -->
      <div v-else class="space-y-2.5">
        <div v-for="floor in floors" :key="floor.key" class="flex items-start gap-3">
          <span
            class="w-28 shrink-0 truncate pt-2 text-end text-p-sm font-medium text-ink-gray-6"
            :title="floor.label"
          >
            {{ floor.label }}
          </span>

          <div class="grid min-w-0 flex-1 grid-cols-[repeat(auto-fill,3.5rem)] gap-2">
            <button
              v-for="room in floor.rooms"
              :key="room.name"
              type="button"
              class="relative flex h-9 w-full items-center justify-center rounded-md text-p-sm font-semibold
                leading-none tabular-nums ring-1 ring-inset transition-shadow hover:shadow-card-hover
                focus-visible:z-10 focus-visible:outline-none
                focus-visible:shadow-[0_0_0_2px_#ffffff,0_0_0_4px_#171717]"
              :style="{
                backgroundColor: room.style.fill,
                color: room.style.text,
                '--tw-ring-color': room.style.ring,
              }"
              :title="room.title"
              :aria-label="room.title"
              @click="$emit('select', room.room)"
            >
              <!-- Pinned, not inline: the chip's width is what keeps the rack
                   aligned, and logical inset keeps the corner correct in RTL. -->
              <FeatherIcon
                v-if="room.style.glyph"
                name="slash"
                class="pointer-events-none absolute end-1 top-1 size-2.5 opacity-80"
                aria-hidden="true"
              />
              {{ room.room.room_number }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </DashboardCard>
</template>

<script setup>
import { FeatherIcon, LoadingIndicator } from 'frappe-ui'
import { computed } from 'vue'

import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import { ROOM_STATE_LEGEND, ROOM_STATE_STYLE, roomStateKey } from '@/components/dashboard/theme'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The `room_types` block of a room rack response. */
  roomTypes: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

defineEmits(['select'])

const legend = computed(() =>
  ROOM_STATE_LEGEND.map((entry) => ({
    key: entry.key,
    label: t(entry.labelKey),
    dot: ROOM_STATE_STYLE[entry.key].dot,
  })),
)

const stateLabel = computed(() =>
  Object.fromEntries(ROOM_STATE_LEGEND.map((entry) => [entry.key, t(entry.labelKey)])),
)

/**
 * Floors, in the order a lift would take them: top of the building first.
 *
 * A room stores its floor as a link, whose name is a code the property chose —
 * `MF03` is a perfectly good floor code and a useless label. The rack response
 * carries the floor's own name and its level alongside, so the group is titled
 * with what the floor is called and ordered by where it is in the building.
 * Where a property has not recorded a level, the label is sorted on instead,
 * which at least keeps the order stable.
 */
const floors = computed(() => {
  const groups = new Map()

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

      const stateKey = roomStateKey(room)

      groups.get(key).rooms.push({
        name: room.name,
        room,
        style: ROOM_STATE_STYLE[stateKey] || ROOM_STATE_STYLE.other,
        title: `${room.room_number} · ${stateLabel.value[stateKey] || ''}`,
      })
    }
  }

  return [...groups.values()]
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
})
</script>
