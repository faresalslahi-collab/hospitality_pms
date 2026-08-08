<!--
  Guest search.

  Identification numbers are deliberately not searchable here (the server
  reserves that for `find_matches`, gated on a higher permission level); this
  screen only searches name, email and mobile, matching what the server will
  actually accept (guests.search_guests).
-->
<template>
  <div>
    <PageHeader :title="t('page.guests.title')" :subtitle="t('page.guests.subtitle')" />

    <div class="space-y-4 p-5">
      <FormControl
        v-model="query"
        type="text"
        :placeholder="t('page.guests.search_hint')"
        @keyup.enter="run"
      >
        <template #suffix>
          <Button variant="ghost" @click="run">
            <FeatherIcon name="search" class="size-4" />
          </Button>
        </template>
      </FormControl>

      <LoadingState v-if="search.loading && !search.data" />
      <ErrorState v-else-if="search.error" :error="search.error" :on-retry="run" />
      <EmptyState v-else-if="search.data && !guests.length" :message="t('page.guests.empty')" />

      <div v-else-if="guests.length" class="overflow-x-auto rounded border border-outline-gray-1">
        <table class="w-full min-w-max text-p-sm">
          <thead class="bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
            <tr>
              <th class="p-2 text-start">{{ t('page.guests.name') }}</th>
              <th class="p-2 text-start">{{ t('page.guests.email') }}</th>
              <th class="p-2 text-start">{{ t('page.guests.mobile') }}</th>
              <th class="p-2 text-start">{{ t('page.guests.nationality') }}</th>
              <th class="p-2 text-start">{{ t('page.guests.vip') }}</th>
              <th class="p-2 text-start">{{ t('page.guests.total_stays') }}</th>
              <th class="p-2 text-start">{{ t('page.guests.last_stay') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in guests"
              :key="row.name"
              class="cursor-pointer border-t border-outline-gray-1 hover:bg-surface-gray-1"
              @click="router.push({ name: 'GuestProfile', params: { id: row.name } })"
            >
              <td class="p-2 font-medium text-ink-gray-9">
                {{ row.guest_name }}
                <Badge v-if="row.vip_status" class="ms-1" :theme="vipStatusTheme(row.vip_status)" variant="subtle" :label="row.vip_status" />
              </td>
              <td class="p-2">{{ row.email_id || '—' }}</td>
              <td class="p-2">{{ row.mobile_no || '—' }}</td>
              <td class="p-2">{{ row.nationality || '—' }}</td>
              <td class="p-2">{{ row.guest_type || '—' }}</td>
              <td class="p-2">{{ row.total_stays ?? 0 }}</td>
              <td class="p-2 whitespace-nowrap">{{ row.last_stay_on ? formatDate(row.last_stay_on) : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { searchGuestsResource, vipStatusTheme } from '@/resources/guests'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const router = useRouter()
const search = searchGuestsResource()

const query = ref('')

const guests = computed(() => search.data || [])

function run() {
  search.fetch({ query: query.value.trim() || undefined, limit: 50 })
}

run()
</script>
