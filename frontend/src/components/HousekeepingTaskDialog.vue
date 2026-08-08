<!--
  Housekeeping task detail and action.

  Every action the server might allow from the current status is offered;
  the server is the one that refuses it if the task has moved on since the
  board was last loaded (Frontend Standards section 6).
-->
<template>
  <Dialog v-model="open" :options="{ title: task?.room || '', size: 'lg' }">
    <template #body-content>
      <div v-if="current" class="space-y-4">
        <dl class="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.housekeeping.task_type') }}
            </dt>
            <dd class="mt-1 text-p-sm text-ink-gray-8">{{ current.task_type }}</dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.housekeeping.priority') }}
            </dt>
            <dd class="mt-1">
              <Badge :theme="priorityTheme(current.priority)" variant="subtle" :label="current.priority" />
            </dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.housekeeping.status') }}
            </dt>
            <dd class="mt-1">
              <Badge :theme="taskStatusTheme(current.task_status)" variant="subtle" :label="current.task_status" />
            </dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.housekeeping.assigned_to') }}
            </dt>
            <dd class="mt-1 text-p-sm text-ink-gray-8">
              {{ current.assigned_to || t('page.housekeeping.unassigned') }}
            </dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.housekeeping.scheduled_date') }}
            </dt>
            <dd class="mt-1 text-p-sm text-ink-gray-8">{{ formatDate(current.scheduled_date) }}</dd>
          </div>
          <div v-if="current.due_in_reservation">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.housekeeping.due_in') }}
            </dt>
            <dd class="mt-1 flex items-center gap-1 text-p-sm text-ink-blue-4">
              <FeatherIcon name="log-in" class="size-3.5" />
              {{ current.due_in_reservation }}
            </dd>
          </div>
        </dl>

        <p v-if="current.notes" class="text-p-sm text-ink-gray-6">{{ current.notes }}</p>

        <div v-if="current.task_status === 'Completed'" class="space-y-1 border-t border-outline-gray-1 pt-3 text-p-sm">
          <p v-if="current.damage_found" class="text-ink-red-4">
            {{ t('page.housekeeping.damage_found') }}: {{ current.damage_notes }}
          </p>
          <p v-if="current.lost_and_found" class="text-ink-gray-7">
            {{ t('page.housekeeping.lost_and_found') }}: {{ current.lost_and_found_notes }}
          </p>
          <p v-if="current.inspection_notes" class="text-ink-gray-7">
            {{ t('page.housekeeping.inspection_notes') }}: {{ current.inspection_notes }}
          </p>
        </div>

        <div class="space-y-3 border-t border-outline-gray-1 pt-4">
          <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.housekeeping.actions') }}</p>

          <div v-if="canAssign" class="flex flex-wrap items-end gap-2">
            <FormControl
              v-model="assignee"
              type="text"
              class="min-w-48 grow"
              :label="t('page.housekeeping.assignee')"
              :placeholder="t('page.housekeeping.assignee_hint')"
            />
            <Button variant="solid" :loading="busy === 'assign'" :disabled="!assignee.trim()" @click="doAssign">
              {{ t('page.housekeeping.assign') }}
            </Button>
          </div>

          <div class="flex flex-wrap gap-2">
            <Button v-if="canStart" variant="solid" :loading="busy === 'start'" @click="doStart">
              {{ t('page.housekeeping.start') }}
            </Button>
            <Button
              v-if="canComplete"
              variant="solid"
              theme="gray"
              @click="emit('complete', current)"
            >
              {{ t('page.housekeeping.complete') }}
            </Button>
            <Button
              v-if="canInspect"
              variant="solid"
              theme="gray"
              @click="emit('inspect', current)"
            >
              {{ t('page.housekeeping.inspect') }}
            </Button>
            <Button v-if="canFlag" variant="subtle" :loading="busy === 'dnd'" @click="doFlag(false)">
              {{ t('page.housekeeping.mark_dnd') }}
            </Button>
            <Button v-if="canFlag" variant="subtle" theme="red" :loading="busy === 'refused'" @click="doFlag(true)">
              {{ t('page.housekeeping.mark_refused') }}
            </Button>
          </div>

          <ErrorMessage :message="errorMessage" />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Badge, Button, Dialog, ErrorMessage, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import {
  assignHousekeepingTaskResource,
  housekeepingTaskResource,
  priorityTheme,
  setDoNotDisturbResource,
  startHousekeepingTaskResource,
  taskStatusTheme,
} from '@/resources/housekeeping'
import { normaliseError } from '@/utils/errors'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  task: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'changed', 'complete', 'inspect'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const detail = housekeepingTaskResource()
const assignRes = assignHousekeepingTaskResource()
const startRes = startHousekeepingTaskResource()
const dndRes = setDoNotDisturbResource()

const busy = ref('')
const errorMessage = ref('')
const assignee = ref('')

// The list already carries enough to render the row; the dialog fetches the
// full record so notes, findings and assignment history are current.
const current = computed(() => detail.data?.task || props.task)

const ASSIGNABLE_FROM = new Set(['Pending', 'DND', 'Service Refused'])
const STARTABLE_FROM = new Set(['Pending', 'Assigned', 'DND', 'Service Refused'])
const FLAGGABLE_FROM = new Set(['Pending', 'Assigned', 'In Progress'])

const canAssign = computed(() => ASSIGNABLE_FROM.has(current.value?.task_status))
const canStart = computed(() => STARTABLE_FROM.has(current.value?.task_status))
const canComplete = computed(() => current.value?.task_status === 'In Progress')
const canInspect = computed(() => current.value?.task_status === 'Inspection Pending')
const canFlag = computed(() => FLAGGABLE_FROM.has(current.value?.task_status))

watch(
  () => [props.modelValue, props.task?.name],
  ([isOpen, name]) => {
    if (!isOpen || !name) return

    errorMessage.value = ''
    assignee.value = ''
    detail.fetch({ task: name })
  },
)

async function reloadDetail() {
  if (props.task?.name) await detail.fetch({ task: props.task.name })
  emit('changed')
}

async function doAssign() {
  busy.value = 'assign'
  errorMessage.value = ''

  try {
    await assignRes.submit({ task: current.value.name, assignee: assignee.value.trim() })
    assignee.value = ''
    await reloadDetail()
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

async function doStart() {
  busy.value = 'start'
  errorMessage.value = ''

  try {
    await startRes.submit({ task: current.value.name })
    await reloadDetail()
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

async function doFlag(refused) {
  busy.value = refused ? 'refused' : 'dnd'
  errorMessage.value = ''

  try {
    await dndRes.submit({ task: current.value.name, refused: refused ? 1 : 0 })
    await reloadDetail()
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}
</script>
