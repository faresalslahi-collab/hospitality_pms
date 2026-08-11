<!--
  A folio balance, presented the same way on every operational screen (16.7.0 UI kit).

  It displays; it never calculates. The amount arrives from a service — the
  departures board, the folio screen, the in-house list — and this component only
  decides how it reads. The three states are the server's arithmetic restated in
  words, not a new rule: zero is settled, positive is owed by the guest, negative
  is a credit the hotel holds. The threshold that separates them lives in
  `balanceTheme()` and is imported, never re-derived here, so a change to what
  counts as "settled" happens in one place.

  Deliberately NOT in this component: checkout eligibility. Whether a stay may
  depart is `can_check_out` from the server, which weighs blockers this component
  never sees (open authorisations, housekeeping, pending postings, split folios).
  A settled balance is not permission to leave, and a component that implied it
  would put the desk in front of a guest with the wrong answer.

  Colour never carries the state alone: the state word is rendered as text, and
  where the caller suppresses it the accessible name still says it.

  Three arrangements, one root element:

  - unknown  MoneyDisplay's placeholder and "Not available" label, with no badge
             and no state word — an amount that was never sent supports no claim.
  - md       a summary block: the state reads first, the amount is the larger element.
  - sm       a table cell: the amount sits in the themed badge, the state beside it.
-->
<template>
  <span :class="rootClass" :aria-label="accessibleName" :title="accessibleName">
    <MoneyDisplay v-if="!known" :value="balance" :currency="currency" muted :bold="size === 'md'" />

    <template v-else-if="size === 'md'">
      <Badge v-if="showLabel" :theme="theme" variant="subtle" size="sm" :label="stateLabel" />
      <MoneyDisplay :value="balance" :currency="currency" bold class="text-lg" />
    </template>

    <template v-else>
      <Badge :theme="theme" variant="subtle" size="sm">
        <MoneyDisplay :value="balance" :currency="currency" />
      </Badge>
      <span v-if="showLabel" class="text-xs text-ink-gray-5">{{ stateLabel }}</span>
    </template>
  </span>
</template>

<script setup>
import { Badge } from 'frappe-ui'
import { computed } from 'vue'

import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
// `balanceTheme` is a pure presentation helper: no request, no state, the same
// thresholds the departures board already renders with.
import { balanceTheme } from '@/resources/frontOffice'
import { formatCurrency } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The balance, as the server sent it. `null` means "not supplied". */
  balance: { type: [Number, String], default: null },
  /** ISO currency code from the row or the property. Never defaulted. */
  currency: { type: String, default: null },
  /** `sm` for a table cell, `md` for a summary block. */
  size: { type: String, default: 'sm' },
  /** Render the semantic state word. The accessible name carries it either way. */
  showLabel: { type: Boolean, default: true },
})

/**
 * Zero is a real balance and means settled; only null, undefined, an empty
 * string or a non-number mean "not supplied". The distinction matters: a settled
 * folio and a folio whose balance never arrived look nothing alike operationally.
 */
const known = computed(
  () =>
    props.balance !== null &&
    props.balance !== undefined &&
    props.balance !== '' &&
    !Number.isNaN(Number(props.balance)),
)

/** `settled` | `due` | `credit`, or null when there is no amount to speak about. */
const state = computed(() => {
  if (!known.value) return null

  const value = Number(props.balance)

  // Same threshold as balanceTheme: a rounding remainder is not a debt.
  if (Math.abs(value) <= 0.005) return 'settled'

  return value > 0 ? 'due' : 'credit'
})

const stateLabel = computed(() => (state.value ? t(`ui.folio_balance.${state.value}`) : ''))

/** Neutral until there is an amount: an unknown balance gets no state colour. */
const theme = computed(() => (known.value ? balanceTheme(props.balance) : 'gray'))

const rootClass = computed(() => {
  if (!known.value) return 'inline-flex items-center text-start'

  return props.size === 'md'
    ? 'inline-flex flex-col items-start gap-1 text-start'
    : 'inline-flex items-center gap-1.5 text-start'
})

/** State and amount together, for screen readers and the hover tooltip. */
const accessibleName = computed(() => {
  if (!known.value) return undefined

  return t('ui.folio_balance.state_amount', {
    state: stateLabel.value,
    amount: formatCurrency(props.balance, props.currency),
  })
})
</script>
