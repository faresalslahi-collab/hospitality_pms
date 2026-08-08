<!--
  Housekeeping board.

  Room attendants use this on a tablet between rooms, so the board favours a
  few large tap targets over a dense table: one tap opens everything that can
  be done with a task, and the server decides what that tap is allowed to do.
-->
<template>
  <div>
    <PageHeader :title="t('page.housekeeping.title')" :subtitle="property.active.value?.property_name || ''">
      <template #actions>
        <Button variant="subtle" :loading="board.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <LoadingState v-if="board.loading && !board.data" />

    <ErrorState v-else-if="board.error" :error="board.error" :on-retry="reload" />

    <EmptyState v-else-if="!tasks.length" :message="t('page.housekeeping.empty')" />

    <div v-else class="space-y-5 p-5">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div
          v-for="tile in summaryTiles"
          :key="tile.key"
          class="rounded border border-outline-gray-1 px-3 py-2"
        >
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold" :class="tile.class">{{ tile.value }}</p>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <button
          v-for="task in sortedTasks"
          :key="task.name"
          class="rounded border border-outline-gray-1 p-4 text-start transition-colors hover:bg-surface-gray-2"
          @click="openDetail(task)"
        >
          <div class="flex items-start justify-between gap-2">
            <span class="flex items-center gap-1.5 text-p-base font-semibold text-ink-gray-9">
              {{ task.room }}
              <FeatherIcon
                v-if="task.due_in_reservation"
                name="log-in"
                class="size-4 text-ink-blue-4"
                :title="t('page.housekeeping.due_in_marker')"
              />
            </span>
            <Badge :theme="priorityTheme(task.priority)" variant="subtle" :label="task.priority" />
          </div>

          <p class="mt-1 text-p-sm text-ink-gray-7">{{ task.task_type }}</p>

          <div class="mt-3 flex items-center justify-between gap-2">
            <Badge :theme="taskStatusTheme(task.task_status)" variant="subtle" :label="task.task_status" />
            <span class="truncate text-p-sm text-ink-gray-6">
              {{ task.assigned_to || t('page.housekeeping.unassigned') }}
            </span>
          </div>
        </button>
      </div>
    </div>

    <HousekeepingTaskDialog
      v-model="detailOpen"
      :task="selectedTask"
      @changed="reload"
      @complete="openComplete"
      @inspect="openInspect"
    />
    <CompleteHousekeepingTaskDialog v-model="completeOpen" :task="actionTask" @changed="reload" />
    <InspectHousekeepingTaskDialog v-model="inspectOpen" :task="actionTask" @changed="reload" />
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import CompleteHousekeepingTaskDialog from '@/components/CompleteHousekeepingTaskDialog.vue'
import HousekeepingTaskDialog from '@/components/HousekeepingTaskDialog.vue'
import InspectHousekeepingTaskDialog from '@/components/InspectHousekeepingTaskDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { housekeepingBoardResource, priorityRank, priorityTheme, taskStatusTheme } from '@/resources/housekeeping'
import { property } from '@/stores/property'
import { t } from '@/utils/i18n'

const board = housekeepingBoardResource()

const detailOpen = ref(false)
const completeOpen = ref(false)
const inspectOpen = ref(false)
const selectedTask = ref(null)
const actionTask = ref(null)

const tasks = computed(() => board.data?.tasks || [])

const sortedTasks = computed(() =>
  [...tasks.value].sort(
    (a, b) => priorityRank(a.priority) - priorityRank(b.priority) || (a.room || '').localeCompare(b.room || ''),
  ),
)

const summaryTiles = computed(() => {
  const s = board.data?.summary || {}

  return [
    { key: 'total', label: t('page.housekeeping.total'), value: s.total ?? 0, class: 'text-ink-gray-9' },
    { key: 'pending', label: t('page.housekeeping.pending'), value: s.pending ?? 0, class: 'text-ink-gray-9' },
    {
      key: 'in_progress',
      label: t('page.housekeeping.in_progress'),
      value: s.in_progress ?? 0,
      class: 'text-ink-orange-4',
    },
    {
      key: 'awaiting_inspection',
      label: t('page.housekeeping.awaiting_inspection'),
      value: s.awaiting_inspection ?? 0,
      class: 'text-ink-orange-4',
    },
    {
      key: 'completed',
      label: t('page.housekeeping.completed'),
      value: s.completed ?? 0,
      class: 'text-ink-green-3',
    },
    { key: 'due_in', label: t('page.housekeeping.due_in'), value: s.due_in ?? 0, class: 'text-ink-blue-4' },
  ]
})

function reload() {
  board.fetch({ property: property.activeName.value })
}

function openDetail(task) {
  selectedTask.value = task
  detailOpen.value = true
}

function openComplete(task) {
  detailOpen.value = false
  actionTask.value = task
  completeOpen.value = true
}

function openInspect(task) {
  detailOpen.value = false
  actionTask.value = task
  inspectOpen.value = true
}

// The board is always scoped to the active property, so switching property
// reloads it rather than showing another property's tasks.
watch(() => property.activeName.value, reload, { immediate: true })
</script>
