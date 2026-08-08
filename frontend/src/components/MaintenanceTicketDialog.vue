<!--
  Maintenance ticket detail and action.

  Every action the server might allow from the current status is offered;
  the server is the one that refuses it if the ticket has moved on since the
  board was last loaded (Frontend Standards section 6).
-->
<template>
  <Dialog v-model="open" :options="{ title: current?.title || '', size: 'lg' }">
    <template #body-content>
      <div v-if="current" class="space-y-4">
        <div v-if="current.is_repeat_defect" class="flex items-center gap-1.5 text-p-sm text-ink-orange-4">
          <FeatherIcon name="repeat" class="size-3.5" />
          {{ t('page.maintenance.repeat_marker') }}
          <span v-if="current.previous_ticket">({{ current.previous_ticket }})</span>
        </div>

        <div v-if="current.takes_room_out_of_service" class="flex items-center gap-1.5 text-p-sm text-ink-red-4">
          <FeatherIcon name="slash" class="size-3.5" />
          {{ t('page.maintenance.oos_marker') }}: {{ current.out_of_service_status }}
        </div>

        <dl class="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.maintenance.category') }}</dt>
            <dd class="mt-1 text-p-sm text-ink-gray-8">{{ current.category }}</dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.maintenance.priority') }}</dt>
            <dd class="mt-1">
              <Badge :theme="priorityTheme(current.priority)" variant="subtle" :label="current.priority" />
            </dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.maintenance.status') }}</dt>
            <dd class="mt-1">
              <Badge :theme="ticketStatusTheme(current.ticket_status)" variant="subtle" :label="current.ticket_status" />
            </dd>
          </div>
          <div v-if="current.room">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.maintenance.room') }}</dt>
            <dd class="mt-1 text-p-sm text-ink-gray-8">{{ current.room }}</dd>
          </div>
          <div v-if="current.zone">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.maintenance.zone') }}</dt>
            <dd class="mt-1 text-p-sm text-ink-gray-8">{{ current.zone }}</dd>
          </div>
          <div v-if="current.area">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.maintenance.area') }}</dt>
            <dd class="mt-1 text-p-sm text-ink-gray-8">{{ current.area }}</dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.maintenance.assigned_to') }}</dt>
            <dd class="mt-1 text-p-sm text-ink-gray-8">
              {{ current.assigned_to || t('page.maintenance.unassigned') }}
            </dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.maintenance.reported_by') }}</dt>
            <dd class="mt-1 text-p-sm text-ink-gray-8">{{ current.reported_by }}</dd>
          </div>
        </dl>

        <p class="text-p-sm text-ink-gray-6">{{ current.description }}</p>

        <div v-if="workLogs.length" class="border-t border-outline-gray-1 pt-3">
          <p class="mb-2 text-p-sm font-medium text-ink-gray-8">{{ t('page.maintenance.work_log') }}</p>
          <ul class="max-h-40 space-y-1 overflow-y-auto text-p-sm text-ink-gray-7">
            <li v-for="(row, index) in workLogs" :key="index">
              <span class="text-ink-gray-9">{{ formatDateTime(row.logged_on) }}</span>
              — {{ row.work_done }}
              <span v-if="row.minutes_spent">({{ row.minutes_spent }}m)</span>
            </li>
          </ul>
        </div>

        <div class="space-y-3 border-t border-outline-gray-1 pt-4">
          <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.maintenance.actions') }}</p>

          <div v-if="canAssign" class="flex flex-wrap items-end gap-2">
            <FormControl
              v-model="technician"
              type="text"
              class="min-w-48 grow"
              :label="t('page.maintenance.technician')"
              :placeholder="t('page.maintenance.technician_hint')"
            />
            <Button variant="solid" :loading="busy === 'assign'" :disabled="!technician.trim()" @click="doAssign">
              {{ t('page.maintenance.assign') }}
            </Button>
          </div>

          <div v-if="canLogWork" class="space-y-2 rounded border border-outline-gray-1 p-3">
            <FormControl v-model="workDone" type="textarea" :label="t('page.maintenance.work_done')" rows="2" />
            <div class="grid gap-2 sm:grid-cols-2">
              <FormControl v-model="workMinutes" type="number" :label="t('page.maintenance.minutes')" min="0" />
              <FormControl v-model="workParts" type="text" :label="t('page.maintenance.parts')" />
            </div>
            <div class="flex justify-end">
              <Button variant="subtle" :loading="busy === 'log'" :disabled="!workDone.trim()" @click="doLogWork">
                {{ t('page.maintenance.log_work_title') }}
              </Button>
            </div>
          </div>

          <div class="flex flex-wrap gap-2">
            <Button v-if="canStart" variant="solid" :loading="busy === 'start'" @click="doStart">
              {{ t('page.maintenance.start_work') }}
            </Button>
            <Button v-if="canTakeOutOfService" variant="subtle" theme="red" @click="emit('take-out-of-service', current)">
              {{ t('page.maintenance.take_out_of_service') }}
            </Button>
            <Button v-if="canCompleteWork" variant="solid" theme="gray" :loading="busy === 'complete'" @click="doCompleteWork">
              {{ t('page.maintenance.complete_work') }}
            </Button>
            <Button v-if="canVerify" variant="solid" theme="gray" @click="emit('verify', current)">
              {{ t('page.maintenance.verify_release') }}
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
  assignMaintenanceTicketResource,
  completeMaintenanceWorkResource,
  logMaintenanceWorkResource,
  maintenanceTicketResource,
  priorityTheme,
  startMaintenanceWorkResource,
  ticketStatusTheme,
} from '@/resources/maintenance'
import { normaliseError } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  ticket: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'changed', 'take-out-of-service', 'verify'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const detail = maintenanceTicketResource()
const assignRes = assignMaintenanceTicketResource()
const startRes = startMaintenanceWorkResource()
const logWorkRes = logMaintenanceWorkResource()
const completeWorkRes = completeMaintenanceWorkResource()

