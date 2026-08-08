<!--
  Closing the business date is the highest-impact action on this screen: it
  rolls the property's operating day forward and, once done, needs a manager
  exception (Reopen) to undo. It always asks for explicit confirmation. The
  blocking-exception rule itself is never re-derived here — the parent screen
  only opens this dialog when the server's own `blocking_count` is zero.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.night_audit.close_title'), size: 'md' }">
    <template #body-content>
      <div v-if="audit" class="space-y-3">
        <p class="text-p-sm text-ink-gray-6">
          {{ t('page.night_audit.close_warning', {
            date: formatDate(audit.business_date),
            next_date: formatDate(audit.next_business_date),
          }) }}
        </p>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" theme="red" :loading="saving" @click="submit">
            {{ t('page.night_audit.close_confirm') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import { closeNightAuditResource } from '@/resources/nightAudit'
import { normaliseError } from '@/utils/errors'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  audit: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'closed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const closeResource = closeNightAuditResource()

const saving = ref(false)
const errorMessage = ref('')

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return
    errorMessage.value = ''
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await closeResource.submit({ audit: props.audit.name })
    emit('closed')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
