<!-- Take a payment against a folio. -->
<template>
  <Dialog v-model="open" :options="{ title: t('page.folio.take_payment_title'), size: 'lg' }">
    <template #body-content>
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <FormControl
            v-model="form.payment_type"
            type="select"
            :label="t('page.folio.payment_type')"
            :options="paymentTypeOptions"
          />
          <FormControl
            v-model="form.payment_method"
            type="select"
            :label="t('page.folio.payment_method')"
            :options="paymentMethodOptions"
          />
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <FormControl v-model="form.amount" type="number" step="0.01" :label="t('page.folio.amount')" />
          <FormControl
            v-model="form.payer"
            type="select"
            :label="t('page.folio.payer')"
            :options="payerOptions"
          />
        </div>

        <FormControl v-model="form.reference" type="text" :label="t('page.folio.optional_reference')" />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!canSubmit" @click="submit">
            {{ t('page.folio.take_payment') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { PAYER_OPTIONS, PAYMENT_METHOD_OPTIONS, PAYMENT_TYPE_OPTIONS, postPaymentResource } from '@/resources/folio'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  folio: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'posted'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const postPayment = postPaymentResource()

const saving = ref(false)
const errorMessage = ref('')

function blankForm() {
  return { payment_type: 'Payment', payment_method: 'Cash', amount: '', payer: 'Guest', reference: '' }
}

const form = reactive(blankForm())

const paymentTypeOptions = PAYMENT_TYPE_OPTIONS.map((value) => ({ label: value, value }))
const paymentMethodOptions = PAYMENT_METHOD_OPTIONS.map((value) => ({ label: value, value }))
const payerOptions = PAYER_OPTIONS.map((value) => ({ label: value, value }))

const canSubmit = computed(() => form.amount !== '' && form.amount !== null && Number(form.amount) > 0)

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return
    errorMessage.value = ''
    Object.assign(form, blankForm())
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await postPayment.submit({
      folio: props.folio,
      amount: Number(form.amount),
      payment_method: form.payment_method,
      payment_type: form.payment_type,
      reference: form.reference.trim() || undefined,
      payer: form.payer,
    })

    emit('posted')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
