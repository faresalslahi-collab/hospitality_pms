<!--
  Post a charge to a folio.

  Every charge type the DocType accepts is offered; the server refuses one
  that is not postable in the folio's current status rather than this dialog
  guessing the rule (Frontend Standards section 5, same pattern as
  RoomDetailDialog).
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.folio.post_charge_title'), size: 'lg' }">
    <template #body-content>
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <FormControl
            v-model="form.charge_type"
            type="select"
            :label="t('page.folio.charge_type')"
            :options="chargeTypeOptions"
          />
          <FormControl
            v-model="form.payer"
            type="select"
            :label="t('page.folio.payer')"
            :options="payerOptions"
          />
        </div>

        <FormControl v-model="form.description" type="text" :label="t('page.folio.description')" />

        <div class="grid gap-3 sm:grid-cols-3">
          <FormControl v-model="form.quantity" type="number" min="0" step="1" :label="t('page.folio.quantity')" />
          <FormControl v-model="form.amount" type="number" step="0.01" :label="t('page.folio.amount')" />
          <FormControl v-model="form.tax_amount" type="number" min="0" step="0.01" :label="t('page.folio.tax')" />
        </div>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!canSubmit" @click="submit">
            {{ t('page.folio.post_charge') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { CHARGE_TYPE_OPTIONS, PAYER_OPTIONS, postChargeResource } from '@/resources/folio'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'
import { useOperationKey } from '@/utils/operationKey'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  folio: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'posted'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const postCharge = postChargeResource()

// One key per charge the operator is posting. It outlives a failed attempt, so
// pressing Post again after a timeout retries the same operation rather than
// starting a second one.
const operation = useOperationKey('charge')

const saving = ref(false)
const errorMessage = ref('')

function blankForm() {
  return { charge_type: 'Room Service', description: '', quantity: 1, amount: '', tax_amount: 0, payer: 'Guest' }
}

const form = reactive(blankForm())

const chargeTypeOptions = CHARGE_TYPE_OPTIONS.map((value) => ({ label: value, value }))
const payerOptions = PAYER_OPTIONS.map((value) => ({ label: value, value }))

const canSubmit = computed(() => Boolean(form.description.trim()) && form.amount !== '' && form.amount !== null)

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return
    errorMessage.value = ''
    Object.assign(form, blankForm())
    // Opening the dialog is the operator starting a new charge.
    operation.reset()
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await postCharge.submit({
      folio: props.folio,
      charge_type: form.charge_type,
      description: form.description.trim(),
      amount: Number(form.amount),
      quantity: Number(form.quantity || 1),
      tax_amount: Number(form.tax_amount || 0),
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
