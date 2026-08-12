<!--
  Alerts: what the desk must know before it speaks to this guest.

  Only active alerts reach this component — the server filters `is_active` — so
  an empty list means nothing is outstanding, not that alerts were withheld.
  `Guest Alert` is permlevel 0, which here means "unprivileged among Guest
  readers" and emphatically not "public": the endpoint is gated on Guest read and
  ten roles that can open a stay board never see any of this.

  Alert text can be medical, behavioural or security-related, which is why it
  lives on a tab a person chooses to open rather than in the header. The header
  carries a badge and a count and nothing else.

  **The blacklist is not an alert and is not shown here.** It is permlevel 2, its
  reason is permlevel 3, and both are answered on the header from `standing`,
  where the absent-key rule applies. Folding it into this list would put a
  narrower disclosure inside a wider one.
-->
<template>
  <div>
    <EmptyState v-if="!alerts.length" :message="t('page.guest_profile.no_alerts')" />

    <ul v-else class="space-y-3">
      <li
        v-for="alert in alerts"
        :key="alert.name"
        class="rounded border border-outline-gray-1 p-3"
      >
        <div class="flex flex-wrap items-center gap-2">
          <Badge
            :theme="alertSeverityTheme(alert.severity)"
            variant="subtle"
            :label="alert.severity"
          />
          <span class="text-p-sm font-medium text-ink-gray-8">{{ alert.alert_type }}</span>

          <span v-if="alert.valid_upto" class="text-xs text-ink-gray-5">
            {{ t('page.guest_profile.alert_valid_upto') }}: {{ formatDate(alert.valid_upto) }}
          </span>
        </div>

        <p class="mt-2 whitespace-pre-line text-p-sm text-ink-gray-7">{{ alert.alert }}</p>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { Badge } from 'frappe-ui'

import EmptyState from '@/components/states/EmptyState.vue'
import { alertSeverityTheme } from '@/resources/guests'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

defineProps({
  /** Active alerts only; the server has already filtered them. */
  alerts: { type: Array, default: () => [] },
})
</script>
