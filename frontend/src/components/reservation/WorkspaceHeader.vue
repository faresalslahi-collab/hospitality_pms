<!--
  The Reservation Workspace's persistent header (16.7.2).

  It stays above the tabs because the six tabs are views of one booking, and the
  figures an agent quotes on the phone — who, when, how many rooms, how much, is a
  deposit expected — must not depend on which tab happens to be open.

  Three things it deliberately does NOT do:

  - It decides nothing. Which verbs are offered is `allowed_transitions` and
    `editability` from the server, resolved by the page and handed here as a list.
    This component renders buttons; it holds no copy of the state machine.
  - It computes no money and no dates. Amounts arrive from the server and go
    through MoneyDisplay; dates go through `formatDate`, which slices a date-only
    value instead of parsing it through a UTC instant.
  - It never claims a room is ready, a guest is in house, or a deposit will move
    to a folio. The first two are per-line facts that live in Rooms & rates; the
    third is not true in this build (see DepositTab).

  **The header dates are a span, not the booking's dates.** `refresh_header_dates`
  writes min(arrival) and max(departure) across the room lines, so the moment one
  line of three moves, the header interval covers nights no room occupies. It is
  therefore rendered as one interval, and when the lines disagree the night count
  is withheld entirely — a nights figure for an interval nobody is staying is a
  number an agent would quote. The authoritative per-line intervals are in Rooms &
  rates, which is what the link offers.
-->
<template>
  <div class="bg-surface-white">
    <PageHeader :title="reservation.guest_name || reservation.name" :subtitle="reservation.name">
      <template #actions>
        <Badge
          :theme="reservationStatusTheme(reservation.reservation_status)"
          variant="subtle"
          :label="reservation.reservation_status"
        />

        <!-- Only transitions the server says are reachable are offered. -->
        <Button
          v-for="action in actions"
          :key="action.key"
          :variant="action.variant"
          :theme="action.theme"
          :loading="busy === action.key"
          @click="action.run"
        >
          {{ action.label }}
        </Button>
      </template>
    </PageHeader>

    <dl
      class="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-outline-gray-1 px-5 pb-4 pt-3 sm:grid-cols-3
        lg:grid-cols-6"
    >
      <div class="min-w-0">
        <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
          {{ t('page.reservations.arrival') }} – {{ t('page.reservations.departure') }}
        </dt>
        <dd class="mt-0.5 text-p-sm text-ink-gray-8">
          {{ formatDate(reservation.arrival_date) }} → {{ formatDate(reservation.departure_date) }}
        </dd>
        <!--
          The lines disagree, so this span is wider than any room's stay. The only
          honest thing to offer is the tab that holds the real intervals.
        -->
        <Button
          v-if="linesDiffer"
          class="mt-1"
          variant="subtle"
          size="sm"
          @click="emit('open-tab', 'rooms')"
        >
          {{ t('page.reservation.tab.rooms') }}
        </Button>
      </div>

      <!-- Withheld while the lines disagree: see the note above. -->
      <div v-if="!linesDiffer" class="min-w-0">
        <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservations.nights') }}</dt>
        <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.nights }}</dd>
      </div>

      <div class="min-w-0">
        <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservation.header.rooms') }}</dt>
        <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.total_rooms }}</dd>
      </div>

      <div class="min-w-0">
        <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
          {{ t('page.reservation.header.assigned') }}
        </dt>
        <dd class="mt-0.5 text-p-sm text-ink-gray-8">
          {{ t('page.reservation.header.assigned_count', { assigned: assignedRooms, total: reservation.total_rooms }) }}
        </dd>
      </div>

      <div class="min-w-0">
        <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservation.header.guests') }}</dt>
        <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ occupancy }}</dd>
      </div>

      <div class="min-w-0">
        <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservation.header.total') }}</dt>
        <dd class="mt-0.5 text-p-sm">
          <MoneyDisplay :value="reservation.total_amount" :currency="reservation.currency" bold />
        </dd>
      </div>

      <!--
        The deposit position as the booking records it: what the policy expects and
        what has been recorded. No outstanding figure is computed here — see
        DepositTab for why an "amount due" would send an agent looking for a
        payment screen this build does not have.
      -->
      <div class="min-w-0">
        <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservation.header.deposit') }}</dt>
        <dd class="mt-0.5 text-p-sm text-ink-gray-8">
          <MoneyDisplay :value="deposit?.deposit_required ?? null" :currency="reservation.currency" />
        </dd>
        <dd class="text-xs text-ink-gray-5">
          {{ t('page.reservation.deposit.received') }}:
          <MoneyDisplay :value="deposit?.deposit_received ?? null" :currency="reservation.currency" muted />
        </dd>
      </div>

      <div class="min-w-0">
        <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
          {{ t('page.reservation.header.booked_on') }}
        </dt>
        <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ formatDateTime(reservation.booked_on) || '—' }}</dd>
      </div>
    </dl>
  </div>
</template>

<script setup>
import { Badge, Button } from 'frappe-ui'
import { computed } from 'vue'

import PageHeader from '@/components/PageHeader.vue'
import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import { reservationStatusTheme } from '@/resources/reservations'
import { formatDate, formatDateTime } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The reservation's own allow-listed fields, exactly as the server sent them. */
  reservation: { type: Object, required: true },
  /** The deposit position. `null` only if the payload had none. */
  deposit: { type: Object, default: null },
  /** How many room lines carry an assigned room, counted by the page. */
  assignedRooms: { type: Number, default: 0 },
  /**
   * Whether the room lines hold different intervals. Decided by the page from the
   * lines the server sent; this component never compares dates itself.
   */
  linesDiffer: { type: Boolean, default: false },
  /** `[{ key, label, variant, theme, run }]`, already filtered by the page. */
  actions: { type: Array, default: () => [] },
  /** Which action is in flight, so its own button shows the spinner. */
  busy: { type: String, default: '' },
})

const emit = defineEmits(['open-tab'])

const occupancy = computed(() =>
  t('page.reservation.guests.occupancy_line', {
    adults: props.reservation.total_adults ?? 0,
    children: props.reservation.total_children ?? 0,
  }),
)
</script>
