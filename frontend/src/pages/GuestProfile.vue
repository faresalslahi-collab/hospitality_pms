<!--
  Guest profile.

  Identification and blacklist status are permission-gated on the server: a
  user who cannot see them simply does not get the field back. `hasField`
  checks for that distinction so an unauthorised viewer sees nothing about
  the section at all, rather than a section that reads "none on file" as if
  the guest had no identification (Frontend Standards section 5).
-->
<template>
  <div>
    <LoadingState v-if="detail.loading && !detail.data" />
    <ErrorState v-else-if="detail.error" :error="detail.error" :on-retry="load" />

    <div v-else-if="guest">
      <PageHeader :title="guest.guest_name" :subtitle="guest.name">
        <template #actions>
          <Badge v-if="guest.vip_status" :theme="vipStatusTheme(guest.vip_status)" variant="subtle" :label="guest.vip_status" />
          <Badge
            v-if="hasField(guest, 'is_blacklisted')"
            :theme="guest.is_blacklisted ? 'red' : 'gray'"
            variant="subtle"
            :label="guest.is_blacklisted ? t('page.guest_profile.blacklisted') : t('page.guest_profile.not_blacklisted')"
          />
        </template>
      </PageHeader>

      <div class="grid gap-5 p-5 lg:grid-cols-3">
        <section class="space-y-4 lg:col-span-2">
          <div v-if="guest.alerts.length" class="rounded border border-outline-gray-1 p-4">
            <p class="mb-2 text-p-sm font-medium text-ink-gray-8">{{ t('page.guest_profile.alerts') }}</p>
            <div class="space-y-2">
              <div v-for="(alert, index) in guest.alerts" :key="index" class="flex items-start gap-2">
                <Badge :theme="alertSeverityTheme(alert.severity)" variant="subtle" :label="alert.alert_type" />
                <p class="text-p-sm text-ink-gray-7">{{ alert.alert }}</p>
              </div>
            </div>
          </div>

          <div v-if="hasField(guest, 'is_blacklisted') && guest.is_blacklisted" class="rounded border border-outline-red-1 bg-surface-red-1 p-4">
            <p class="font-medium text-ink-red-4">{{ t('page.guest_profile.blacklist_status') }}</p>
            <p v-if="hasField(guest, 'blacklist_reason') && guest.blacklist_reason" class="mt-1 text-p-sm text-ink-red-4">
              {{ t('page.guest_profile.blacklist_reason') }}: {{ guest.blacklist_reason }}
            </p>
          </div>

          <div class="rounded border border-outline-gray-1">
            <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
              {{ t('page.guest_profile.preferences') }}
            </h2>
            <EmptyState v-if="!guest.preferences.length" :message="t('page.guest_profile.no_preferences')" />
            <div v-else class="divide-y divide-outline-gray-1">
              <div v-for="(pref, index) in guest.preferences" :key="index" class="p-4">
                <p class="font-medium text-ink-gray-9">{{ pref.category }}</p>
                <p class="mt-0.5 text-p-sm text-ink-gray-7">{{ pref.preference }}</p>
                <p v-if="pref.notes" class="mt-0.5 text-p-sm text-ink-gray-5">{{ pref.notes }}</p>
              </div>
            </div>
          </div>

          <div v-if="hasField(guest, 'identifications')" class="rounded border border-outline-gray-1">
            <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
              {{ t('page.guest_profile.identification') }}
            </h2>
            <EmptyState v-if="!guest.identifications.length" :message="t('page.guest_profile.no_identifications')" />
            <div v-else class="divide-y divide-outline-gray-1">
              <div v-for="(id, index) in guest.identifications" :key="index" class="flex items-start justify-between gap-3 p-4">
                <div>
                  <p class="font-medium text-ink-gray-9">
                    {{ id.id_type }}
                    <Badge v-if="id.is_primary" class="ms-1" theme="blue" variant="subtle" :label="t('page.guest_profile.primary')" />
                  </p>
                  <p class="mt-0.5 text-p-sm text-ink-gray-6">
                    {{ id.id_number }} · {{ id.issuing_country || '—' }}
                  </p>
                  <p v-if="id.expiry_date" class="mt-0.5 text-p-sm text-ink-gray-5">
                    {{ t('page.guest_profile.expiry_date') }}: {{ formatDate(id.expiry_date) }}
                  </p>
                </div>
                <Badge
                  :theme="id.verified ? 'green' : 'gray'"
                  variant="subtle"
                  :label="id.verified ? t('page.guest_profile.verified') : t('page.guest_profile.unverified')"
                />
              </div>
            </div>
          </div>
        </section>

        <aside class="space-y-4">
          <dl class="space-y-3 rounded border border-outline-gray-1 p-4">
            <div v-for="item in summary" :key="item.label">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ item.label }}</dt>
              <dd class="mt-0.5 text-p-base text-ink-gray-8">{{ item.value }}</dd>
            </div>
          </dl>

          <dl class="space-y-3 rounded border border-outline-gray-1 p-4">
            <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.guest_profile.stay_history') }}</p>
            <div>
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.guest_profile.total_stays') }}</dt>
              <dd class="mt-0.5 text-p-base text-ink-gray-8">{{ guest.total_stays ?? 0 }}</dd>
            </div>
            <div>
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.guest_profile.total_nights') }}</dt>
              <dd class="mt-0.5 text-p-base text-ink-gray-8">{{ guest.total_nights ?? 0 }}</dd>
            </div>
            <div>
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.guest_profile.last_stay_on') }}</dt>
              <dd class="mt-0.5 text-p-base text-ink-gray-8">
                {{ guest.last_stay_on ? formatDate(guest.last_stay_on) : '—' }}
              </dd>
            </div>
          </dl>
        </aside>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge } from 'frappe-ui'
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { alertSeverityTheme, getGuestResource, hasField, vipStatusTheme } from '@/resources/guests'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const route = useRoute()

const detail = getGuestResource()

const guest = computed(() => detail.data || null)

const summary = computed(() => {
  const g = guest.value
  if (!g) return []

  return [
    { label: t('page.guest_profile.contact'), value: [g.email_id, g.mobile_no].filter(Boolean).join(' · ') || '—' },
    { label: t('page.guest_profile.nationality'), value: g.nationality || '—' },
    { label: t('page.guest_profile.preferred_language'), value: g.preferred_language || '—' },
    { label: t('page.guest_profile.guest_type'), value: g.guest_type || '—' },
    { label: t('page.guest_profile.date_of_birth'), value: g.date_of_birth ? formatDate(g.date_of_birth) : '—' },
    { label: t('page.guest_profile.dietary_requirements'), value: g.dietary_requirements || '—' },
    { label: t('page.guest_profile.allergies'), value: g.allergies || '—' },
    { label: t('page.guest_profile.accessibility_requirements'), value: g.accessibility_requirements || '—' },
  ]
})

function load() {
  return detail.fetch({ guest: route.params.id })
}

watch(() => route.params.id, load, { immediate: true })
</script>
