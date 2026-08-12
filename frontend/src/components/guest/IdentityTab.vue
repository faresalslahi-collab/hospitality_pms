<!--
  Identity: passport and ID documents, at Guest permlevel 1.

  The whole point of this tab is the distinction it draws. `identifications`
  arrives as an **absent key** for a caller without permlevel 1 — Reservation
  Agent is the concrete role on this product — and as a possibly-empty array for
  one with it. So:

    absent  -> "not shown to your role"
    []      -> "no documents on file"

  Rendering the first as the second would tell a reservation agent that a guest
  who handed over a passport at check-in has no papers, and would hide from
  review the fact that a permission boundary was crossed. `hasField` is therefore
  the test here, never `.length` and never truthiness.

  **No document image.** `id_image` is deliberately not published by the server:
  Frappe authorises a file download against the document it is attached to, at
  permlevel 0, so the URL would be a wider grant than the permlevel-1 row that
  carries it. Recorded in 16.7.3 as DEFERRED — DOCUMENT SECURITY DESIGN. Do not
  add an image column here expecting the server to fill it.
-->
<template>
  <div>
    <PermissionDenied
      v-if="!disclosed"
      :message="t('page.guest_profile.restricted_identity')"
    />

    <EmptyState
      v-else-if="!identifications.length"
      :message="t('page.guest_profile.no_identifications')"
    />

    <OperationalDataTable
      v-else
      :columns="columns"
      :rows="rows"
      row-key="name"
      :aria-label="t('page.guest_profile.tab.identity')"
      dense
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'

import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import PermissionDenied from '@/components/states/PermissionDenied.vue'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The rows, or `null` when the server withheld the block entirely. */
  identifications: { type: Array, default: () => [] },
  /** Whether the server disclosed the block at all (permlevel 1). */
  disclosed: { type: Boolean, default: false },
})

const columns = computed(() => [
  { key: 'id_type', label: t('page.guest_profile.id_type'), primary: true },
  { key: 'id_number', label: t('page.guest_profile.id_number') },
  { key: 'issuing_country', label: t('page.guest_profile.issuing_country') },
  { key: 'issue_date', label: t('page.guest_profile.issue_date'), nowrap: true },
  { key: 'expiry_date', label: t('page.guest_profile.expiry_date'), nowrap: true },
  { key: 'verified', label: t('page.guest_profile.verified') },
])

/** Every cell a string, so the phone card view reads the same as the table. */
const rows = computed(() =>
  (props.identifications || []).map((row) => ({
    name: row.name,
    id_type: row.is_primary
      ? `${row.id_type} · ${t('page.guest_profile.primary')}`
      : row.id_type || '',
    id_number: row.id_number || '',
    issuing_country: row.issuing_country || '',
    issue_date: row.issue_date ? formatDate(row.issue_date) : '',
    expiry_date: row.expiry_date ? formatDate(row.expiry_date) : '',
    verified: t(row.verified ? 'page.guest_profile.verified' : 'page.guest_profile.unverified'),
  })),
)
</script>
