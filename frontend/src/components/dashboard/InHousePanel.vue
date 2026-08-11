<!--
  The guests in the house who still owe the hotel money, most owed first.

  Not a sample of the house. "The top five in-house guests" is not a question
  anyone at a counter asks — the five rooms happen to sort first, and nothing
  follows from reading them. Money still to collect is work: it is what the desk
  chases before a departure, what a duty manager asks about, and it comes
  straight from the folio service's own balance on the enriched in-house payload.

  A credit balance is deliberately not here. The hotel owing a guest money is
  settled at checkout by the folio screen, not collected at the counter, and
  mixing the two directions into one queue would put refunds in a collection
  list. The whole house stays one link away on the in-house board.

  This panel decides nothing, mutates nothing and computes no balance: the row's
  own figure and the row's own currency, rendered as they arrived.
-->
<template>
  <DashboardCard
    :title="t('page.dashboard.in_house_panel')"
    :subtitle="t('page.dashboard.outstanding_balance')"
    :padded="false"
  >
    <template #action>
      <!-- The two counters the desk reads with this list: how full the house is,
           and how much of it leaves today. -->
      <span class="flex items-center gap-1.5 whitespace-nowrap text-xs text-ink-gray-6">
        {{ t('page.in_house.in_house') }}
        <span class="font-semibold tabular-nums text-ink-gray-8">{{ inHouseRooms }}</span>
      </span>
      <span class="flex items-center gap-1.5 whitespace-nowrap text-xs text-ink-gray-6">
        {{ t('page.in_house.due_out') }}
        <span class="font-semibold tabular-nums text-ink-gray-8">{{ dueOut }}</span>
      </span>
      <RouterLink
        :to="{ name: 'InHouse' }"
        class="flex items-center gap-1 text-p-sm font-medium text-ink-blue-3 hover:underline"
      >
        {{ t('page.dashboard.view_all') }}
        <FeatherIcon name="chevron-right" class="size-3.5 flip-rtl" aria-hidden="true" />
      </RouterLink>
    </template>

    <p v-if="loading" class="flex items-center gap-2 px-5 pb-5 pt-1 text-p-sm text-ink-gray-5">
      <LoadingIndicator class="size-4" />
      {{ t('common.loading') }}
    </p>

    <!--
      Two different empty days, said as two different things: an empty house, and
      a full house with nothing left to collect. One line for each, because
      "no guests are in house" printed over twenty occupied rooms would be a lie
      the desk could act on.
    -->
    <p v-else-if="!rows.length" class="px-5 pb-5 pt-1 text-p-sm text-ink-gray-5">
      {{ stays.length ? t('page.in_house.filter_empty') : t('page.dashboard.in_house_empty') }}
    </p>

    <div v-else>
      <div class="overflow-x-auto">
        <table class="w-full text-p-sm">
          <thead class="border-y border-outline-gray-1 bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
            <tr>
              <th class="px-5 py-2 text-start font-medium">{{ t('page.in_house.room') }}</th>
              <th class="w-full px-3 py-2 text-start font-medium">{{ t('page.arrivals.guest') }}</th>
              <th class="whitespace-nowrap px-4 py-2 text-end font-medium">{{ t('page.in_house.balance') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.key"
              class="border-b border-outline-gray-1 last:border-b-0 hover:bg-surface-gray-1"
            >
              <td class="whitespace-nowrap px-5 py-2.5">
                <RouterLink
                  :to="{ name: 'Stay', params: { id: row.stay } }"
                  class="font-medium tabular-nums text-ink-blue-3 hover:underline"
                >
                  {{ row.room_number }}
                </RouterLink>
              </td>
              <!-- The guest column gives way and truncates, so the amount never
                   leaves the card: the amount is what the row exists for. -->
              <td class="w-full min-w-[6.5rem] max-w-0 px-3 py-2.5">
                <span class="flex items-center gap-1.5">
                  <span class="truncate text-ink-gray-8" :title="row.guest_name">{{ row.guest_name }}</span>
                  <Badge
                    v-if="row.vip_status"
                    class="shrink-0"
                    :theme="vipStatusTheme(row.vip_status)"
                    variant="subtle"
                    :label="row.vip_status"
                  />
                  <!-- Presence and grade only. The alert text stays behind the
                       guest endpoints that authorise reading it. -->
                  <AlertBadge
                    v-if="row.alert_count > 0"
                    class="shrink-0"
                    :count="row.alert_count"
                    :severity="row.alert_grade"
                  />
                </span>
              </td>
              <td class="whitespace-nowrap px-4 py-2.5 text-end">
                <FolioBalance :balance="row.balance" :currency="row.currency" :show-label="false" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="total > rows.length" class="px-5 pb-4 pt-2.5 text-xs text-ink-gray-5">
        {{ t('page.dashboard.showing_first', { count: rows.length, total }) }}
      </p>
    </div>
  </DashboardCard>
</template>

<script setup>
import { Badge, FeatherIcon, LoadingIndicator } from 'frappe-ui'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import AlertBadge from '@/components/operational/AlertBadge.vue'
import FolioBalance from '@/components/operational/FolioBalance.vue'
import { vipStatusTheme } from '@/resources/guests'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The `stays` block of an in-house board response. */
  stays: { type: Array, default: () => [] },
  /** The dashboard's own room counts, so the panel restates and never derives. */
  inHouseRooms: { type: Number, default: 0 },
  dueOut: { type: Number, default: 0 },
  limit: { type: Number, default: 5 },
  loading: { type: Boolean, default: false },
})

/**
 * The server's severity word in the grade vocabulary `AlertBadge` renders.
 *
 * Presentation only, and the same colour semantics `guests.ALERT_SEVERITY_THEME`
 * already uses for these three values. An ungraded alert stays ungraded: this
 * panel does not invent urgency the server did not send.
 */
const ALERT_GRADE = {
  Critical: 'high',
  Warning: 'medium',
  Info: 'low',
}

/**
 * Guests with money still to collect, most owed first.
 *
 * `?? 0` throughout: a payload without `balance` degrades to a row with nothing
 * to collect and drops out of the queue, rather than throwing a whole dashboard
 * away over one missing field. The threshold is the folio service's own — a
 * rounding remainder is not a debt.
 */
const owing = computed(() =>
  props.stays
    .filter((row) => Number(row.balance ?? 0) > 0.005)
    .map((row) => ({
      key: row.key || row.name || row.stay,
      stay: row.stay || row.name,
      room_number: row.room_number || row.room || '',
      guest_name: row.guest_name || '',
      vip_status: row.vip_status || '',
      alert_count: Number(row.alert_count ?? 0),
      alert_grade: ALERT_GRADE[row.alert_severity] || '',
      balance: Number(row.balance ?? 0),
      // The row's currency, never the property's: a bench may run several, and
      // relabelling one currency as another is how a folio gets paid in the wrong
      // money.
      currency: row.currency || '',
    }))
    .sort((a, b) => b.balance - a.balance),
)

const total = computed(() => owing.value.length)

const rows = computed(() => owing.value.slice(0, props.limit))
</script>
