<!--
  Folios: this guest's account history. The most permission-sensitive tab here.

  Ten roles hold `Reservation.read` and `Stay.read` without `Guest Folio.read` —
  Revenue Manager, the housekeeping and maintenance roles, the kitchen roles and
  Corporate Sales Manager among them. 16.7.1 shipped a board that handed every
  one of them a balance, which is the defect this whole workspace is shaped
  around. So the page does not render this tab unless the server said
  `disclosure.folio`, and the endpoint refuses the call independently.

  **Read-only operational context.** No refund, no ERP posting, no
  reconciliation, no gateway action, no corporate settlement — 16.7.5 owns the
  financial actions, and none of them belongs behind a guest lookup. Posting
  state is not shown either: it lives on `Financial Posting Log`, which has its
  own narrower reader set, and surfacing it under a folio read would be the same
  mistake one layer down.

  Money goes through `MoneyDisplay` with the folio's own currency. A guest who
  stayed in two properties can hold folios in two currencies, so the currency is
  taken per row and never assumed from the first one.
-->
<template>
  <OperationalDataTable
    :columns="columns"
    :rows="rows"
    row-key="name"
    :loading="loading"
    :error="error"
    :page="page"
    :page-length="pageLength"
    :empty-message="t('page.guest_profile.no_folios')"
    :aria-label="t('page.guest_profile.tab.folios')"
    dense
    @page-change="$emit('page-change', $event)"
  >
    <template #cell:balance="{ row }">
      <FolioBalance :balance="row.balanceValue" :currency="row.currency" size="sm" />
    </template>

    <template #error="{ error: rowError, details }">
      <PermissionDenied v-if="details.kind === 'permission'" :message="details.message" />
      <ErrorState v-else :error="rowError" :on-retry="onRetry" />
    </template>
  </OperationalDataTable>
</template>

<script setup>
import { computed } from 'vue'

import FolioBalance from '@/components/operational/FolioBalance.vue'
import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import PermissionDenied from '@/components/states/PermissionDenied.vue'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  folios: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: [Object, String], default: null },
  page: { type: Number, default: 1 },
  pageLength: { type: Number, default: 20 },
})

const emit = defineEmits(['page-change', 'retry'])

const columns = computed(() => [
  { key: 'name', label: t('page.guest_profile.folio'), primary: true },
  { key: 'property', label: t('page.guest_profile.property'), hideBelow: 'md' },
  { key: 'stay', label: t('page.guest_profile.stay'), hideBelow: 'lg' },
  { key: 'folio_status', label: t('page.guest_profile.status') },
  {
    key: 'total_charges',
    label: t('page.guest_profile.charges'),
    type: 'money',
    currencyField: 'currency',
    align: 'end',
  },
  {
    key: 'total_payments',
    label: t('page.guest_profile.payments'),
    type: 'money',
    currencyField: 'currency',
    align: 'end',
  },
  { key: 'balance', label: t('page.guest_profile.balance'), align: 'end' },
  { key: 'opened_on', label: t('page.guest_profile.checked_in'), hideBelow: 'lg', nowrap: true },
])

/**
 * `balanceValue` is kept numeric alongside the formatted cells because the
 * balance is rendered by `FolioBalance`, which states settled/owed/credit in
 * words rather than by colour alone.
 */
const rows = computed(() =>
  (props.folios || []).map((row) => ({
    name: row.name,
    property: row.property || '',
    stay: row.stay || '',
    folio_status: row.folio_status || '',
    currency: row.currency || '',
    total_charges: row.total_charges,
    total_payments: row.total_payments,
    balanceValue: row.balance,
    opened_on: row.opened_on ? formatDate(row.opened_on) : '',
  })),
)

function onRetry() {
  emit('retry')
}
</script>
