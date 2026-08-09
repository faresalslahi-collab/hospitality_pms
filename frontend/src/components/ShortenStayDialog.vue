<!--
  Shorten a stay: the guest leaves earlier than they booked.

  A reason is mandatory because shortening a stay changes what the hotel
  expected to earn, and the server refuses without one. Charges already posted
  are not removed — a night the guest slept is a night they owe, and unwinding
  it is a folio reversal, not a date change.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.stay.shorten_title'), size: 'md' }">
    <template #body-content>
      <div class="space-y-4">
        <div class="rounded bg-surface-amber-1 px-3 py-2">
          <p class="text-p-sm text-ink-amber-3">{{ t('page.stay.shorten_hint') }}</p>
        </div>

        <p class="text-p-sm text-ink-gray-8">
          {{ stay?.guest_name }} · {{ t('page.stay.room') }} {{ stay?.room }} ·
          {{ formatDate(stay?.departure_date) }}
        </p>

        <FormControl
          v-model="form.departure"
          type="date"
          :label="t('page.stay.new_departure')"
          :max="stay?.departure_date || ''"
        />

        <p v-if="tooLate" class="text-p-sm text-ink-red-3">
          {{ t('page.stay.shorten_earlier_only') }}
        </p>

        <FormControl
          v-model="form.reason"
          type="textarea"
          :label="t('page.stay.shorten_reason')"
          rows="3"
        />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!canSubmit" @click="submit">
            {{ t('page.stay.shorten') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { shortenStayResource } from '@/resources/stays'
import { normaliseError } from '@/utils/errors'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  stay: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const shortenStay = shortenStayResource()

const saving = ref(false)
const errorMessage = ref('')
const form = reactive({ departure: '', reason: '' })

const tooLate = computed(
  () => Boolean(form.departure) && form.departure >= (props.stay?.departure_date || ''),
)
const canSubmit = computed(
  () => Boolean(form.departure) && !tooLate.value && Boolean(form.reason.trim()) && !saving.value,
)

watch(
  () => [props.modelValue, props.stay?.name],
  ([isOpen]) => {
    if (!isOpen) return

    errorMessage.value = ''
    form.departure = ''
    form.reason = ''
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await shortenStay.submit({
      stay: props.stay.name,
      new_departure: form.departure,
      reason: form.reason.trim(),
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
