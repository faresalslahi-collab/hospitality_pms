<!--
  Maintenance board.

  One tap opens everything that can be done with a ticket; the server
  decides what that tap is allowed to do (Frontend Standards section 6).
-->
<template>
  <div>
    <PageHeader :title="t('page.maintenance.title')" :subtitle="property.active.value?.property_name || ''">
      <template #actions>
        <Button variant="solid" @click="createOpen = true">
          <template #prefix><FeatherIcon name="plus" class="size-4" /></template>
          {{ t('page.maintenance.create_ticket') }}
        </Button>
        <Button variant="subtle" :loading="board.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <LoadingState v-if="board.loading && !board.data" />

    <ErrorState v-else-if="board.error" :error="board.error" :on-retry="reload" />

    <EmptyState v-else-if="!tickets.length" :message="t('page.maintenance.empty')" />

    <div v-else class="space-y-5 p-5">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <div
          v-for="tile in summaryTiles"
          :key="tile.key"
          class="rounded border border-outline-gray-1 px-3 py-2"
        >
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold" :class="tile.class">{{ tile.value }}</p>
        </div>
      </div>

      <div class="overflow-x-auto rounded border border-outline-gray-1">
        <table class="w-full min-w-max text-p-sm">
          <thead class="bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
            <tr>
              <th class="p-2 text-start">{{ t('page.maintenance.priority') }}</th>
              <th class="p-2 text-start">{{ t('page.maintenance.category') }}</th>
              <th class="p-2 text-start">{{ t('page.maintenance.ticket_title') }}</th>
              <th class="p-2 text-start">{{ t('page.maintenance.room') }}</th>
              <th class="p-2 text-start">{{ t('page.maintenance.status') }}</th>
              <th class="p-2 text-start">{{ t('page.maintenance.assigned_to') }}</th>
              <th class="p-2 text-start">{{ t('page.maintenance.flags') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="ticket in sortedTickets"
              :key="ticket.name"
              class="cursor-pointer border-t border-outline-gray-1 hover:bg-surface-gray-1"
              @click="openDetail(ticket)"
            >
              <td class="p-2">
                <Badge :theme="priorityTheme(ticket.priority)" variant="subtle" :label="ticket.priority" />
              </td>
              <td class="p-2">{{ ticket.category }}</td>
              <td class="p-2 font-medium text-ink-gray-9">{{ ticket.title }}</td>
              <td class="p-2">{{ ticket.room || ticket.area || '—' }}</td>
              <td class="p-2">
                <Badge :theme="ticketStatusTheme(ticket.ticket_status)" variant="subtle" :label="ticket.ticket_status" />
              </td>
              <td class="p-2">{{ ticket.assigned_to || t('page.maintenance.unassigned') }}</td>
              <td class="p-2">
                <span class="flex items-center gap-2">
                  <FeatherIcon
                    v-if="ticket.is_repeat_defect"
                    name="repeat"
                    class="size-3.5 text-ink-orange-4"
                    :title="t('page.maintenance.repeat_marker')"
                  />
                  <FeatherIcon
                    v-if="ticket.takes_room_out_of_service"
                    name="slash"
                    class="size-3.5 text-ink-red-3"
                    :title="t('page.maintenance.oos_marker')"
                  />
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <MaintenanceTicketDialog
      v-model="detailOpen"
      :ticket="selectedTicket"
      @changed="reload"
      @take-out-of-service="openTakeOutOfService"
      @verify="openVerify"
    />
    <TakeOutOfServiceDialog v-model="oosOpen" :ticket="actionTicket" @changed="reload" />
    <VerifyMaintenanceDialog v-model="verifyOpen" :ticket="actionTicket" @changed="reload" />
    <CreateMaintenanceTicketDialog v-model="createOpen" @changed="reload" />
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import CreateMaintenanceTicketDialog from '@/components/CreateMaintenanceTicketDialog.vue'
import MaintenanceTicketDialog from '@/components/MaintenanceTicketDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import TakeOutOfServiceDialog from '@/components/TakeOutOfServiceDialog.vue'
import VerifyMaintenanceDialog from '@/components/VerifyMaintenanceDialog.vue'
import { maintenanceBoardResource, priorityRank, priorityTheme, ticketStatusTheme } from '@/resources/maintenance'
import { property } from '@/stores/property'
import { t } from '@/utils/i18n'

const board = maintenanceBoardResource()

const detailOpen = ref(false)
const oosOpen = ref(false)
const verifyOpen = ref(false)
const createOpen = ref(false)
const selectedTicket = ref(null)
const actionTicket = ref(null)

const tickets = computed(() => board.data?.tickets || [])

const sortedTickets = computed(() =>
  [...tickets.value].sort(
    (a, b) =>
      priorityRank(a.priority) - priorityRank(b.priority) ||
      (a.room || a.area || '').localeCompare(b.room || b.area || ''),
  ),
)

const summaryTiles = computed(() => {
  const s = board.data?.summary || {}

  return [
    { key: 'open', label: t('page.maintenance.open'), value: s.open ?? 0, class: 'text-ink-gray-9' },
    {
      key: 'in_progress',
      label: t('page.maintenance.in_progress'),
      value: s.in_progress ?? 0,
      class: 'text-ink-orange-4',
    },
    {
      key: 'awaiting_verification',
      label: t('page.maintenance.awaiting_verification'),
      value: s.awaiting_verification ?? 0,
      class: 'text-ink-blue-4',
    },
    {
      key: 'rooms_out_of_service',
      label: t('page.maintenance.rooms_out_of_service'),
      value: s.rooms_out_of_service ?? 0,
      class: 'text-ink-red-3',
    },
    {
      key: 'repeat_defects',
      label: t('page.maintenance.repeat_defects'),
      value: s.repeat_defects ?? 0,
      class: 'text-ink-orange-4',
    },
  ]
})

function reload() {
  board.fetch({ property: property.activeName.value })
}

function openDetail(ticket) {
  selectedTicket.value = ticket
  detailOpen.value = true
}

function openTakeOutOfService(ticket) {
  detailOpen.value = false
  actionTicket.value = ticket
  oosOpen.value = true
}

function openVerify(ticket) {
  detailOpen.value = false
  actionTicket.value = ticket
  verifyOpen.value = true
}

// The board is always scoped to the active property, so switching property
// reloads it rather than showing another property's tickets.
watch(() => property.activeName.value, reload, { immediate: true })
</script>
