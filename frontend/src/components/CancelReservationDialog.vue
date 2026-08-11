<!--
  Cancel a reservation, with the scope of the cancellation stated first.

  Extracted from the inline dialog on `pages/Reservation.vue`, which asks for a
  reason and keeps the confirm button disabled until it is non-blank because
  `services.reservations.cancel` throws on a blank one. That contract is kept
  here verbatim.

  What is new, and the reason this is a component rather than a second copy of
  that dialog: `reservations.cancel` acts on the **whole reservation**, and
  `_propagate_status` stamps every one of its room lines. The arrivals board is
  one row per room line, so cancelling "this row" of a three-room booking
  cancels all three rooms and removes all three rows. The caller therefore
  passes the reservation's room count and this dialog says out loud what is
  about to happen, before the reason field, every time.

  It computes nothing about money. The server returns the policy charge it
  decided and wrote to `Reservation.cancellation_charge`; that figure is shown
  afterwards as policy — no Folio Charge is posted and no ledger entry is made,
  so nothing here may read as a receipt. `waive_charge` is deliberately not
  offered: it needs `CANCEL_OVERRIDE_ROLES` and the server's default is the
  correct answer for this build.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.arrivals.cancel_title') }">
    <template #body-content>
      <!--
        Two phases in one dialog. The outcome phase exists because the policy
        charge is the only place that figure is ever shown: a toast that fades
        is not where an agent reads what the guest now owes.
      -->
      <div v-if="outcome" class="space-y-3">
        <p class="text-p-sm text-ink-gray-8">{{ t('page.arrivals.cancelled') }}</p>
        <p v-if="chargeText" class="text-p-sm font-medium text-ink-gray-9">{{ chargeText }}</p>

        <div class="flex justify-end">
          <Button variant="solid" @click="open = false">{{ t('common.close') }}</Button>
        </div>
      </div>

      <div v-else class="space-y-3">
        <!-- The scope, before anything else on the screen. -->
        <p class="text-p-sm text-ink-gray-6">{{ scopeMessage }}</p>

        <!-- Required, not optional: the server refuses a blank reason. -->
        <FormControl v-model="reason" type="textarea" :rows="3" :label="t('page.arrivals.cancel_reason')" />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.close') }}</Button>
          <Button
            variant="solid"
            theme="red"
            :loading="saving"
            :disabled="!reason.trim()"
            @click="submit"
          >
            {{ t('page.arrivals.cancel_confirm') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import { cancelReservationResource } from '@/resources/reservations'
import { normaliseError } from '@/utils/errors'
import { formatCurrency } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  reservation: { type: String, default: '' },
  /**
   * How many rooms the reservation holds, from the row's `total_rooms`.
   *
   * `null` means the caller does not know, and a caller that does not know must
   * not offer this dialog at all: the scope sentence would then be a guess
   * about how much of the booking is about to end. It is never computed here.
   */
  rooms: { type: Number, default: null },
  /** The reservation's currency, for the policy charge. Never defaulted. */
  currency: { type: String, default: null },
})

const emit = defineEmits(['update:modelValue', 'cancelled'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const cancelResource = cancelReservationResource()

const reason = ref('')
const saving = ref(false)
const errorMessage = ref('')
const outcome = ref(null)

/**
 * What this cancellation reaches.
 *
 * More than one room is the dangerous case and names the count, so an agent
 * cancelling from a single row of a three-room booking reads "all 3 of its
 * rooms" before they type a word.
 */
const scopeMessage = computed(() =>
  Number(props.rooms) > 1
    ? t('page.arrivals.cancel_whole_reservation', { count: props.rooms })
    : t('page.arrivals.cancel_single_room'),
)

/** The server's policy figure, worded as policy. Nothing was posted or taken. */
const chargeText = computed(() => {
  const charge = Number(outcome.value?.cancellation_charge)

  if (!Number.isFinite(charge) || charge <= 0.005) return ''

  return t('page.arrivals.cancel_charge', { amount: formatCurrency(charge, props.currency) })
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
    const result = await cancelResource.submit({
      reservation: props.reservation,
      reason: reason.value.trim(),
    })

    // The API answers with the refreshed reservation plus its `cancellation`
    // block; the charge is the server's, read and never recomputed.
    outcome.value = result?.cancellation || {}
    emit('cancelled', outcome.value)
  } catch (error) {
    // A stale offer — the row said Confirmed, the server re-read Cancelled
    // under its lock — arrives here and is reported in the server's own words.
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
