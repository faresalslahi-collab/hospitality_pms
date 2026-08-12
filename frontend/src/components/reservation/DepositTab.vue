<!--
  Guarantee & deposit — display only, and honest about what that means.

  There is **no editable money field on this tab, or anywhere in this workspace.**
  Money enters the system as a payment on a folio, never as a number typed onto a
  reservation, so `editability.may_edit_deposit` is `false` in every status the
  server can be in and this tab renders a position rather than a form.

  What makes that uncomfortable, and why the warning below exists: nothing in the
  application writes `deposit_received`. A folio's only production creator is
  check-in, so a deposit cannot be recorded *before* arrival at all — and if
  `deposit_required` is set, check-in is refused for want of it, with no in-app
  remedy. An agent reading a red "outstanding" figure would go hunting for a
  payment screen that does not exist. So this tab states the expectation, states
  that nothing is recorded against it, and says plainly that check-in will be
  refused; it computes no shortfall and offers no verb it cannot honour.

  Two further boundaries:

  - The deposit is never rendered through `FolioBalance`, and never beside a real
    folio balance. Both would imply the hotel is holding money it is not.
  - `guarantee_type` and `guaranteed_on` are shown as *recorded* — no card icon, no
    "card on file", nothing implying a token is held. `services.reservations`
    verifies no instrument and this application has no card vault.

  `deposit.credited` is folio money and answers a different DocType's question, so
  it is absent for a caller who may not read Guest Folio. Absence is reported as
  withheld from the reader; the expectation fields above it are Reservation's own
  and stay on screen either way.
-->
<template>
  <div class="grid gap-5 lg:grid-cols-3">
    <section class="space-y-5 lg:col-span-2">
      <div class="rounded border border-outline-gray-1">
        <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
          {{ t('page.reservation.tab.deposit') }}
        </h2>

        <div class="space-y-4 p-4">
          <p class="text-p-sm text-ink-gray-6">{{ t('page.reservation.deposit.display_only') }}</p>

          <dl class="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
            <div class="min-w-0">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
                {{ t('page.reservation.deposit.policy') }}
              </dt>
              <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ deposit.deposit_policy || '—' }}</dd>
            </div>

            <div class="min-w-0">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
                {{ t('page.reservation.deposit.required') }}
              </dt>
              <dd class="mt-0.5 text-p-sm">
                <MoneyDisplay :value="deposit.deposit_required ?? null" :currency="currency" bold />
              </dd>
            </div>

            <div class="min-w-0">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
                {{ t('page.reservation.deposit.received') }}
              </dt>
              <dd class="mt-0.5 text-p-sm">
                <MoneyDisplay :value="deposit.deposit_received ?? null" :currency="currency" />
              </dd>
            </div>

            <div class="min-w-0">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
                {{ t('page.reservation.deposit.due_date') }}
              </dt>
              <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ formatDate(deposit.deposit_due_date) || '—' }}</dd>
            </div>
          </dl>

          <!--
            The expectation is set and nothing is recorded against it. Stated as an
            alert with the two figures the check-in screen itself shows when it
            refuses, so the agent reads the same sentence in both places.
          -->
          <div
            v-if="nothingRecorded"
            class="flex flex-wrap items-center gap-2 rounded border border-outline-amber-1 bg-surface-amber-1 p-3"
          >
            <AlertBadge present severity="high" :label="t('page.reservation.deposit.required')" />
            <p class="text-p-sm text-ink-amber-3">{{ expectationWarning }}</p>
          </div>

          <div class="border-t border-outline-gray-1 pt-3">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation.deposit.credited') }}
            </dt>
            <dd v-if="creditedDisclosed" class="mt-0.5 text-p-sm">
              <MoneyDisplay :value="deposit.credited" :currency="currency" />
            </dd>
            <!-- Withheld from this reader, not zero. -->
            <dd v-else class="mt-0.5 text-p-sm text-ink-gray-6">
              {{ t('page.reservation.deposit.credited_restricted') }}
            </dd>
          </div>
        </div>
      </div>

      <!--
        Per-room shares of the deposit, as the server apportioned them. Arithmetic
        over stored values, done on the server so the shares add back to the
        deposit exactly; nothing is divided here.
      -->
      <div v-if="allocationRows.length" class="rounded border border-outline-gray-1">
        <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
          {{ t('page.reservation.deposit.allocation') }}
        </h2>

        <div class="p-4">
          <OperationalDataTable
            :columns="allocationColumns"
            :rows="allocationRows"
            row-key="name"
            :aria-label="t('page.reservation.deposit.allocation')"
            dense
          />
        </div>
      </div>
    </section>

    <aside class="space-y-4">
      <div class="rounded border border-outline-gray-1">
        <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
          {{ t('page.reservation.deposit.guarantee') }}
        </h2>

        <dl class="space-y-3 p-4">
          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation.deposit.guarantee') }}
            </dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.guarantee_type || '—' }}</dd>
          </div>

          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation.deposit.guaranteed_on') }}
            </dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ formatDateTime(reservation.guaranteed_on) || '—' }}</dd>
          </div>
        </dl>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed } from 'vue'

import AlertBadge from '@/components/operational/AlertBadge.vue'
import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import { hasField } from '@/resources/guests'
import { formatCurrency, formatDate, formatDateTime } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  reservation: { type: Object, required: true },
  /** The deposit position. `credited` is absent unless the caller may read folios. */
  deposit: { type: Object, required: true },
  /** The room lines, to name the allocation's shares. Never re-read for money. */
  rooms: { type: Array, default: () => [] },
})

const currency = computed(() => props.reservation.currency || null)

/** Presence, not truthiness: `0.00` credited is a real answer, absence is not. */
const creditedDisclosed = computed(() => hasField(props.deposit, 'credited'))

const required = computed(() => Number(props.deposit.deposit_required) || 0)
const received = computed(() => Number(props.deposit.deposit_received) || 0)

/** An expectation with nothing against it — the state that blocks check-in. */
const nothingRecorded = computed(() => required.value > 0.005 && received.value <= 0.005)

/**
 * The same wording the check-in screen shows when it refuses for a deposit, with
 * the server's own two figures. No shortfall is computed: the difference between
 * them is not a debt this application can take.
 */
const expectationWarning = computed(() =>
  t('page.check_in.deposit_warning', {
    required: formatCurrency(required.value, currency.value),
    received: formatCurrency(received.value, currency.value),
  }),
)

const allocationColumns = computed(() => [
  { key: 'line', label: t('page.reservations.rooms'), primary: true },
  { key: 'room_type', label: t('page.arrivals.room_type') },
  { key: 'amount', label: t('page.reservation.rooms.amount'), type: 'money' },
])

/**
 * One row per share the server allocated, named from the room line it belongs to.
 *
 * `room_type_name` is the display name and `room_type` is the code; the name is
 * preferred where the server disclosed it, and the code is never labelled as one.
 */
const allocationRows = computed(() => {
  const allocation = props.deposit.allocation || {}

  return Object.entries(allocation).map(([lineName, amount]) => {
    const line = props.rooms.find((room) => room.name === lineName) || null

    return {
      name: lineName,
      line: line ? t('page.reservation.rooms.line', { idx: line.idx }) : lineName,
      room_type: line?.room_type_name || line?.room_type || '',
      amount,
      currency: currency.value,
    }
  })
})
</script>
