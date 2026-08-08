<!--
  Supervisor sign-off on a cleaned room.

  A fail is not a quiet variant of pass: it visibly sends the room back to
  Dirty and reopens the task, which is the whole point of having the step.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.housekeeping.inspect_title'), size: 'md' }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-p-sm text-ink-gray-6">{{ roomLabel }}</p>

        <div class="grid grid-cols-2 gap-2">
          <button
            type="button"
            class="rounded border p-3 text-center font-medium transition-colors"
            :class="
              form.passed
                ? 'border-outline-green-2 bg-surface-green-1 text-ink-green-4'
                : 'border-outline-gray-2 text-ink-gray-6'
            "
            @click="form.passed = true"
          >
            {{ t('page.housekeeping.inspection_passed') }}
          </button>
          <button
            type="button"
            class="rounded border p-3 text-center font-medium transition-colors"
            :class="
              !form.passed
                ? 'border-outline-red-2 bg-surface-red-1 text-ink-red-4'
                : 'border-outline-gray-2 text-ink-gray-6'
            "
            @click="form.passed = false"
          >
            {{ t('page.housekeeping.inspection_failed') }}
          </button>
        </div>

        <div v-if="!form.passed" class="rounded bg-surface-red-1 px-3 py-2">
          <p class="text-p-sm text-ink-red-4">{{ t('page.housekeeping.inspect_warning') }}</p>
        </div>

        <FormControl
          v-model="form.notes"
          type="textarea"
          :label="t('page.housekeeping.inspection_notes')"
          rows="3"
        />
        <p v-if="!form.passed && !form.notes.trim()" class="text-p-sm text-ink-red-4">
          {{ t('page.housekeeping.inspection_notes_required') }}
        </p>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button
            variant="solid"
            :theme="form.passed ? 'gray' : 'red'"
            :loading="saving"
            :disabled="!canSubmit"
            @click="submit"
          >
            {{ t('common.confirm') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { inspectHousekeepingTaskResource } from '@/resources/housekeeping'
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

const inspect = inspectHousekeepingTaskResource()

const saving = ref(false)
const errorMessage = ref('')
const form = reactive({ passed: true, notes: '' })

const roomLabel = computed(() => {
  const task = props.task
  if (!task) return ''
  return `${task.room || ''} · ${task.task_type || ''}`
})

const canSubmit = computed(() => form.passed || form.notes.trim().length > 0)

watch(
  () => [props.modelValue, props.task?.name],
  ([isOpen]) => {
    if (!isOpen) return

    errorMessage.value = ''
    form.passed = true
    form.notes = ''
  },
)

async function submit() {
  if (!props.task) return

  saving.value = true
  errorMessage.value = ''

  try {
    await inspect.submit({
      task: props.task.name,
      passed: form.passed ? 1 : 0,
      notes: form.notes || undefined,
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
