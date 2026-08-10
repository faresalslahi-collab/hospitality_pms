<!--
  The next few arrivals, as a working list rather than a report.

  Rows still to check in come first: the ones already in the hotel are done,
  and pushing them down is the difference between a panel the desk works from
  and one it scrolls past. The full board is one link away and stays the
  authority — this panel decides nothing and mutates nothing.
-->
<template>
  <DashboardCard :title="t('page.dashboard.arrivals_panel')" :padded="false">
    <template #action>
      <RouterLink
        :to="{ name: 'Arrivals' }"
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
      {{ t('page.dashboard.arrivals_empty') }}
    </p>

    <div v-else class="overflow-x-auto">
      <table class="w-full text-p-sm">
        <thead class="border-y border-outline-gray-1 bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
          <tr>
            <th class="w-full px-5 py-2 text-start font-medium">{{ t('page.arrivals.guest') }}</th>
            <th class="px-3 py-2 text-start font-medium">{{ t('page.arrivals.reservation') }}</th>
            <th class="px-3 py-2 text-start font-medium">{{ t('page.dashboard.assigned_room') }}</th>
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
            <!--
              `w-full max-w-0` makes the guest column the one that gives way:
              it takes whatever width is left and truncates, so however long a
              name or a reservation number turns out to be, the readiness badge
              and the action stay on the card. Those two are what the row exists
              for. The minimum keeps the name from collapsing to an ellipsis.
            -->
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
            <td class="px-3 py-2.5">
              <RouterLink
                :to="{ name: 'Reservation', params: { id: row.reservation } }"
                class="block max-w-[7rem] truncate font-medium text-ink-blue-3 hover:underline"
                :title="row.reservation"
              >
                {{ row.reservation }}
              </RouterLink>
            </td>
            <!--
              The room type sits under the room rather than in a column of its
              own: half a screen does not hold six columns without pushing the
              action off the card, and the room a guest is walking to is the
              question, with the type as its qualifier.
            -->
            <td class="whitespace-nowrap px-3 py-2.5">
              <span v-if="row.room_number" class="block font-medium text-ink-gray-8">{{ row.room_number }}</span>
              <span v-else class="block text-ink-gray-5">{{ t('page.arrivals.no_room_yet') }}</span>
              <span class="block max-w-[5.5rem] truncate text-xs text-ink-gray-5">
                {{ row.room_type_name || row.room_type }}
              </span>
            </td>
            <!--
              Readiness, not reservation status: what the desk is deciding at
              this row is whether the guest can be walked to a room now.
            -->
            <td class="whitespace-nowrap px-3 py-2.5">
              <Badge :theme="row.readiness.theme" variant="subtle" :label="row.readiness.label" />
            </td>
            <td class="whitespace-nowrap px-4 py-2.5 text-end">
              <Button
                v-if="!row.is_checked_in"
                variant="solid"
                size="sm"
                :label="t('page.arrivals.action.check_in')"
                @click="goToCheckIn(row)"
              />
              <Button
                v-else
                variant="subtle"
                size="sm"
                :label="t('page.dashboard.action.view_stay')"
                @click="goToStay(row)"
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
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The `rows` block of an arrivals board response. */
  arrivals: { type: Array, default: () => [] },
  limit: { type: Number, default: 5 },
  loading: { type: Boolean, default: false },
})

const router = useRouter()

const rows = computed(() => {
  const pending = props.arrivals.filter((row) => !row.is_checked_in)
  const done = props.arrivals.filter((row) => row.is_checked_in)

  return [...pending, ...done].slice(0, props.limit).map((row) => ({ ...row, readiness: readiness(row) }))
})

/**
 * How ready this arrival is, in the three states the desk acts on.
 *
 * Housekeeping is only one of the room's four dimensions; it is the one that
 * decides whether a guest can walk in, which is why it is the one summarised
 * here. The arrivals board keeps all four separate.
 */
function readiness(row) {
  if (row.is_checked_in) return { theme: 'green', label: t('page.arrivals.checked_in') }
  if (!row.assigned_room) return { theme: 'gray', label: t('page.dashboard.readiness_due') }
  if (row.room_ready) return { theme: 'green', label: t('page.dashboard.readiness_ready') }

  return { theme: 'red', label: t('page.dashboard.readiness_not_ready') }
}

function goToCheckIn(row) {
  router.push({ name: 'CheckIn', params: { reservation: row.reservation } })
}

function goToStay(row) {
  router.push({ name: 'Stay', params: { id: row.stay } })
}
</script>
