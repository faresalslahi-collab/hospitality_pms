<!--
  Guests: the association between this booking and the guest record. Nothing more.

  **This is not a Guest 360.** No stay history, no folio history, no documents, no
  preferences, no merge. Those belong to the guest profile, which authorises them
  on its own terms and is one link away. An aggregate screen that quietly grows a
  guest dossier is exactly how 16.7.1 came to hand out folio balances to ten roles
  whose DocType could not open them.

  What it shows: who the booking is for, how to reach them, how many people are
  expected, and — only if the server disclosed it — the guest's standing.

  `guest_standing` is absent from the payload for a caller who may not read Guest.
  Absence is a statement about the *reader*, not about the guest, so it is reported
  as "not shown to your role" and never as "no VIP status" or "not blacklisted".
  The blacklist flag is a second, narrower clearance (permlevel 2) and is absent
  again unless the caller holds it; where it is present and set, the fact is shown
  through AlertBadge, which has no prop and no slot that could carry a reason.
-->
<template>
  <div class="grid gap-5 lg:grid-cols-2">
    <section class="rounded border border-outline-gray-1">
      <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
        {{ t('page.reservation.guests.primary') }}
      </h2>

      <div class="space-y-3 p-4">
        <div class="flex flex-wrap items-center gap-2">
          <p class="font-medium text-ink-gray-9">{{ reservation.guest_name || reservation.guest || '—' }}</p>

          <!-- Standing, where the server disclosed it. -->
          <template v-if="standing">
            <Badge
              v-if="standing.vip_status"
              variant="subtle"
              :theme="vipStatusTheme(standing.vip_status)"
              :label="standing.vip_status"
            />
            <!--
              Presence, never content: this badge cannot render a reason. A cleared
              reader who sees nothing here has been told the guest is not flagged;
              an uncleared reader is shown the restricted line below instead.
            -->
            <AlertBadge
              v-if="blacklisted"
              present
              severity="high"
              :label="t('common.blacklisted')"
            />
          </template>
        </div>

        <dl class="grid grid-cols-2 gap-x-4 gap-y-3">
          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.guests.mobile') }}</dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ reservation.guest_mobile || '—' }}</dd>
          </div>

          <div v-if="standing" class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.guest_profile.guest_type') }}
            </dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ standing.guest_type || '—' }}</dd>
          </div>
        </dl>

        <!--
          Not a negative claim about the guest: the server withheld the section
          from this reader, and saying "no standing" would hand them a clearance
          it declined to give.
        -->
        <p v-if="!standing" class="text-p-sm text-ink-gray-6">
          {{ t('page.reservation.guests.standing_restricted') }}
        </p>

        <!-- The one door out of this tab. Everything else about the guest is there. -->
        <router-link
          v-if="reservation.guest"
          class="inline-flex text-p-sm text-ink-blue-3 hover:underline"
          :to="{ name: 'GuestProfile', params: { id: reservation.guest } }"
        >
          {{ t('page.reservation.guests.open_profile') }}
        </router-link>
      </div>
    </section>

    <section class="rounded border border-outline-gray-1">
      <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
        {{ t('page.reservation.guests.occupancy') }}
      </h2>

      <!--
        The booking's own totals. Not counted from the room lines: the header
        totals are the server's, and a filtered or partially loaded list of lines
        would understate how many people are expected.
      -->
      <div class="p-4">
        <p class="text-p-sm text-ink-gray-8">
          {{
            t('page.reservation.guests.occupancy_line', {
              adults: reservation.total_adults ?? 0,
              children: reservation.total_children ?? 0,
            })
          }}
        </p>
      </div>
    </section>
  </div>
</template>

<script setup>
import { Badge } from 'frappe-ui'
import { computed } from 'vue'

import AlertBadge from '@/components/operational/AlertBadge.vue'
import { hasField, vipStatusTheme } from '@/resources/guests'
import { t } from '@/utils/i18n'

const props = defineProps({
  reservation: { type: Object, required: true },
  /**
   * `guest_standing`, or `null` when the server sent no such key.
   *
   * `null` means "not disclosed to this reader" and is rendered as that. It is
   * never read as "the guest has no standing".
   */
  standing: { type: Object, default: null },
})

/**
 * Only a disclosed *and* set flag is a flag. `hasField` rather than truthiness,
 * because an absent key and `false` are different answers and only one of them is
 * about the guest.
 */
const blacklisted = computed(
  () => hasField(props.standing, 'is_blacklisted') && Boolean(props.standing.is_blacklisted),
)
</script>
