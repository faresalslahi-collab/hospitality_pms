<!--
  An amount of money, rendered the same way everywhere (16.7.0 UI kit).

  It displays; it never calculates. Every amount reaching this component was
  produced by a service on the server, and the currency always arrives with it —
  a bench may run several companies in different currencies, so a currency is
  read from the row or the property, never assumed.

  Formatting goes through `Intl` (utils/format), never string concatenation, so
  an Arabic session gets Arabic digits and the currency on the correct side
  without this component knowing which side that is.
-->
<template>
  <span
    class="whitespace-nowrap tabular-nums"
    :class="[muted ? 'text-ink-gray-5' : '', bold ? 'font-medium text-ink-gray-9' : '']"
    :aria-label="known ? undefined : t('ui.money.unknown')"
    :title="known ? undefined : t('ui.money.unknown')"
  >{{ text }}</span>
</template>

<script setup>
import { computed } from 'vue'

import { formatCurrency, formatNumber } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The amount, as the server sent it. `null` means "not supplied". */
  value: { type: [Number, String], default: null },
  /** ISO currency code from the row or the property. Never defaulted. */
  currency: { type: String, default: null },
  precision: { type: Number, default: 2 },
  /** Shown when there is no value. A dash alone is not accessible, so the
      unknown case also carries a text label for screen readers. */
  placeholder: { type: String, default: '—' },
  muted: { type: Boolean, default: false },
  bold: { type: Boolean, default: false },
})

/**
 * Zero is a real amount and must show as 0.00; only null, undefined and an
 * empty string mean "not supplied". A folio that is settled reads `0.00`, which
 * is operationally different from a folio whose balance was never sent.
 */
const known = computed(
  () => props.value !== null && props.value !== undefined && props.value !== '' && !Number.isNaN(Number(props.value)),
)

const text = computed(() => {
  if (!known.value) return props.placeholder

  return props.currency
    ? formatCurrency(props.value, props.currency, props.precision)
    : formatNumber(props.value, props.precision)
})
</script>
