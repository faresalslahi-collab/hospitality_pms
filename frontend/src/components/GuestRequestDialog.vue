<!--
  Guest request detail and lifecycle actions.

  Only the actions that could plausibly apply to the current status are
  offered (mirrored from the request state machine, Workflow Matrix
  section 9). The server holds the real transition table; an action offered
  here that is no longer reachable comes back as a normal error, surfaced
  through `normaliseError` rather than hidden or guessed at again client-side.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.guest_services.request_title'), size: 'xl' }">
    <template #body-content>
      <LoadingState v-if="detail.loading && !detail.data" />
      <ErrorState v-else-if="detail.error" :error="detail.error" :on-retry="load" />

      <div v-else-if="request" class="space-y-4">
        <div class="flex flex-wrap items-center gap-2">
          <Badge :theme="requestStatusTheme(request.request_status)" variant="subtle" :label="request.request_status" />
          <Badge :theme="priorityTheme(request.priority)" variant="subtle" :label="request.priority" />
          <Badge v-if="request.request_type === 'Complaint'" theme="red" variant="subtle" :label="t('page.guest_services.complaint')" />
          <span
            v-if="sla.minutes !== null"
            class="text-p-sm font-medium"
            :class="sla.overdue ? 'text-ink-red-3' : 'text-ink-gray-6'"
          >
            {{ sla.overdue
              ? t('page.guest_services.overdue_by', { time: slaLabel })
              : t('page.guest_services.due_in', { time: slaLabel }) }}
          </span>
        </div>

        <div>
          <p class="text-base font-medium text-ink-gray-9">{{ request.subject }}</p>
          <p class="mt-1 text-p-sm text-ink-gray-6">{{ request.description }}</p>
        </div>

        <dl class="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.guest_services.category') }}</dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ request.category }}</dd>
          </div>
          <div v-if="request.room">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.guest_services.room') }}</dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ request.room }}</dd>
          </div>
          <div v-if="request.guest">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.guest_services.guest') }}</dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ request.guest }}</dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.guest_services.assignee') }}</dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ request.assigned_to || t('page.guest_services.unassigned') }}</dd>
          </div>
          <div v-if="request.department">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.guest_services.department') }}</dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ request.department }}</dd>
          </div>
        </dl>

        <div v-if="request.resolution" class="rounded bg-surface-gray-1 p-3">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.guest_services.resolution') }}</p>
          <p class="mt-1 text-p-sm text-ink-gray-7">{{ request.resolution }}</p>
        </div>

        <div v-if="request.escalation_reason" class="rounded bg-surface-red-1 p-3">
          <p class="text-p-sm text-ink-red-4">
            {{ t('page.guest_services.escalated_note', { level: request.escalation_level || 1 }) }}:
            {{ request.escalation_reason }}
          </p>
        </div>

        <div class="flex flex-wrap gap-2 border-t border-outline-gray-1 pt-4">
          <Button
            v-if="canOffer('start', request.request_status)"
            variant="subtle"
            :loading="busy === 'start'"
            @click="doStart"
          >
            {{ t('page.guest_services.start') }}
          </Button>
          <Button
            v-if="canOffer('assign', request.request_status)"
            variant="subtle"
            @click="toggle('assign')"
          >
            {{ t('page.guest_services.assign') }}
          </Button>
          <Button
            v-if="canOffer('complete', request.request_status)"
            variant="subtle"
            theme="green"
            @click="toggle('complete')"
          >
            {{ t('page.guest_services.complete') }}
          </Button>
          <Button
            v-if="canOffer('escalate', request.request_status)"
            variant="subtle"
            theme="orange"
            @click="toggle('escalate')"
          >
            {{ t('page.guest_services.escalate') }}
          </Button>
          <Button
            v-if="canOffer('reopen', request.request_status)"
            variant="subtle"
            @click="toggle('reopen')"
          >
            {{ t('page.guest_services.reopen') }}
          </Button>
          <Button
            v-if="canOffer('close', request.request_status)"
            variant="solid"
            :loading="busy === 'close'"
            @click="doClose"
          >
            {{ t('page.guest_services.close_request') }}
          </Button>
          <Button variant="subtle" theme="red" @click="recoveryOpen = true">
            {{ t('page.guest_services.service_recovery') }}
          </Button>
        </div>

        <div v-if="activeAction === 'assign'" class="space-y-3 rounded border border-outline-gray-1 p-3">
          <FormControl v-model="assignForm.assignee" type="text" :label="t('page.guest_services.assignee_hint')" />
          <FormControl v-model="assignForm.department" type="text" :label="t('page.guest_services.department_optional')" />
          <ErrorMessage :message="actionError" />
          <div class="flex justify-end gap-2">
            <Button variant="subtle" @click="activeAction = ''">{{ t('common.cancel') }}</Button>
            <Button
              variant="solid"
              :loading="busy === 'assign'"
              :disabled="!assignForm.assignee.trim()"
              @click="doAssign"
            >
              {{ t('common.confirm') }}
            </Button>
          </div>
        </div>

        <div v-if="activeAction === 'complete'" class="space-y-3 rounded border border-outline-gray-1 p-3">
          <FormControl
            v-model="completeForm.resolution"
            type="textarea"
            rows="3"
            :label="t('page.guest_services.resolution_label')"
            :placeholder="t('page.guest_services.resolution_hint')"
          />
          <FormControl v-model="completeForm.guest_satisfied" type="checkbox" :label="t('page.guest_services.guest_satisfied')" />
          <ErrorMessage :message="actionError" />
          <div class="flex justify-end gap-2">
            <Button variant="subtle" @click="activeAction = ''">{{ t('common.cancel') }}</Button>
            <Button
              variant="solid"
              theme="green"
              :loading="busy === 'complete'"
              :disabled="!completeForm.resolution.trim()"
              @click="doComplete"
            >
              {{ t('common.confirm') }}
            </Button>
          </div>
        </div>

        <div v-if="activeAction === 'escalate'" class="space-y-3 rounded border border-outline-gray-1 p-3">
          <FormControl v-model="escalateForm.escalate_to" type="text" :label="t('page.guest_services.escalate_to')" />
          <FormControl v-model="escalateForm.reason" type="textarea" rows="2" :label="t('page.guest_services.escalate_reason')" />
          <ErrorMessage :message="actionError" />
          <div class="flex justify-end gap-2">
            <Button variant="subtle" @click="activeAction = ''">{{ t('common.cancel') }}</Button>
            <Button variant="solid" theme="orange" :loading="busy === 'escalate'" @click="doEscalate">
              {{ t('common.confirm') }}
            </Button>
          </div>
        </div>

        <div v-if="activeAction === 'reopen'" class="space-y-3 rounded border border-outline-gray-1 p-3">
          <p class="text-p-sm text-ink-gray-6">{{ t('page.guest_services.reopen_warning') }}</p>
          <FormControl v-model="reopenForm.reason" type="textarea" rows="2" :label="t('page.guest_services.reopen_reason')" />
          <ErrorMessage :message="actionError" />
          <div class="flex justify-end gap-2">
            <Button variant="subtle" @click="activeAction = ''">{{ t('common.cancel') }}</Button>
            <Button
              variant="solid"
              :loading="busy === 'reopen'"
              :disabled="!reopenForm.reason.trim()"
              @click="doReopen"
            >
              {{ t('common.confirm') }}
            </Button>
          </div>
        </div>
      </div>
    </template>
  </Dialog>

  <ServiceRecoveryDialog v-model="recoveryOpen" :request="request" @applied="onChanged" />
