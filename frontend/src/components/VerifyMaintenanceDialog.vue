<!--
  Verify completed work and, if it passed, release the room back to sale.

  A fail is not a quiet variant of pass: the room stays out of sale and the
  ticket returns to In Progress, which is the whole point of verification
  (services/maintenance.py `verify_and_release`).
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.maintenance.verify_title'), size: 'md' }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-p-sm text-ink-gray-6">{{ ticket?.title }}</p>

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
            {{ t('page.maintenance.verify_passed') }}
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
            {{ t('page.maintenance.verify_failed') }}
          </button>
        </div>

        <div v-if="!form.passed" class="rounded bg-surface-red-1 px-3 py-2">
          <p class="text-p-sm text-ink-red-4">{{ t('page.maintenance.verify_fail_warning') }}</p>
        </div>

        <FormControl v-model="form.notes" type="textarea" :label="t('page.maintenance.verify_notes')" rows="3" />
        <p v-if="!form.passed && !form.notes.trim()" class="text-p-sm text-ink-red-4">
          {{ t('page.maintenance.verify_notes_required') }}
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

import { verifyAndReleaseResource } from '@/resources/maintenance'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  ticket: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const verify = verifyAndReleaseResource()

const saving = ref(false)
const errorMessage = ref('')
const form = reactive({ passed: true, notes: '' })

const canSubmit = computed(() => form.passed || form.notes.trim().length > 0)

watch(
  () => [props.modelValue, props.ticket?.name],
  ([isOpen]) => {
    if (!isOpen) return

    errorMessage.value = ''
    form.passed = true
    form.notes = ''
  },
)

async function submit() {
  if (!props.ticket) return

  saving.value = true
  errorMessage.value = ''

  try {
    await verify.submit({
      ticket: props.ticket.name,
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
