<!--
  Reopening a closed business date is a manager exception (Workflow Matrix
  section 7): it puts back into play a day the hotel has already reported on.
  A reason is always required, on the server as well as here, and the dialog
  states plainly what reopening does before letting anyone confirm it.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.night_audit.reopen_title'), size: 'md' }">
    <template #body-content>
      <div v-if="audit" class="space-y-3">
        <p class="text-p-sm text-ink-red-4">{{ t('page.night_audit.reopen_warning') }}</p>

        <FormControl
          v-model="reason"
          type="textarea"
          rows="3"
          :label="t('page.night_audit.reopen_reason')"
        />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button
            variant="solid"
            theme="red"
            :loading="saving"
            :disabled="!reason.trim()"
            @click="submit"
          >
            {{ t('page.night_audit.reopen_confirm') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import { reopenNightAuditResource } from '@/resources/nightAudit'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  audit: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'reopened'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const reopenResource = reopenNightAuditResource()

const saving = ref(false)
const errorMessage = ref('')
const reason = ref('')

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return
    errorMessage.value = ''
    reason.value = ''
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await reopenResource.submit({ audit: props.audit.name, reason: reason.value.trim() })
    emit('reopened')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
