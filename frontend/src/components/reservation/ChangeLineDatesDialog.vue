<!--
  Move one room line's dates (16.7.2).

  **Per line, never at the header.** The reservation's own `arrival_date` and
  `departure_date` are `refresh_header_dates`' min/max across the room lines, so
  there is nothing there to edit: moving "the booking's dates" would mean moving
  three rooms because one of them changed. `change_line_interval` takes a room line
  and this dialog is opened from one.

  **The rule this dialog exists to explain, and does not enforce.** The service
  re-reads the booking under a lock and refuses a length change on a booking that
  already holds inventory: the guest has been quoted these amounts, no repricing is
  available for the nights that would be added, and a preserved two-night price
  spread over three nights would leave `total_amount`, the booking totals and every
  `Reservation Rate Line` describing an interval the guest does not have. So a held
  booking may be *shifted*, not lengthened or shortened.

  That rule is stated here and checked nowhere here. A second copy of it in Vue
  would be a second statement of the state machine, and it would go stale the first
  time the service's states change; worse, a client-side refusal robs the agent of
  the server's own sentence, which names the booking, the status, the current night
  count and the remedy. So the dialog collects two dates, sends them, and shows
  whatever comes back verbatim.

  **No rate is shown, chosen or computed.** A date change is not a re-quote. The
  booked rate is carried across by the service for a held booking, and re-derived by
  it for a draft; either way the figure on screen after this dialog closes is the
  server's, arriving through the workspace's own refetch.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.reservation.rooms.change_dates_title'), size: 'md' }">
    <template #body-content>
      <div v-if="line" class="space-y-4">
        <!--
          Which room. A three-room booking has three of these dialogs' worth of
          dates, and the one being moved is named before anything can be typed.
        -->
        <div class="rounded border border-outline-gray-1 p-3">
          <p class="text-p-sm font-medium text-ink-gray-8">
            {{ t('page.reservation.rooms.line', { idx: line.idx }) }} ·
            {{ line.room_type_name || line.room_type }}
          </p>

          <dl class="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
            <div class="min-w-0">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservations.arrival') }}</dt>
              <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ formatDate(line.arrival_date) }}</dd>
            </div>
            <div class="min-w-0">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservations.departure') }}</dt>
              <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ formatDate(line.departure_date) }}</dd>
            </div>
            <div class="min-w-0">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservations.nights') }}</dt>
              <dd class="mt-0.5 text-p-sm text-ink-gray-8">
                {{ t('page.availability.nights', { count: line.nights }) }}
              </dd>
            </div>
          </dl>
        </div>

        <!--
          The booking holds inventory, so the length is the one thing that may not
          move. Stated beside the two inputs, with the count it must keep and the
          remedy for changing it — which is not this dialog.
        -->
        <div v-if="isHolding" class="space-y-1 rounded border border-outline-amber-1 bg-surface-amber-1 p-3">
          <p class="text-p-sm font-medium text-ink-amber-3">
            {{ t('page.reservation.rooms.nights_fixed', { count: line.nights }) }}
          </p>
          <p class="text-p-sm text-ink-amber-3">{{ t('page.reservation.rooms.price_preserved') }}</p>
        </div>

        <p class="text-p-sm text-ink-gray-6">{{ t('page.reservation.rooms.change_dates_hint') }}</p>

        <div class="grid gap-3 sm:grid-cols-2">
          <FormControl v-model="form.arrival" type="date" :label="t('page.reservations.arrival')" />
          <FormControl v-model="form.departure" type="date" :label="t('page.reservations.departure')" />
        </div>

        <!--
          The service records this against the booking's log in place of its own
          default wording, so it is offered rather than required: a move with no
          reason is still auditable, and a mandatory box teaches agents to type "x".
        -->
        <FormControl
          v-model="form.reason"
          type="textarea"
          :rows="2"
          :label="t('page.reservation.rooms.reason')"
        />

        <!-- The server's refusal, in the server's words. -->
        <ErrorMessage :message="errorMessage" />

        <div class="flex flex-wrap justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!canSubmit" @click="submit">
            {{ t('page.reservation.rooms.change_dates') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { apiResource } from '@/resources'
import { normaliseError } from '@/utils/errors'
import { formatDate, toServerDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** The reservation's name. The service authorises the document, not the line. */
  reservation: { type: String, default: '' },
  /** The room line being moved, exactly as `get_workspace` sent it. */
  line: { type: Object, default: null },
  /**
   * The server's own `editability.is_holding`. Used to decide what to *say*; the
   * equal-nights rule itself is the service's and is never checked here.
   */
  isHolding: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const changeInterval = apiResource('reservations.change_line_interval')

const saving = ref(false)
const errorMessage = ref('')
const form = reactive({ arrival: '', departure: '', reason: '' })

/**
 * Both ends are always sent, so nothing is inferred from a blank.
 *
 * The service accepts one end alone and moves that end, but a dialog showing two
 * inputs would then send "no change" for whichever one the browser had not filled
 * — which is a different operation from the one the agent is looking at.
 */
const canSubmit = computed(() => Boolean(form.arrival && form.departure) && !saving.value)

/**
 * Opened on a line: the inputs start at the interval the server holds.
 *
 * The dates are the server's own strings and are placed in the inputs as-is. A
 * date-only value carries no time and no zone, so parsing one through an instant to
 * "prepare" it is the defect 16.7.2 fixed in `toServerDate`.
 */
watch(
  () => [props.modelValue, props.line?.name],
  ([isOpen]) => {
    if (!isOpen || !props.line) return

    errorMessage.value = ''
    form.arrival = props.line.arrival_date || ''
    form.departure = props.line.departure_date || ''
    form.reason = ''
  },
)

async function submit() {
  if (!canSubmit.value || !props.line) return

  saving.value = true
  errorMessage.value = ''

  // Only this line. The room line's name is the one thing that decides what moves,
  // and it is read from the line the dialog was opened on.
  const payload = {
    reservation: props.reservation,
    room_line: props.line.name,
    arrival: toServerDate(form.arrival),
    departure: toServerDate(form.departure),
  }

  const reason = form.reason.trim()

  if (reason) payload.reason = reason

  try {
    await changeInterval.submit(payload)

    emit('changed')
    open.value = false
  } catch (error) {
    // Verbatim. The service names the booking, its status, the night count it holds
    // and what to do instead; nothing here can say it better.
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
