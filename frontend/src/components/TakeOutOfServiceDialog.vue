<!--
  Take a room out of service for maintenance.

  This removes sellable inventory the moment it is confirmed, so the warning
  is plain and a reason is mandatory — mirroring the server's own rule
  (services/maintenance.py `take_out_of_service`).
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.maintenance.oos_title'), size: 'md' }">
    <template #body-content>
      <div class="space-y-4">
        <div class="rounded bg-surface-red-1 px-3 py-2">
          <p class="text-p-sm font-medium text-ink-red-4">{{ t('page.maintenance.oos_warning') }}</p>
        </div>

        <p class="text-p-sm text-ink-gray-6">{{ ticket?.room }}</p>

        <FormControl
          v-model="form.status"
          type="select"
          :label="t('page.maintenance.oos_status')"
          :options="statusOptions"
        />

        <FormControl
          v-model="form.reason"
          type="textarea"
          :label="t('page.maintenance.oos_reason')"
          rows="3"
        />

        <FormControl v-model="form.until_date" type="date" :label="t('page.maintenance.oos_until')" />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button
            variant="solid"
            theme="red"
            :loading="saving"
            :disabled="!form.reason.trim()"
            @click="submit"
          >
            {{ t('page.maintenance.take_out_of_service') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { OUT_OF_SERVICE_STATUSES, takeOutOfServiceResource } from '@/resources/maintenance'
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

const takeOutOfService = takeOutOfServiceResource()

const saving = ref(false)
const errorMessage = ref('')
const form = reactive({ status: OUT_OF_SERVICE_STATUSES[0], reason: '', until_date: '' })

const statusOptions = OUT_OF_SERVICE_STATUSES.map((value) => ({ label: value, value }))

watch(
  () => [props.modelValue, props.ticket?.name],
  ([isOpen]) => {
    if (!isOpen) return

    errorMessage.value = ''
    form.status = OUT_OF_SERVICE_STATUSES[0]
    form.reason = ''
    form.until_date = ''
  },
)

async function submit() {
  if (!props.ticket) return

  saving.value = true
  errorMessage.value = ''

  try {
    await takeOutOfService.submit({
      ticket: props.ticket.name,
      status: form.status,
      reason: form.reason.trim(),
      until_date: form.until_date || undefined,
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
