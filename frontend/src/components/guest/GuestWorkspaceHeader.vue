<!--
  The Guest 360 header: who this is, and what may be done about them.

  Decides nothing and computes nothing. Every value is handed to it already
  resolved, and every action is a key the page turns into a call — so the one
  place that knows what a guest may have done to them is the page, not a header
  that happens to render a button.

  **The blacklist reason is not here, and cannot be.** Eleven roles may know a
  guest is blacklisted; six may know why, and no front-office role is among the
  six. The header shows a badge when the server disclosed the flag and nothing
  at all when it did not — `standing.is_blacklisted` arrives absent rather than
  `false` for an uncleared caller, so `hasField` is the test and truthiness would
  silently turn "not shown to you" into "not blacklisted".

  Alerts are a badge and a count, never their text: an allergy or a security note
  is sensitive, belongs on its own tab, and has no business being readable over a
  colleague's shoulder at the desk.
-->
<template>
  <div>
    <PageHeader :title="guestName" :subtitle="guestId">
      <template #actions>
        <Badge
          v-if="standing.vip_status"
          :theme="vipStatusTheme(standing.vip_status)"
          variant="subtle"
          :label="standing.vip_status"
        />

        <!-- Absent, not false: an uncleared caller is told nothing either way. -->
        <Badge
          v-if="hasField(standing, 'is_blacklisted') && standing.is_blacklisted"
          theme="red"
          variant="subtle"
          :label="t('page.guest_profile.blacklisted')"
        />

        <AlertBadge v-if="alertCount" :count="alertCount" />

        <Button
          v-for="action in actions"
          :key="action.key"
          :variant="action.variant || 'ghost'"
          :theme="action.theme"
          :loading="busy === action.key"
          @click="$emit('action', action.key)"
        >
          {{ action.label }}
        </Button>
      </template>
    </PageHeader>

    <dl
      class="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-outline-gray-1 px-5 pb-4 pt-3 sm:grid-cols-3 lg:grid-cols-6"
    >
      <div v-for="metric in metrics" :key="metric.key">
        <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ metric.label }}</dt>
        <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ metric.value }}</dd>
      </div>
    </dl>
  </div>
</template>

<script setup>
import { Badge, Button } from 'frappe-ui'
import { computed } from 'vue'

import PageHeader from '@/components/PageHeader.vue'
import AlertBadge from '@/components/operational/AlertBadge.vue'
import { hasField, vipStatusTheme } from '@/resources/guests'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  guestName: { type: String, default: '' },
  guestId: { type: String, default: '' },
  /** `standing` from the workspace payload. Keys may legitimately be absent. */
  standing: { type: Object, default: () => ({}) },
  /** Count only. The alert text stays on the Alerts tab. */
  alertCount: { type: Number, default: 0 },
  /**
   * `stay_statistics` when the caller may read Stay, otherwise null.
   *
   * Derived server-side from Stay rather than read from `Guest.total_stays`,
   * which nothing in the app writes and which the old profile rendered as a
   * confident zero.
   */
  statistics: { type: Object, default: null },
  /** The in-house stay, `null` when there is none, absent when undisclosed. */
  currentStay: { type: Object, default: null },
  /** Whether the caller was cleared for Stay at all. */
  mayReadStay: { type: Boolean, default: false },
  actions: { type: Array, default: () => [] },
  busy: { type: String, default: '' },
})

defineEmits(['action'])

/**
 * The metric strip, built only from what the caller was actually given.
 *
 * A metric whose source is undisclosed is omitted rather than shown as a dash:
 * six columns with three of them empty invites the reader to conclude the guest
 * has never stayed, which is the inference the omission exists to prevent.
 */
const metrics = computed(() => {
  const list = [
    { key: 'guest_type', label: t('page.guest_profile.guest_type'), value: props.standing.guest_type || '—' },
  ]

  if (props.statistics) {
    list.push(
      {
        key: 'total_stays',
        label: t('page.guest_profile.total_stays'),
        value: String(props.statistics.total_stays ?? 0),
      },
      {
        key: 'total_nights',
        label: t('page.guest_profile.total_nights'),
        value: String(props.statistics.total_nights ?? 0),
      },
      {
        key: 'last_stay_on',
        label: t('page.guest_profile.last_stay_on'),
        value: props.statistics.last_stay_on ? formatDate(props.statistics.last_stay_on) : '—',
      },
    )
  }

  if (props.mayReadStay) {
    list.push({
      key: 'current_room',
      label: t('page.guest_profile.current_room'),
      // The room the guest is actually in. Since 16.7.3 the inventory row names
      // the same one, because a cross-type move carries the type with it.
      value: props.currentStay?.room || t('page.guest_profile.no_current_stay'),
    })
  }

  return list
})
</script>
