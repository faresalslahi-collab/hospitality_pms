<template>
  <div>
    <PageHeader :title="t('page.rack.title')" :subtitle="property.active.value?.property_name || ''">
      <template #actions>
        <Button variant="subtle" :loading="rack.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <LoadingState v-if="rack.loading && !rack.data" />

    <ErrorState v-else-if="rack.error" :error="rack.error" :on-retry="reload" />

    <EmptyState v-else-if="!roomTypes.length" :message="t('page.rack.empty')" />

    <div v-else class="space-y-5 p-5">
      <!-- Summary strip: what the shift needs to know before anything else. -->
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        <div
          v-for="tile in summaryTiles"
          :key="tile.key"
          class="rounded border border-outline-gray-1 px-3 py-2"
        >
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold" :class="tile.class">{{ tile.value }}</p>
        </div>
      </div>

      <section v-for="group in roomTypes" :key="group.name" class="space-y-2">
        <h2 class="text-base font-medium text-ink-gray-8">
          {{ group.room_type_name || group.name }}
          <span class="text-p-sm font-normal text-ink-gray-5">({{ group.rooms.length }})</span>
        </h2>

        <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-7">
          <button
            v-for="room in group.rooms"
            :key="room.name"
            class="rounded border p-2 text-start transition-colors hover:bg-surface-gray-2"
            :class="room.assignable ? 'border-outline-gray-2' : 'border-outline-red-1 bg-surface-red-1'"
            @click="open(room)"
          >
            <span class="flex items-center justify-between gap-1">
              <span class="truncate font-medium text-ink-gray-9">{{ room.room_number }}</span>
              <FeatherIcon
                v-if="!room.assignable"
                name="slash"
                class="size-3.5 shrink-0 text-ink-red-3"
              />
            </span>
            <span class="mt-1 block truncate text-xs text-ink-gray-6">
              {{ room.occupancy_status }} · {{ room.housekeeping_status }}
            </span>
            <span v-if="room.blocking_reason" class="mt-0.5 block truncate text-xs text-ink-red-3">
              {{ room.blocking_reason }}
            </span>
          </button>
        </div>
      </section>
    </div>

    <RoomDetailDialog v-model="detailOpen" :room="selectedRoom" @changed="reload" />
  </div>
</template>

<script setup>
import { Button, FeatherIcon } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import PageHeader from '@/components/PageHeader.vue'
import RoomDetailDialog from '@/components/RoomDetailDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { roomRackResource } from '@/resources/rooms'
import { property } from '@/stores/property'
import { t } from '@/utils/i18n'

const rack = roomRackResource()
const detailOpen = ref(false)
const selectedRoom = ref(null)

const roomTypes = computed(() =>
  (rack.data?.room_types || []).filter((group) => group.rooms?.length),
)

const summaryTiles = computed(() => {
  const s = rack.data?.summary || {}

  return [
    { key: 'total', label: t('page.rack.total'), value: s.total ?? 0, class: 'text-ink-gray-9' },
    { key: 'occupied', label: t('page.rack.occupied'), value: s.occupied ?? 0, class: 'text-ink-amber-3' },
    { key: 'vacant', label: t('page.rack.vacant'), value: s.vacant ?? 0, class: 'text-ink-gray-9' },
    { key: 'ready', label: t('page.rack.ready'), value: s.ready ?? 0, class: 'text-ink-green-3' },
    { key: 'dirty', label: t('page.rack.dirty'), value: s.dirty ?? 0, class: 'text-ink-red-3' },
    { key: 'ooo', label: t('page.rack.out_of_order'), value: s.out_of_order ?? 0, class: 'text-ink-red-3' },
    {
      key: 'assignable',
      label: t('page.rack.assignable'),
      value: s.assignable ?? 0,
      class: 'text-ink-green-3',
    },
  ]
})

function reload() {
  rack.fetch({ property: property.activeName.value })
}

function open(room) {
  selectedRoom.value = room
  detailOpen.value = true
}

// The rack is always scoped to the active property, so switching property
// reloads it rather than showing another property's rooms.
watch(() => property.activeName.value, reload, { immediate: true })
</script>
