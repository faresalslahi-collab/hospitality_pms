<template>
  <div>
    <PageHeader :title="t('page.guest_services.title')" :subtitle="property.active.value?.property_name || ''">
      <template #actions>
        <FormControl
          v-model="includeClosed"
          type="checkbox"
          :label="t('page.guest_services.include_closed')"
          @change="reload"
        />
        <Button variant="subtle" :loading="board.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
        <Button variant="solid" @click="createOpen = true">
          <template #prefix><FeatherIcon name="plus" class="size-4" /></template>
          {{ t('page.guest_services.create') }}
        </Button>
      </template>
    </PageHeader>

    <LoadingState v-if="board.loading && !board.data" />

    <ErrorState v-else-if="board.error" :error="board.error" :on-retry="reload" />

    <EmptyState v-else-if="!requests.length" :message="t('page.guest_services.empty')" />

    <div v-else class="space-y-5 p-5">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <div v-for="tile in summaryTiles" :key="tile.key" class="rounded border border-outline-gray-1 px-3 py-2">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold" :class="tile.class">{{ tile.value }}</p>
        </div>
      </div>

      <div class="overflow-x-auto rounded border border-outline-gray-1">
        <table class="w-full min-w-max text-p-sm">
          <thead class="bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
            <tr>
              <th class="p-2 text-start">{{ t('page.guest_services.subject') }}</th>
              <th class="p-2 text-start">{{ t('page.guest_services.category') }}</th>
              <th class="p-2 text-start">{{ t('page.guest_services.room') }}</th>
              <th class="p-2 text-start">{{ t('page.guest_services.assignee') }}</th>
              <th class="p-2 text-start">{{ t('page.guest_services.priority_label') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.status') }}</th>
              <th class="p-2 text-start">{{ t('page.guest_services.sla') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in requests"
              :key="row.name"
              class="cursor-pointer border-t border-outline-gray-1 hover:bg-surface-gray-1"
              @click="open(row)"
            >
              <td class="p-2">
                <p class="font-medium text-ink-gray-9">{{ row.subject }}</p>
                <p v-if="row.request_type === 'Complaint'" class="text-xs text-ink-red-3">
                  {{ t('page.guest_services.complaint') }}
                </p>
              </td>
              <td class="p-2">{{ row.category }}</td>
              <td class="p-2">{{ row.room || '—' }}</td>
              <td class="p-2">{{ row.assigned_to || t('page.guest_services.unassigned') }}</td>
              <td class="p-2">
                <Badge :theme="priorityTheme(row.priority)" variant="subtle" :label="row.priority" />
              </td>
              <td class="p-2">
                <Badge :theme="requestStatusTheme(row.request_status)" variant="subtle" :label="row.request_status" />
              </td>
              <td class="p-2 whitespace-nowrap">
                <span
                  v-if="slaLabel(row)"
                  class="inline-flex items-center gap-1 font-medium"
                  :class="slaStatus(row.due_by, now).overdue ? 'text-ink-red-3' : 'text-ink-gray-6'"
                >
                  <FeatherIcon
                    v-if="slaStatus(row.due_by, now).overdue"
                    name="alert-triangle"
                    class="size-3.5"
                  />
                  {{ slaLabel(row) }}
                </span>
                <span v-else class="text-ink-gray-4">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <GuestRequestFormDialog v-model="createOpen" @created="reload" />
    <GuestRequestDialog v-model="detailOpen" :request-name="selectedRequest" @changed="reload" />
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import GuestRequestDialog from '@/components/GuestRequestDialog.vue'
import GuestRequestFormDialog from '@/components/GuestRequestFormDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import {
  guestServicesBoardResource,
  priorityTheme,
  requestStatusTheme,
  slaStatus,
} from '@/resources/guestServices'
import { property } from '@/stores/property'
import { t } from '@/utils/i18n'

const board = guestServicesBoardResource()

const includeClosed = ref(false)
const createOpen = ref(false)
const detailOpen = ref(false)
const selectedRequest = ref('')
const now = ref(new Date())

let ticker = null

const requests = computed(() => board.data?.requests || [])

const summaryTiles = computed(() => {
  const s = board.data?.summary || {}

  return [
    { key: 'open', label: t('page.guest_services.tile_open'), value: s.open ?? 0, class: 'text-ink-gray-9' },
    {
      key: 'in_progress',
      label: t('page.guest_services.tile_in_progress'),
      value: s.in_progress ?? 0,
      class: 'text-ink-blue-3',
    },
    {
      key: 'escalated',
      label: t('page.guest_services.tile_escalated'),
      value: s.escalated ?? 0,
      class: 'text-ink-red-3',
    },
    {
      key: 'overdue',
      label: t('page.guest_services.tile_overdue'),
      value: s.overdue ?? 0,
      class: 'text-ink-red-3',
    },
    {
      key: 'complaints',
      label: t('page.guest_services.tile_complaints'),
      value: s.complaints ?? 0,
      class: 'text-ink-gray-9',
    },
  ]
})

function slaLabel(row) {
  const status = slaStatus(row.due_by, now.value)
  if (status.minutes === null) return ''

  const hours = Math.floor(status.minutes / 60)
  const rest = status.minutes % 60
  const duration = hours > 0
    ? t('page.guest_services.hours_minutes', { hours, minutes: rest })
    : t('page.guest_services.minutes_only', { minutes: rest })

  return status.overdue
    ? t('page.guest_services.overdue_by', { time: duration })
    : t('page.guest_services.due_in', { time: duration })
}

function reload() {
  board.fetch({
    property: property.activeName.value,
    include_closed: includeClosed.value ? 1 : 0,
  })
}

function open(row) {
  selectedRequest.value = row.name
  detailOpen.value = true
}

onMounted(() => {
  // A live countdown is the point of this screen; refresh the clock on its
  // own timer so "overdue by" keeps advancing without needing a data refetch.
  ticker = window.setInterval(() => {
    now.value = new Date()
  }, 30000)
})

onBeforeUnmount(() => {
  if (ticker) window.clearInterval(ticker)
})

watch(() => property.activeName.value, reload, { immediate: true })
</script>
