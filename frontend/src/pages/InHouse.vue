<template>
  <div>
    <PageHeader :title="t('page.in_house.title')" :subtitle="property.active.value?.property_name || ''">
      <template #actions>
        <Button variant="subtle" :loading="board.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <LoadingState v-if="board.loading && !board.data" />
    <ErrorState v-else-if="board.error" :error="board.error" :on-retry="reload" />
    <EmptyState v-else-if="!stays.length" :message="t('page.in_house.empty')" />

    <div v-else class="space-y-4 p-5">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div v-for="tile in tiles" :key="tile.key" class="rounded border border-outline-gray-1 px-3 py-2">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold text-ink-gray-9">{{ tile.value }}</p>
        </div>
      </div>

      <div class="overflow-x-auto rounded border border-outline-gray-1">
        <table class="w-full min-w-max text-p-sm">
          <thead class="bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
            <tr>
              <th class="p-2 text-start">{{ t('page.in_house.room') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.guest') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.arrival') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.departure') }}</th>
              <th class="p-2 text-start">{{ t('page.in_house.pax') }}</th>
              <th class="p-2 text-start">{{ t('page.reservations.status') }}</th>
              <th class="p-2 text-end">{{ t('page.in_house.rate') }}</th>
              <th class="p-2 text-end">{{ t('page.in_house.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in stays" :key="row.name" class="border-t border-outline-gray-1">
              <td class="p-2 font-medium text-ink-gray-9">{{ row.room }}</td>
              <td class="p-2">{{ row.guest_name }}</td>
              <td class="p-2 whitespace-nowrap">{{ formatDate(row.arrival_date) }}</td>
              <td class="p-2 whitespace-nowrap">{{ formatDate(row.departure_date) }}</td>
              <td class="p-2">{{ row.adults }}A {{ row.children }}C</td>
              <td class="p-2">
                <Badge
                  :theme="row.stay_status === 'Due Out' ? 'orange' : 'green'"
                  variant="subtle"
                  :label="row.stay_status"
                />
              </td>
              <td class="p-2 text-end whitespace-nowrap">
                {{ formatCurrency(row.room_rate, property.currency.value) }}
              </td>
              <td class="p-2 text-end whitespace-nowrap">
                <RouterLink
                  v-if="row.folio"
                  :to="{ name: 'Folio', params: { id: row.folio } }"
                  class="text-ink-blue-3 hover:underline"
                >
                  {{ t('page.in_house.folio') }}
                </RouterLink>
                <RouterLink
                  :to="{ name: 'Checkout', params: { stay: row.name } }"
                  class="ms-3 text-ink-blue-3 hover:underline"
                >
                  {{ t('page.in_house.checkout') }}
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon } from 'frappe-ui'
import { computed, watch } from 'vue'
import { RouterLink } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { apiResource } from '@/resources'
import { property } from '@/stores/property'
import { formatCurrency, formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const board = apiResource('stays.in_house', { method: 'GET' })

const stays = computed(() => board.data?.stays || [])

const tiles = computed(() => {
  const s = board.data?.summary || {}

  return [
    { key: 'in_house', label: t('page.in_house.in_house'), value: s.in_house ?? 0 },
    { key: 'due_out', label: t('page.in_house.due_out'), value: s.due_out ?? 0 },
    { key: 'adults', label: t('page.availability.adults'), value: s.adults ?? 0 },
    { key: 'children', label: t('page.availability.children'), value: s.children ?? 0 },
  ]
})

function reload() {
  board.fetch({ property: property.activeName.value })
}

watch(() => property.activeName.value, reload, { immediate: true })
</script>
