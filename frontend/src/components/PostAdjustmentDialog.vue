<!--
  Post an adjustment to a folio.

  An adjustment is its own charge line, not an edit of an existing one — the
  ledger keeps every line it ever posted. The server enforces finance
  authority and a reason; this dialog only keeps the submit button honest.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.folio.post_adjustment_title'), size: 'lg' }">
    <template #body-content>
      <div class="space-y-3">
        <p class="text-p-sm text-ink-gray-6">{{ t('page.folio.post_adjustment_hint') }}</p>

        <div class="grid gap-3 sm:grid-cols-2">
          <FormControl v-model="form.amount" type="number" step="0.01" :label="t('page.folio.amount')" />
          <FormControl
            v-model="form.payer"
            type="select"
            :label="t('page.folio.payer')"
            :options="payerOptions"
          />
        </div>

        <FormControl v-model="form.description" type="text" :label="t('page.folio.description')" />
        <FormControl v-model="form.reason" type="textarea" rows="2" :label="t('page.folio.reason')" />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!canSubmit" @click="submit">
            {{ t('page.folio.post_adjustment') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { PAYER_OPTIONS, postAdjustmentResource } from '@/resources/folio'
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

const postAdjustment = postAdjustmentResource()

const saving = ref(false)
const errorMessage = ref('')

function blankForm() {
  return { amount: '', description: '', reason: '', payer: 'Guest' }
}

const form = reactive(blankForm())

const payerOptions = PAYER_OPTIONS.map((value) => ({ label: value, value }))

const canSubmit = computed(
  () => form.amount !== '' && form.amount !== null && Boolean(form.description.trim()) && Boolean(form.reason.trim()),
)

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
    await postAdjustment.submit({
      folio: props.folio,
      amount: Number(form.amount),
      description: form.description.trim(),
      reason: form.reason.trim(),
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