const busy = ref('')
const errorMessage = ref('')
const technician = ref('')
const workDone = ref('')
const workMinutes = ref('')
const workParts = ref('')

const current = computed(() => detail.data?.ticket || props.ticket)
const workLogs = computed(() => detail.data?.work_logs || [])

const canAssign = computed(() => ['Open', 'In Progress'].includes(current.value?.ticket_status))
const canStart = computed(() => current.value?.ticket_status === 'Open')
const canLogWork = computed(() => current.value?.ticket_status === 'In Progress')
const canCompleteWork = computed(() => current.value?.ticket_status === 'In Progress')
const canVerify = computed(() => current.value?.ticket_status === 'Verification')
const canTakeOutOfService = computed(
  () =>
    Boolean(current.value?.room) &&
    !current.value?.takes_room_out_of_service &&
    !['Completed', 'Cancelled'].includes(current.value?.ticket_status),
)

watch(
  () => [props.modelValue, props.ticket?.name],
  ([isOpen, name]) => {
    if (!isOpen || !name) return

    errorMessage.value = ''
    technician.value = ''
    workDone.value = ''
    workMinutes.value = ''
    workParts.value = ''
    detail.fetch({ ticket: name })
  },
)

async function reloadDetail() {
  if (props.ticket?.name) await detail.fetch({ ticket: props.ticket.name })
  emit('changed')
}

async function doAssign() {
  busy.value = 'assign'
  errorMessage.value = ''

  try {
    await assignRes.submit({ ticket: current.value.name, technician: technician.value.trim() })
    technician.value = ''
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
    await startRes.submit({ ticket: current.value.name })
    await reloadDetail()
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

async function doLogWork() {
  busy.value = 'log'
  errorMessage.value = ''

  try {
    await logWorkRes.submit({
      ticket: current.value.name,
      work_done: workDone.value.trim(),
      minutes: workMinutes.value ? Number(workMinutes.value) : undefined,
      parts: workParts.value || undefined,
    })
    workDone.value = ''
    workMinutes.value = ''
    workParts.value = ''
    await reloadDetail()
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

async function doCompleteWork() {
  busy.value = 'complete'
  errorMessage.value = ''

  try {
    await completeWorkRes.submit({ ticket: current.value.name })
    await reloadDetail()
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}
</script>
