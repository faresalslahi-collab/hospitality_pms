<!--
  Preferences: what this guest has asked for before.

  `Guest Preference` is a child table at permlevel 0, so it travels with Guest
  read and there is no disclosure question on this tab — an empty list genuinely
  means no preferences on file.

  The rows are rendered exactly as they are stored. Free text is not parsed into
  structure and a category is not inferred from a note: the schema already models
  `preference_category`, and inventing a second, softer classification here would
  put a guess in front of an agent as though the guest had said it.
-->
<template>
  <div>
    <EmptyState v-if="!preferences.length" :message="t('page.guest_profile.no_preferences')" />

    <OperationalDataTable
      v-else
      :columns="columns"
      :rows="rows"
      row-key="name"
      :aria-label="t('page.guest_profile.tab.preferences')"
      dense
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'

import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import { t } from '@/utils/i18n'

const props = defineProps({
  preferences: { type: Array, default: () => [] },
})

const columns = computed(() => [
  {
    key: 'preference_category',
    label: t('page.guest_profile.preference_category'),
    primary: true,
  },
  { key: 'preference', label: t('page.guest_profile.preference') },
  { key: 'notes', label: t('page.guest_profile.preference_notes') },
])

const rows = computed(() =>
  (props.preferences || []).map((row) => ({
    name: row.name,
    preference_category: row.preference_category || '',
    preference: row.preference || '',
    notes: row.notes || '',
  })),
)
</script>
