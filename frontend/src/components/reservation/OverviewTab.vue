<!--
  Overview: what this booking is, and the few details of it that may be corrected.

  Read first, edit second. Everything above the booking block is the server's own
  statement of the reservation and is never editable here — the dates and the rooms
  are inventory decisions and belong to Rooms & rates, where availability is
  re-checked, and the status is a transition with its own audit record.

  The three fields this tab collects — booking source, market segment and expected
  arrival time — are exactly three of the fields `update_reservation_details`
  accepts. They carry no availability or pricing consequence, which is why the
  server keeps them editable for as long as the booking is live. Whether they may
  be edited at all is `editability.may_edit_details`; this component never looks at
  the status to decide, and where the server says no it says why.

  Edits are not saved here. They are collected into the page's one draft alongside
  the Notes tab's two fields and saved in a single call, so correcting a source and
  a note is one write and one audit entry rather than two.

  **No rate comparison, anywhere.** A "booked rate versus today's rate" panel was
  considered and dropped: `get_rate_breakdown` never consults a negotiated
  corporate rate, so for a corporate booking the difference it would display is the
  contract discount, and the panel would tell an agent the hotel is out of pocket
  by an amount it agreed to. There is no such element on this tab by design.
-->
<template>
  <div class="grid gap-5 lg:grid-cols-3">
    <section class="space-y-5 lg:col-span-2">
      <!-- The stay, as the header records it. -->
      <div class="rounded border border-outline-gray-1">
        <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
          {{ t('page.reservation.overview.stay') }}
        </h2>

        <dl class="grid grid-cols-2 gap-x-4 gap-y-3 p-4 sm:grid-cols-3">
          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservations.arrival') }} – {{ t('page.reservations.departure') }}
            </dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">
              {{ formatDate(reservation.arrival_date) }} → {{ formatDate(reservation.departure_date) }}
            </dd>
          </div>

          <!--
            The header interval is min(arrival)/max(departure) across the lines, so
            a night count for it is meaningless once the lines disagree. Withheld
            rather than approximated; Rooms & rates holds the real intervals.
          -->
          <div v-if="!linesDiffer" class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservations.nights') }}</dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.nights }}</dd>
          </div>

          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservations.rooms') }}</dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.total_rooms }}</dd>
          </div>

          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservation.guests') }}</dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">
              {{
                t('page.reservation.guests.occupancy_line', {
                  adults: reservation.total_adults ?? 0,
                  children: reservation.total_children ?? 0,
                })
              }}
            </dd>
          </div>

          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservations.status') }}</dt>
            <dd class="mt-0.5">
              <Badge
                :theme="reservationStatusTheme(reservation.reservation_status)"
                variant="subtle"
                :label="reservation.reservation_status"
              />
            </dd>
          </div>

          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation_new.total_amount') }}
            </dt>
            <dd class="mt-0.5 text-p-sm">
              <MoneyDisplay :value="reservation.total_amount" :currency="reservation.currency" bold />
            </dd>
          </div>
        </dl>

        <!--
          The policy figure the server decided and wrote to the reservation. It is
          stated as policy: `cancel` and `mark_no_show` post no Folio Charge and
          make no ledger entry, so nothing here may read as money taken.
        -->
        <p v-if="cancellationCharge" class="border-t border-outline-gray-1 px-4 py-2 text-p-sm text-ink-gray-7">
          {{ cancellationCharge }}
        </p>
      </div>

      <!-- The booking's own particulars, and the three that may be corrected. -->
      <div class="rounded border border-outline-gray-1">
        <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
          {{ t('page.reservation.overview.booking') }}
        </h2>

        <div class="space-y-4 p-4">
          <!-- The server's reason, in the server's terms. Never re-derived here. -->
          <p v-if="!editable" class="text-p-sm text-ink-gray-6">
            {{ t('page.reservation.not_editable_here', { status: editability.status }) }}
          </p>

          <dl class="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
            <div class="min-w-0">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
                {{ t('page.reservation_new.reservation_type') }}
              </dt>
              <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.reservation_type || '—' }}</dd>
            </div>

            <div class="min-w-0">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
                {{ t('page.reservation.overview.external_reference') }}
              </dt>
              <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.external_reference || '—' }}</dd>
            </div>
          </dl>

          <div class="grid gap-4 sm:grid-cols-3">
            <FormControl
              v-if="editable"
              type="text"
              :label="t('page.reservation.source')"
              :model-value="values.booking_source"
              @update:model-value="onEdit('booking_source', $event)"
            />
            <div v-else class="min-w-0">
              <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservation.source') }}</p>
              <p class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.booking_source || '—' }}</p>
            </div>

            <FormControl
              v-if="editable"
              type="text"
              :label="t('page.reservation.overview.market_segment')"
              :model-value="values.market_segment"
              @update:model-value="onEdit('market_segment', $event)"
            />
            <div v-else class="min-w-0">
              <p class="text-xs uppercase tracking-wide text-ink-gray-5">
                {{ t('page.reservation.overview.market_segment') }}
              </p>
              <p class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.market_segment || '—' }}</p>
            </div>

            <!--
              An expectation, not a date: the arrival *day* is inventory and moves
              only through Rooms & rates. This is the time the guest said they
              would turn up.
            -->
            <FormControl
              v-if="editable"
              type="time"
              :label="t('page.reservation.overview.eta')"
              :model-value="values.arrival_time"
              @update:model-value="onEdit('arrival_time', $event)"
            />
            <div v-else class="min-w-0">
              <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservation.overview.eta') }}</p>
              <p class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.arrival_time || '—' }}</p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!--
      The company behind the booking. Absent from the payload means one of two
      things — there is no company, or this caller may not read Corporate Account —
      and the two are not distinguishable from here, so nothing is rendered and
      nothing is claimed either way.
    -->
    <aside v-if="corporate" class="space-y-4">
      <div class="rounded border border-outline-gray-1">
        <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
          {{ t('page.reservation.overview.contract') }}
        </h2>

        <dl class="space-y-3 p-4">
          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation.overview.corporate') }}
            </dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">
              {{ corporate.account_name || corporate.account }}
            </dd>
          </div>

          <div v-if="creditStatus" class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation.overview.credit_status') }}
            </dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ creditStatus }}</dd>
          </div>

          <!--
            The service could not answer for this account (a configuration problem
            on the account itself). Said plainly rather than shown as a zero, which
            would read as "no credit left".
          -->
          <p v-if="!corporate.credit" class="text-p-sm text-ink-gray-6">
            {{ t('page.reservation.overview.credit_unavailable') }}
          </p>
        </dl>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { Badge, FormControl } from 'frappe-ui'
