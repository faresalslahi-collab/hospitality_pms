<!--
  Finish cleaning a room.

  Damage notes are required as soon as damage is ticked, mirroring the
  server's own rule, so the attendant sees the same requirement before
  submitting rather than after a refusal comes back.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.housekeeping.complete_title'), size: 'lg' }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-p-sm text-ink-gray-6">{{ roomLabel }}</p>

        <FormControl
          v-model="form.minutes"
          type="number"
          :label="t('page.housekeeping.minutes')"
          min="0"
        />

        <FormControl
          v-model="form.minibar_checked"
          type="checkbox"
          :label="t('page.housekeeping.minibar_checked')"
        />

        <div class="space-y-2 rounded border border-outline-gray-1 p-3">
          <FormControl
            v-model="form.damage_found"
            type="checkbox"
            :label="t('page.housekeeping.damage_found')"
          />
          <FormControl
            v-if="form.damage_found"
            v-model="form.damage_notes"
            type="textarea"
            :label="t('page.housekeeping.damage_notes')"
            rows="2"
          />
          <p v-if="form.damage_found && !form.damage_notes.trim()" class="text-p-sm text-ink-red-4">
            {{ t('page.housekeeping.damage_notes_required') }}
          </p>
        </div>

        <div class="space-y-2 rounded border border-outline-gray-1 p-3">
          <FormControl
            v-model="form.lost_and_found"
            type="checkbox"
            :label="t('page.housekeeping.lost_and_found')"
          />
          <FormControl
            v-if="form.lost_and_found"
            v-model="form.lost_and_found_notes"
            type="textarea"
            :label="t('page.housekeeping.lost_and_found_notes')"
            rows="2"
          />
        </div>

        <div class="space-y-2 rounded border border-outline-gray-1 p-3">
          <FormControl
            v-model="form.maintenance_required"
            type="checkbox"
            :label="t('page.housekeeping.maintenance_required')"
          />
          <FormControl
            v-if="form.maintenance_required"
            v-model="form.maintenance_description"
            type="textarea"
            :label="t('page.housekeeping.maintenance_description')"
            rows="2"
          />
        </div>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!canSubmit" @click="submit">
            {{ t('page.housekeeping.complete') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { completeHousekeepingTaskResource } from '@/resources/housekeeping'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  task: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const complete = completeHousekeepingTaskResource()

const saving = ref(false)
const errorMessage = ref('')

function emptyForm() {
  return {
    minutes: '',
    minibar_checked: false,
    damage_found: false,
    damage_notes: '',
    lost_and_found: false,
    lost_and_found_notes: '',
    maintenance_required: false,
    maintenance_description: '',
  }
}

const form = reactive(emptyForm())

const roomLabel = computed(() => {
  const task = props.task
  if (!task) return ''
  return `${task.room || ''} · ${task.task_type || ''}`
})

const canSubmit = computed(() => !(form.damage_found && !form.damage_notes.trim()))

watch(
  () => [props.modelValue, props.task?.name],
  ([isOpen]) => {
    if (!isOpen) return

    errorMessage.value = ''
    Object.assign(form, emptyForm())
  },
)

async function submit() {
  if (!props.task) return

  saving.value = true
  errorMessage.value = ''

  try {
    await complete.submit({
      task: props.task.name,
      minutes: form.minutes ? Number(form.minutes) : 0,
      minibar_checked: form.minibar_checked ? 1 : 0,
      damage_found: form.damage_found ? 1 : 0,
      damage_notes: form.damage_notes || undefined,
      lost_and_found: form.lost_and_found ? 1 : 0,
      lost_and_found_notes: form.lost_and_found_notes || undefined,
      maintenance_required: form.maintenance_required ? 1 : 0,
      maintenance_description: form.maintenance_description || undefined,
    })

    emit('changed')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
