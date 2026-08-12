<!--
  Raise an ad-hoc cleaning task.

  Most housekeeping tasks are raised by the system — checkout queues a departure
  clean automatically. This is for the ones that are not: a spill in a corridor
  room, a guest asking for a turndown, a supervisor scheduling a deep clean.

  **The property is not on this form.** It comes from the active property
  context, the server authorises it, and the server then proves the room belongs
  to it. A property field here would invite the cross-property write that
  16.7.4 closed, and would be a permission decision taken in Vue.

  The server is idempotent per (property, room, task type, day): raising the same
  task twice returns the existing one rather than queueing the room twice, so a
  double-submit is harmless and no client-side guard pretends otherwise.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.housekeeping.create_title') }">
    <template #body-content>
      <div class="space-y-4">
        <FormControl
          v-model="form.room"
          type="text"
          :label="t('page.housekeeping.room')"
          :placeholder="t('page.housekeeping.room_hint')"
        />

        <FormControl
          v-model="form.task_type"
          type="select"
          :options="taskTypeOptions"
          :label="t('page.housekeeping.task_type')"
        />

        <FormControl
          v-model="form.priority"
          type="select"
          :options="priorityOptions"
          :label="t('page.housekeeping.priority')"
        />

        <FormControl
          v-model="form.notes"
          type="textarea"
          :rows="3"
          :label="t('page.housekeeping.notes')"
        />

        <ErrorMessage :message="errorMessage" />
      </div>
    </template>

    <template #actions>
      <div class="flex justify-end gap-2">
        <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
        <Button variant="solid" :loading="saving" :disabled="!canSubmit" @click="submit">
          {{ t('page.housekeeping.create_task') }}
        </Button>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, watch } from 'vue'

import {
  TASK_PRIORITIES,
  TASK_TYPES,
  createHousekeepingTaskResource,
} from '@/resources/housekeeping'
import { property } from '@/stores/property'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** Prefilled when raised from a room context, e.g. the room rack. */
  room: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'created'])

const create = createHousekeepingTaskResource()

const form = reactive({
  room: props.room,
  task_type: 'Departure Clean',
  priority: 'Normal',
  notes: '',
})

const saving = computed(() => create.loading)
const errorMessage = computed(() => (create.error ? normaliseError(create.error).message : ''))

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const taskTypeOptions = computed(() => TASK_TYPES.map((value) => ({ label: value, value })))
const priorityOptions = computed(() => TASK_PRIORITIES.map((value) => ({ label: value, value })))

const canSubmit = computed(() => Boolean(form.room.trim()))

// Reset on open so a room typed for one task is not submitted with another.
watch(open, (value) => {
  if (!value) return

  form.room = props.room
  form.task_type = 'Departure Clean'
  form.priority = 'Normal'
  form.notes = ''
  create.error = null
})

async function submit() {
  if (!canSubmit.value) return

  await create.submit({
    property: property.activeName.value,
    room: form.room.trim(),
    task_type: form.task_type,
    priority: form.priority,
    notes: form.notes.trim() || undefined,
  })

  open.value = false
  emit('created')
}
</script>
