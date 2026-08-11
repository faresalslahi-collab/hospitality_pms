<!--
  Record a reservation as a no-show.

  A sibling of CancelReservationDialog and, like it, whole-reservation in scope:
  `reservations.mark_no_show` transitions the reservation and `_propagate_status`
  stamps every room line, so a no-show raised from one row of a three-room
  booking marks all three. The caller passes the room count and the scope is
  stated before the reason field.

  Two things differ from a cancellation:

  - The reason is **optional**. `mark_no_show` accepts `reason=None` and records
    "Recorded as a no-show" itself, so the confirm button is never disabled on a
    blank one.
  - The role is narrower. `NO_SHOW_ROLES` excludes Front Office Agent, and the
    caller mirrors that list when deciding whether to offer this dialog.

  The charge is the server's and is shown afterwards as **policy**:
  `mark_no_show` computes it from the no-show policy and writes
  `Reservation.cancellation_charge`. It posts no Folio Charge and creates no
  ledger entry, so no wording here may suggest money changed hands. Nothing is
  pre-computed either: the row carries no such figure and pricing policy is not
  the client's to evaluate.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.arrivals.no_show_title') }">
    <template #body-content>
      <div v-if="outcome" class="space-y-3">
        <p class="text-p-sm text-ink-gray-8">{{ t('page.arrivals.no_show_done') }}</p>
        <p v-if="chargeText" class="text-p-sm font-medium text-ink-gray-9">{{ chargeText }}</p>

        <div class="flex justify-end">
          <Button variant="solid" @click="open = false">{{ t('common.close') }}</Button>
        </div>
      </div>

      <div v-else class="space-y-3">
        <!--
          The scope, first. Only the multi-room wording exists in the catalogue,
          and it is the only case that needs saying: a one-room reservation has
          no hidden reach for the sentence to warn about.
        -->
        <p v-if="scopeMessage" class="text-p-sm text-ink-gray-6">{{ scopeMessage }}</p>
        <p class="text-p-sm text-ink-gray-6">{{ t('page.arrivals.no_show_hint') }}</p>

        <FormControl v-model="reason" type="textarea" :rows="3" :label="t('page.arrivals.no_show_reason')" />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.close') }}</Button>
          <Button variant="solid" theme="red" :loading="saving" @click="submit">
            {{ t('page.arrivals.no_show_confirm') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import { noShowResource } from '@/resources/reservations'
import { normaliseError } from '@/utils/errors'
import { formatCurrency } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  reservation: { type: String, default: '' },
  /** The reservation's room count, from the row. Never computed here. */
  rooms: { type: Number, default: null },
  currency: { type: String, default: null },
})

const emit = defineEmits(['update:modelValue', 'marked'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const noShow = noShowResource()

const reason = ref('')
const saving = ref(false)
const errorMessage = ref('')
const outcome = ref(null)

const scopeMessage = computed(() =>
  Number(props.rooms) > 1
    ? t('page.arrivals.no_show_whole_reservation', { count: props.rooms })
    : '',
)

/** Policy, not receipt: the figure the server decided, and nothing was posted. */
const chargeText = computed(() => {
  const charge = Number(outcome.value?.no_show_charge)

  if (!Number.isFinite(charge) || charge <= 0.005) return ''

  return t('page.arrivals.no_show_charge', { amount: formatCurrency(charge, props.currency) })
})

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return

    reason.value = ''
    errorMessage.value = ''
    outcome.value = null
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    const result = await noShow.submit({
      reservation: props.reservation,
      // Blank means "not given": the server records its own wording rather than
      // storing an empty reason.
      reason: reason.value.trim() || undefined,
    })

    outcome.value = result?.no_show || {}
    emit('marked', outcome.value)
  } catch (error) {
    // Includes the refusal a stale board earns: the server re-reads the status
    // under a lock, and its wording is what the desk is shown.
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