</template>

<script setup>
import { Badge, Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import ServiceRecoveryDialog from '@/components/ServiceRecoveryDialog.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import {
  assignGuestRequestResource,
  canOffer,
  closeGuestRequestResource,
  completeGuestRequestResource,
  escalateGuestRequestResource,
  guestRequestResource,
  priorityTheme,
  reopenGuestRequestResource,
  requestStatusTheme,
  slaStatus,
  startGuestRequestResource,
} from '@/resources/guestServices'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  requestName: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const detail = guestRequestResource()
const startResource = startGuestRequestResource()
const assignResource = assignGuestRequestResource()
const completeResource = completeGuestRequestResource()
const escalateResource = escalateGuestRequestResource()
const reopenResource = reopenGuestRequestResource()
const closeResource = closeGuestRequestResource()

const busy = ref('')
const actionError = ref('')
const activeAction = ref('')
const recoveryOpen = ref(false)

const assignForm = reactive({ assignee: '', department: '' })
const completeForm = reactive({ resolution: '', guest_satisfied: false })
const escalateForm = reactive({ escalate_to: '', reason: '' })
const reopenForm = reactive({ reason: '' })

const request = computed(() => detail.data?.request || null)

const sla = computed(() => slaStatus(request.value?.due_by))
const slaLabel = computed(() => formatMinutes(sla.value.minutes))

function formatMinutes(minutes) {
  if (minutes === null) return ''

  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60

  return hours > 0
    ? t('page.guest_services.hours_minutes', { hours, minutes: rest })
    : t('page.guest_services.minutes_only', { minutes: rest })
}

function toggle(action) {
  actionError.value = ''
  activeAction.value = activeAction.value === action ? '' : action
}

function load() {
  if (!props.requestName) return
  return detail.fetch({ request: props.requestName })
}

async function run(key, fn) {
  busy.value = key
  actionError.value = ''

  try {
    await fn()
    await load()
    activeAction.value = ''
    emit('changed')
  } catch (error) {
    actionError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

function doStart() {
  return run('start', () => startResource.submit({ request: props.requestName }))
}

function doAssign() {
  return run('assign', () =>
    assignResource.submit({
      request: props.requestName,
      assignee: assignForm.assignee.trim(),
      department: assignForm.department || undefined,
    }),
  )
}

function doComplete() {
  return run('complete', () =>
    completeResource.submit({
      request: props.requestName,
      resolution: completeForm.resolution.trim(),
      guest_satisfied: completeForm.guest_satisfied ? 1 : 0,
    }),
  )
}

function doEscalate() {
  return run('escalate', () =>
    escalateResource.submit({
      request: props.requestName,
      escalate_to: escalateForm.escalate_to || undefined,
      reason: escalateForm.reason || undefined,
    }),
  )
}

function doReopen() {
  return run('reopen', () =>
    reopenResource.submit({ request: props.requestName, reason: reopenForm.reason.trim() }),
  )
}

function doClose() {
  return run('close', () => closeResource.submit({ request: props.requestName }))
}

function onChanged() {
  load()
  emit('changed')
}

watch(
  () => [props.modelValue, props.requestName],
  ([isOpen, name]) => {
    if (!isOpen || !name) return

    actionError.value = ''
    activeAction.value = ''
    assignForm.assignee = ''
    assignForm.department = ''
    completeForm.resolution = ''
    completeForm.guest_satisfied = false
    escalateForm.escalate_to = ''
    escalateForm.reason = ''
    reopenForm.reason = ''

    load()
  },
)
</script>
