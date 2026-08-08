<!--
  Move selected charges onto a new folio, e.g. to bill a company separately
  from the guest's own charges.

  Charges already reversed, and the compensating line a reversal posts, are
  not offered: moving one half of a reversal pair to another folio would
  leave a charge on one folio with its offsetting line on another, which
  nothing then keeps paired.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.folio.split_title'), size: 'lg' }">
    <template #body-content>
      <div class="space-y-3">
        <p class="text-p-sm text-ink-gray-6">{{ t('page.folio.split_hint') }}</p>

        <div class="max-h-72 space-y-1 overflow-y-auto rounded border border-outline-gray-1 p-2">
          <label
            v-for="row in eligibleCharges"
            :key="row.name"
            class="flex items-center justify-between gap-3 rounded px-2 py-1.5 hover:bg-surface-gray-1"
          >
            <span class="flex items-center gap-2 text-p-sm text-ink-gray-8">
              <input type="checkbox" :value="row.name" v-model="selected" class="rounded" />
              {{ row.description }}
              <span class="text-ink-gray-5">· {{ row.charge_type }}</span>
            </span>
            <span class="text-p-sm font-medium text-ink-gray-9">
              {{ formatCurrency(row.total_amount, currency) }}
            </span>
          </label>

          <p v-if="!eligibleCharges.length" class="p-2 text-p-sm text-ink-gray-5">
            {{ t('page.folio.split_none_eligible') }}
          </p>
        </div>

        <FormControl
          v-model="payer"
          type="select"
          :label="t('page.folio.split_payer')"
          :options="payerOptions"
        />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!selected.length" @click="submit">
            {{ t('page.folio.split_confirm') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import { PAYER_OPTIONS, splitFolioResource } from '@/resources/folio'
import { normaliseError } from '@/utils/errors'
import { formatCurrency } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  folio: { type: String, default: '' },
  currency: { type: String, default: '' },
  charges: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'split'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const splitFolio = splitFolioResource()

const saving = ref(false)
const errorMessage = ref('')
const selected = ref([])
const payer = ref('Company')

const payerOptions = PAYER_OPTIONS.map((value) => ({ label: value, value }))

const eligibleCharges = computed(() => props.charges.filter((row) => !row.is_reversed && !row.reversal_of))

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return
    errorMessage.value = ''
    selected.value = []
    payer.value = 'Company'
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    const result = await splitFolio.submit({
      folio: props.folio,
      charge_rows: selected.value,
      payer: payer.value,
    })

    emit('split', result.target?.folio?.name)
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
