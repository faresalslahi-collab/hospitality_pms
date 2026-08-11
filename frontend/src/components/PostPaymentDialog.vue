<!--
  Take a payment against a folio.

  The folio screen opens this with a folio and nothing else, which is right there:
  the balance is already the largest thing on that page. An operational board is
  not, so 16.7.1 adds three optional context props — `balance`, `currency` and
  `guestName`. When they are supplied the outstanding balance is shown inside the
  dialog and the amount is pre-filled with it, because an agent typing a figure
  with the balance nowhere on screen is how 40 becomes 400.

  All three default to null/'' and change nothing when absent: the folio page's
  call site is untouched and behaves exactly as it did.

  No arithmetic is added by any of this. The balance is displayed as the server
  sent it, through the same `FolioBalance` the boards use, and the pre-fill is
  that same number — not a total, not a share, not a remainder.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.folio.take_payment_title'), size: 'lg' }">
    <template #body-content>
      <div class="space-y-3">
        <!-- Context, when the caller has it: who owes, and how much. -->
        <div v-if="guestName || hasBalance" class="rounded border border-outline-gray-1 p-3">
          <p v-if="guestName" class="text-p-sm font-medium text-ink-gray-9">{{ guestName }}</p>
          <FolioBalance v-if="hasBalance" :balance="balance" :currency="currency" size="md" />
        </div>

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

import FolioBalance from '@/components/operational/FolioBalance.vue'
import { PAYER_OPTIONS, PAYMENT_METHOD_OPTIONS, PAYMENT_TYPE_OPTIONS, postPaymentResource } from '@/resources/folio'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'
import { useOperationKey } from '@/utils/operationKey'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  folio: { type: String, default: '' },
  /**
   * Optional context, all additive. Absent means "the caller has none", and the
   * dialog then behaves exactly as it did before these existed.
   */
  balance: { type: [Number, String], default: null },
  currency: { type: String, default: null },
  guestName: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'posted'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const postPayment = postPaymentResource()

// Money in the other direction, same rule: a retried submission must be the
// same payment, not a second one.
const operation = useOperationKey('payment')

const saving = ref(false)
const errorMessage = ref('')

/**
 * Whether a balance was supplied at all. Zero is a real balance and means
 * settled, so only null, an empty string or a non-number mean "not supplied".
 */
const hasBalance = computed(
  () =>
    props.balance !== null &&
    props.balance !== undefined &&
    props.balance !== '' &&
    !Number.isNaN(Number(props.balance)),
)

/**
 * What the amount field starts at.
 *
 * The outstanding balance when one was given and the guest owes it. A settled or
 * credit balance pre-fills nothing: there is no amount to collect, and a
 * negative figure is not a payment.
 */
function prefilledAmount() {
  if (!hasBalance.value) return ''

  const value = Number(props.balance)

  return value > 0.005 ? String(value) : ''
}

function blankForm() {
  return {
    payment_type: 'Payment',
    payment_method: 'Cash',
    amount: prefilledAmount(),
    payer: 'Guest',
    reference: '',
  }
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
    operation.reset()
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
      idempotency_key: operation.current(),
    })

    operation.done()
    emit('posted')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
