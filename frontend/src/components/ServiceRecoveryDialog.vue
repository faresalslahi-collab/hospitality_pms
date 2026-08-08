<!--
  Compensate a guest for a request or complaint.

  An amount greater than zero posts a Discount charge to the guest's folio
  (Services section on service recovery). That is money leaving the hotel's
  ledger, so it gets the same explicit warning and confirmation as any other
  folio adjustment — the server still holds the real authority (role check
  and idempotency key), this dialog only makes sure nobody posts one by
  accident.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.guest_services.recovery_title'), size: 'md' }">
    <template #body-content>
      <div class="space-y-3">
        <FormControl
          v-model="form.recovery_type"
          type="select"
          :label="t('page.guest_services.recovery_type')"
          :options="recoveryTypeOptions"
        />

        <FormControl
          v-model="form.amount"
          type="number"
          min="0"
          step="0.01"
          :label="t('page.guest_services.recovery_amount')"
        />

        <FormControl
          v-model="form.reason"
          type="textarea"
          rows="3"
          :label="t('page.guest_services.recovery_reason')"
        />

        <FormControl
          v-if="amountValue > 0"
          v-model="form.post_to_folio"
          type="checkbox"
          :label="t('page.guest_services.recovery_post_to_folio')"
        />

        <div v-if="amountValue > 0 && form.post_to_folio" class="rounded bg-surface-amber-1 p-3">
          <p class="text-p-sm text-ink-amber-3">{{ t('page.guest_services.recovery_warning') }}</p>
          <FormControl
            v-model="confirmed"
            type="checkbox"
            class="mt-2"
            :label="
              t('page.guest_services.recovery_confirm_checkbox', {
                amount: formatCurrency(amountValue, request?.currency),
              })
            "
          />
        </div>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button
            variant="solid"
            theme="red"
            :loading="saving"
            :disabled="!canSubmit"
            @click="submit"
          >
            {{ t('page.guest_services.recovery_submit') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { RECOVERY_TYPE_OPTIONS, serviceRecoveryResource } from '@/resources/guestServices'
import { normaliseError } from '@/utils/errors'
import { formatCurrency } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  request: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'applied'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const recoveryResource = serviceRecoveryResource()

const saving = ref(false)
const errorMessage = ref('')
const confirmed = ref(false)

const form = reactive({
  recovery_type: 'Apology',
  amount: 0,
  reason: '',
  post_to_folio: true,
})

const recoveryTypeOptions = RECOVERY_TYPE_OPTIONS.map((value) => ({ label: value, value }))

const amountValue = computed(() => Number(form.amount) || 0)

const canSubmit = computed(() => {
  if (!form.reason.trim()) return false
  if (amountValue.value > 0 && form.post_to_folio) return confirmed.value

  return true
})

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return

    errorMessage.value = ''
    confirmed.value = false
    Object.assign(form, { recovery_type: 'Apology', amount: 0, reason: '', post_to_folio: true })
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await recoveryResource.submit({
      request: props.request?.name,
      recovery_type: form.recovery_type,
      reason: form.reason.trim(),
      amount: amountValue.value,
      post_to_folio: form.post_to_folio ? 1 : 0,
    })

    emit('applied')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
