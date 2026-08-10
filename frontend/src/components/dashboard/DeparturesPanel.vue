<!--
  The next few departures, ordered by what still has to happen: stays that are
  blocked first, then those clear to leave, then those already gone.

  The balance is the reason the desk looks at this list, so it is a column of
  its own rather than a detail. Whether a checkout may actually run is the
  checkout service's decision; this panel repeats the server's own blocker
  verdict and offers the screen that holds the lock.
-->
<template>
  <DashboardCard :title="t('page.dashboard.departures_panel')" :padded="false">
    <template #action>
      <RouterLink
        :to="{ name: 'Departures' }"
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

    <p v-else-if="!rows.length" class="px-5 pb-5 pt-1 text-p-sm text-ink-gray-5">
      {{ t('page.dashboard.departures_empty') }}
    </p>

    <div v-else class="overflow-x-auto">
      <table class="w-full text-p-sm">
        <thead class="border-y border-outline-gray-1 bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
          <tr>
            <th class="w-full px-5 py-2 text-start font-medium">{{ t('page.departures.guest') }}</th>
            <th class="px-3 py-2 text-start font-medium">{{ t('page.departures.room') }}</th>
            <th class="px-3 py-2 text-start font-medium">{{ t('page.departures.balance') }}</th>
            <th class="px-3 py-2 text-start font-medium">{{ t('page.reservations.status') }}</th>
            <th class="w-px whitespace-nowrap px-4 py-2 text-end font-medium">{{ t('common.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.key"
            class="border-b border-outline-gray-1 last:border-b-0 hover:bg-surface-gray-1"
          >
            <!-- The guest column absorbs the slack and truncates, so the
                 balance and the action never leave the card. -->
            <td class="w-full min-w-[6.5rem] max-w-0 px-5 py-2.5">
              <span class="flex items-center gap-1.5">
                <span class="truncate font-medium text-ink-gray-8" :title="row.guest_name">
                  {{ row.guest_name }}
                </span>
                <Badge
                  v-if="row.vip_status"
                  class="shrink-0"
                  :theme="vipStatusTheme(row.vip_status)"
                  variant="subtle"
                  :label="row.vip_status"
                />
              </span>
            </td>
            <td class="whitespace-nowrap px-3 py-2.5">
              <RouterLink
                :to="{ name: 'Stay', params: { id: row.stay } }"
                class="font-medium text-ink-blue-3 hover:underline"
              >
                {{ row.room_number }}
              </RouterLink>
            </td>
            <!--
              Split folios are counted, never summed into the primary balance:
              they settle separately, and one merged figure would send the desk
              to collect money against the wrong account.
            -->
            <td class="whitespace-nowrap px-3 py-2.5 tabular-nums">
              <span :class="row.balance > 0.005 ? 'font-medium text-ink-amber-3' : 'text-ink-gray-7'">
                {{ formatCurrency(row.balance, row.currency) }}
              </span>
              <span v-if="row.related_folios > 0" class="ms-1.5 text-xs text-ink-gray-5">
                {{ t('page.departures.split_folios', { count: row.related_folios }) }}
              </span>
            </td>
            <td class="whitespace-nowrap px-3 py-2.5">
              <Badge :theme="row.state.theme" variant="subtle" :label="row.state.label" />
            </td>
            <td class="whitespace-nowrap px-4 py-2.5 text-end">
              <Button
                v-if="row.is_checked_out"
                variant="subtle"
                size="sm"
                :label="t('page.departures.action.open_folio')"
                :disabled="!row.folio"
                @click="goToFolio(row)"
              />
              <Button
                v-else
                variant="solid"
                size="sm"
                :label="t('page.departures.action.checkout')"
                @click="goToCheckout(row)"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </DashboardCard>
</template>

<script setup>
import { Badge, Button, FeatherIcon, LoadingIndicator } from 'frappe-ui'
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import { vipStatusTheme } from '@/resources/guests'
import { formatCurrency } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The `rows` block of a departures board response. */
  departures: { type: Array, default: () => [] },
  limit: { type: Number, default: 5 },
  loading: { type: Boolean, default: false },
})

const router = useRouter()

/** Rank: what is blocked needs a person, what is ready needs a click. */
function rank(row) {
  if (row.is_checked_out) return 2
  return row.can_check_out ? 1 : 0
}

const rows = computed(() =>
  [...props.departures]
    .sort((a, b) => rank(a) - rank(b))
    .slice(0, props.limit)
    .map((row) => ({ ...row, state: state(row) })),
)

function state(row) {
  if (row.is_checked_out) return { theme: 'gray', label: t('page.departures.checked_out') }
  if (row.can_check_out) return { theme: 'green', label: t('page.departures.ready') }

  return { theme: 'orange', label: t('page.departures.blocked') }
}

function goToFolio(row) {
  if (row.folio) router.push({ name: 'Folio', params: { id: row.folio } })
}

function goToCheckout(row) {
  router.push({ name: 'Checkout', params: { stay: row.stay } })
}
</script>
