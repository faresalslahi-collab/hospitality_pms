<template>
  <div>
    <PageHeader :title="t('page.reservations.title')" :subtitle="t('page.reservations.subtitle')">
      <template #actions>
        <Button variant="subtle" :loading="list.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <div class="space-y-4 p-5">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FormControl
          v-model="filters.search"
          type="text"
          :label="t('common.search')"
          :placeholder="t('page.reservations.search_hint')"
          @keyup.enter="reload"
        />
        <FormControl
          v-model="filters.status"
          type="select"
          :label="t('page.reservations.status')"
          :options="statusOptions"
          @change="reload"
        />
        <FormControl v-model="filters.from_date" type="date" :label="t('page.reservations.from')" />
        <FormControl v-model="filters.to_date" type="date" :label="t('page.reservations.to')" />
      </div>

      <LoadingState v-if="list.loading && !list.data" />

      <ErrorState v-else-if="list.error" :error="list.error" :on-retry="reload" />

      <EmptyState v-else-if="!reservations.length" :message="t('page.reservations.empty')" />

      <div v-else class="overflow-x-auto rounded border border-outline-gray-1">
        <table class="w-full min-w-max text-p-sm">
          <thead class="bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
            <tr>
              <th class="p-2 text-start">{{ t('page.reservations.reference') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.guest') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.arrival') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.departure') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.nights') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.rooms') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.status') }}</th>
              <th class="p-2 text-end">{{ t('page.reservations.total') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in reservations"
              :key="row.name"
              class="cursor-pointer border-t border-outline-gray-1 hover:bg-surface-gray-1"
              @click="router.push({ name: 'Reservation', params: { id: row.name } })"
            >
              <td class="p-2 font-medium text-ink-gray-9">{{ row.name }}</td>
              <td class="p-2">{{ row.guest_name || '—' }}</td>
              <td class="p-2 whitespace-nowrap">{{ formatDate(row.arrival_date) }}</td>
              <td class="p-2 whitespace-nowrap">{{ formatDate(row.departure_date) }}</td>
              <td class="p-2">{{ row.nights }}</td>
              <td class="p-2">{{ row.total_rooms }}</td>
              <td class="p-2">
                <Badge
                  :theme="reservationStatusTheme(row.reservation_status)"
                  variant="subtle"
                  :label="row.reservation_status"
                />
              </td>
              <td class="p-2 text-end whitespace-nowrap">
                {{ formatCurrency(row.total_amount, row.currency) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { reservationListResource, reservationStatusTheme } from '@/resources/reservations'
import { property } from '@/stores/property'
import { formatCurrency, formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const router = useRouter()
const list = reservationListResource()

const filters = reactive({ search: '', status: '', from_date: '', to_date: '' })

const statusOptions = [
  { label: t('page.reservations.all_statuses'), value: '' },
  ...['Draft', 'Tentative', 'Confirmed', 'Guaranteed', 'Waitlisted', 'Checked In', 'Checked Out', 'Cancelled', 'No Show'].map(
    (value) => ({ label: value, value }),
  ),
]

const reservations = computed(() => list.data?.reservations || [])

function reload() {
  list.fetch({
    property: property.activeName.value,
    search: filters.search || undefined,
    status: filters.status || undefined,
    from_date: filters.from_date || undefined,
    to_date: filters.to_date || undefined,
  })
}

watch(() => property.activeName.value, reload, { immediate: true })
</script>
