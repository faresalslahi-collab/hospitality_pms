<!--
  Return money to a guest.

  There was no refund UI before 16.7.5 — the backend was complete and
  concurrency-safe, and a cashier still had to open Desk to use it.

  **The ceiling shown here is advisory.** `remainingRefundable` is arithmetic on
  what the server already told us, and it exists so an operator is not walked
  into a refusal. The server recomputes it under a row lock and refuses anything
  above it, which is what stops two simultaneous partial refunds from together
  exceeding the capture. If the two ever disagree, the server is right.

  **The key belongs to the decision, not to the click.** `useOperationKey` mints
  one key per refund the operator decided on and reuses it across every retry of
  that submit. Until 16.7.5 the server derived `refund:{transaction}:{amount}`
  when none was supplied, so a second goodwill refund of the same amount was
  swallowed as a duplicate and refunded nothing while reporting success.

  A refund is never silent: the amount, what remains, and the resulting state
  are all on screen before the button is live.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.payments.refund_title'), size: 'lg' }">
    <template #body-content>
      <div class="space-y-4">
        <dl class="grid grid-cols-2 gap-x-4 gap-y-3 rounded border border-outline-gray-1 p-3">
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.payments.captured') }}
            </dt>
            <dd class="mt-0.5">
              <MoneyDisplay :value="transaction?.amount" :currency="currency" />
            </dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.payments.already_refunded') }}
            </dt>
            <dd class="mt-0.5">
              <MoneyDisplay :value="transaction?.refunded_amount" :currency="currency" />
            </dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.payments.remaining_refundable') }}
            </dt>
            <dd class="mt-0.5">
              <MoneyDisplay :value="remaining" :currency="currency" bold />
            </dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.payments.state') }}
            </dt>
            <dd class="mt-0.5">
              <Badge
                :theme="paymentStateTheme(transaction?.transaction_status)"
                variant="subtle"
                :label="transaction?.transaction_status || '—'"
              />
            </dd>
          </div>
        </dl>

        <FormControl
          v-model="form.amount"
          type="number"
          step="0.01"
          :label="t('page.payments.refund_amount')"
        />

        <FormControl
          v-model="form.reason"
          type="textarea"
          :rows="3"
          :label="t('page.folio.reason')"
          :placeholder="t('page.payments.refund_reason_hint')"
        />

        <p v-if="overCeiling" class="text-p-sm text-ink-red-4">
          {{ t('page.payments.refund_over_ceiling') }}
        </p>

        <p class="text-p-sm text-ink-gray-6">{{ t('page.payments.refund_warning') }}</p>

        <ErrorMessage :message="errorMessage" />
      </div>
    </template>

    <template #actions>
      <div class="flex justify-end gap-2">
        <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
        <Button
          variant="solid"
          theme="red"
          :loading="refund.loading"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ t('page.payments.refund') }}
        </Button>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Badge, Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, watch } from 'vue'

import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import { paymentStateTheme, refundPaymentResource, remainingRefundable } from '@/resources/payments'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'
import { useOperationKey } from '@/utils/operationKey'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** The transaction as `payments.get_transaction` returned it. */
  transaction: { type: Object, default: null },
  currency: { type: String, default: null },
})

const emit = defineEmits(['update:modelValue', 'refunded'])

const refund = refundPaymentResource()
const operation = useOperationKey('refund')

const form = reactive({ amount: '', reason: '' })

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const remaining = computed(() => remainingRefundable(props.transaction))

const errorMessage = computed(() => (refund.error ? normaliseError(refund.error).message : ''))

/**
 * Over the ceiling the server told us about.
 *
 * A warning, not a gate — the button is still disabled by `canSubmit`, but the
 * server's refusal is the authority and its wording is what the operator sees
 * if the two ever disagree.
 */
const overCeiling = computed(() => {
  const value = Number(form.amount)

  if (!form.amount || Number.isNaN(value) || remaining.value === null) return false

  return value > remaining.value + 0.005
})

const canSubmit = computed(() => {
  const value = Number(form.amount)

  return (
    form.amount !== '' &&
    !Number.isNaN(value) &&
    value > 0 &&
    Boolean(form.reason.trim()) &&
    !overCeiling.value
  )
})

// A fresh operation each time the dialog opens: a reason typed for one refund
// must never be submitted under the key minted for another.
watch(open, (value) => {
  if (!value) return

  form.amount = ''
  form.reason = ''
  refund.error = null
  operation.reset()
})

async function submit() {
  if (!canSubmit.value) return

  try {
    await refund.submit({
      transaction: props.transaction.name,
      amount: Number(form.amount),
      reason: form.reason.trim(),
      idempotency_key: operation.current(),
    })
  } catch {
    // The refusal is already rendered from `refund.error`, and the dialog
    // stays open. `operation.done()` is deliberately not reached: the key
    // belongs to this refund decision and must be reused if the operator
    // retries it, or the retry becomes a second refund.
    return
  }

  operation.done()
  open.value = false
  emit('refunded')
}
</script>
