<template>
  <div>
    <PageHeader :title="t('page.availability.title')" :subtitle="t('page.availability.subtitle')" />

    <div class="p-5">
      <form
        class="grid gap-3 rounded border border-outline-gray-1 p-4 sm:grid-cols-2 lg:grid-cols-5"
        @submit.prevent="run"
      >
        <FormControl v-model="form.arrival" type="date" :label="t('page.availability.arrival')" />
        <FormControl v-model="form.departure" type="date" :label="t('page.availability.departure')" />
        <FormControl v-model.number="form.rooms" type="number" min="1" :label="t('page.availability.rooms')" />
        <FormControl v-model.number="form.adults" type="number" min="1" :label="t('page.availability.adults')" />
        <FormControl
          v-model.number="form.children"
          type="number"
          min="0"
          :label="t('page.availability.children')"
        />

        <div class="sm:col-span-2 lg:col-span-5">
          <Button variant="solid" :loading="search.loading" @click="run">
            {{ t('common.search') }}
          </Button>
        </div>
      </form>

      <ErrorState v-if="search.error" class="mt-4" :error="search.error" :on-retry="run" />

      <EmptyState
        v-else-if="search.data && !results.length"
        class="mt-4"
        :message="t('page.availability.none')"
      />

      <div v-else-if="results.length" class="mt-5 space-y-3">
        <p class="text-p-sm text-ink-gray-6">
          {{ t('page.availability.nights', { count: search.data.nights.length }) }}
        </p>

        <div
          v-for="row in results"
          :key="row.name"
          class="rounded border p-4"
          :class="row.bookable ? 'border-outline-gray-2' : 'border-outline-gray-1 opacity-70'"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="font-medium text-ink-gray-9">{{ row.room_type_name || row.name }}</p>
              <p class="mt-0.5 text-p-sm text-ink-gray-6">
                {{ t('page.availability.occupancy_line', { adults: row.max_adults, children: row.max_children }) }}
              </p>
            </div>

            <div class="text-end">
              <p class="text-lg font-semibold" :class="row.bookable ? 'text-ink-green-3' : 'text-ink-red-3'">
                {{ row.min_available }}
              </p>
              <p class="text-xs text-ink-gray-5">{{ t('page.availability.min_available') }}</p>
            </div>
          </div>

          <p v-if="!row.fits_occupancy" class="mt-2 text-p-sm text-ink-amber-4">
            {{ t('page.availability.does_not_fit') }}
          </p>

          <!-- Per-night detail: the desk needs to see which night is the constraint. -->
          <div class="mt-3 overflow-x-auto">
            <table class="w-full min-w-max text-p-sm">
              <thead>
                <tr class="text-start text-xs uppercase tracking-wide text-ink-gray-5">
                  <th class="py-1 pe-3 text-start">{{ t('page.availability.night') }}</th>
                  <th class="py-1 pe-3 text-start">{{ t('page.availability.sellable') }}</th>
                  <th class="py-1 pe-3 text-start">{{ t('page.availability.blocked') }}</th>
                  <th class="py-1 pe-3 text-start">{{ t('page.availability.sold') }}</th>
                  <th class="py-1 text-start">{{ t('page.availability.available') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(figures, night) in row.by_night" :key="night" class="text-ink-gray-7">
                  <td class="py-1 pe-3 whitespace-nowrap">{{ formatDate(night) }}</td>
                  <td class="py-1 pe-3">{{ figures.sellable }}</td>
                  <td class="py-1 pe-3">{{ figures.blocked }}</td>
                  <td class="py-1 pe-3">{{ figures.sold }}</td>
                  <td
                    class="py-1 font-medium"
                    :class="figures.available < form.rooms ? 'text-ink-red-3' : 'text-ink-gray-9'"
                  >
                    {{ figures.available }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Button, FormControl } from 'frappe-ui'
import { computed, reactive } from 'vue'

import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import { availabilitySearchResource } from '@/resources/availability'
import { property } from '@/stores/property'
import { formatDate, toServerDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const search = availabilitySearchResource()

// Default to tonight, which is what a walk-in asks for.
const today = new Date()
const tomorrow = new Date(today.getTime() + 86400000)

const form = reactive({
  arrival: toServerDate(today),
  departure: toServerDate(tomorrow),
  rooms: 1,
  adults: 2,
  children: 0,
})

const results = computed(() => {
  const types = search.data?.room_types || {}

  return Object.entries(types)
    .map(([name, bucket]) => ({ name, ...bucket }))
    .sort((a, b) => (b.bookable === a.bookable ? 0 : b.bookable ? 1 : -1))
})

function run() {
  search.fetch({
    property: property.activeName.value,
    arrival: form.arrival,
    departure: form.departure,
    rooms: form.rooms,
    adults: form.adults,
    children: form.children,
  })
}
</script>