import { computed } from 'vue'

import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import { reservationStatusTheme } from '@/resources/reservations'
import { formatCurrency, formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  reservation: { type: Object, required: true },
  /** The server's editability statement. The only source of enabled/disabled. */
  editability: { type: Object, required: true },
  /**
   * The draft-merged values of the fields this tab collects, so an unsaved edit
   * survives a tab change. The page owns the draft; this tab only reports intent.
   */
  values: { type: Object, default: () => ({}) },
  /** `null` means the server disclosed no corporate section — see the aside. */
  corporate: { type: Object, default: null },
  /** Whether the room lines hold different intervals. Decided by the page. */
  linesDiffer: { type: Boolean, default: false },
})

const emit = defineEmits(['edit'])

const editable = computed(() => Boolean(props.editability?.may_edit_details))

/** The account's own status, whichever of the two the server could answer with. */
const creditStatus = computed(() => props.corporate?.credit_status || props.corporate?.credit?.credit_status || '')

const cancellationCharge = computed(() => {
  const charge = Number(props.reservation.cancellation_charge)

  if (!Number.isFinite(charge) || charge <= 0.005) return ''

  return t('page.arrivals.cancel_charge', {
    amount: formatCurrency(charge, props.reservation.currency),
  })
})

function onEdit(field, value) {
  emit('edit', { field, value })
}
</script>
