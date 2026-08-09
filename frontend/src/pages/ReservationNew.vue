<!--
  New reservation.

  Pricing is always the server's: this screen never lets the guest type a
  rate. `reservations.quote` runs the same pricing service the reservation
  itself will use, so the breakdown shown here and the amount actually
  charged cannot diverge (Frontend Standards section 5).
-->
<template>
  <div>
    <PageHeader :title="t('page.reservation_new.title')" :subtitle="t('page.reservation_new.subtitle')" />

    <div class="grid gap-5 p-5 lg:grid-cols-3">
      <section class="space-y-5 lg:col-span-2">
        <div class="space-y-3 rounded border border-outline-gray-1 p-4">
          <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.reservation_new.guest_section') }}</p>

          <FormControl
            v-model="guestMode"
            type="select"
            :options="[
              { label: t('page.reservation_new.existing_guest'), value: 'existing' },
              { label: t('page.reservation_new.new_guest'), value: 'new' },
            ]"
          />

          <Autocomplete
            v-if="guestMode === 'existing'"
            v-model="guestOption"
            :options="guestOptions"
            :loading="guestSearch.loading"
            :placeholder="t('page.reservation_new.search_guest')"
            @update:query="onGuestQuery"
          />

          <div v-else class="grid gap-3 sm:grid-cols-2">
            <FormControl v-model="form.guest_name" type="text" :label="t('page.reservation_new.guest_name')" />
            <FormControl v-model="form.guest_email" type="text" :label="t('page.reservation_new.guest_email')" />
            <FormControl v-model="form.guest_mobile" type="text" :label="t('page.reservation_new.guest_mobile')" />
          </div>

          <div v-if="guestMode === 'existing'" class="grid gap-3 sm:grid-cols-2">
            <FormControl v-model="form.guest_email" type="text" :label="t('page.reservation_new.guest_email')" />
            <FormControl v-model="form.guest_mobile" type="text" :label="t('page.reservation_new.guest_mobile')" />
          </div>
        </div>

        <div class="space-y-3 rounded border border-outline-gray-1 p-4">
          <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.reservation_new.stay_section') }}</p>

          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <FormControl v-model="form.arrival" type="date" :label="t('page.reservation_new.arrival')" />
            <FormControl v-model="form.departure" type="date" :label="t('page.reservation_new.departure')" />
            <FormControl v-model.number="form.rooms" type="number" min="1" :label="t('page.reservation_new.rooms')" />
            <FormControl v-model.number="form.adults" type="number" min="1" :label="t('page.reservation_new.adults')" />
            <FormControl
              v-model.number="form.children"
              type="number"
              min="0"
              :label="t('page.reservation_new.children')"
            />
          </div>

          <Button variant="subtle" :loading="search.loading" @click="checkAvailability">
            {{ t('page.reservation_new.check_availability') }}
          </Button>

          <ErrorState v-if="search.error" :error="search.error" :on-retry="checkAvailability" />

          <EmptyState
            v-else-if="search.data && !roomTypeChoices.length"
            :message="t('page.reservation_new.no_room_types')"
          />

          <div v-else-if="roomTypeChoices.length" class="grid gap-2 sm:grid-cols-2">
            <button
              v-for="choice in roomTypeChoices"
              :key="choice.name"
              type="button"
              class="rounded border p-3 text-start transition-colors"
              :class="
                form.room_type === choice.name
                  ? 'border-outline-gray-4 bg-surface-gray-2'
                  : 'border-outline-gray-1 hover:bg-surface-gray-1'
              "
              @click="selectRoomType(choice.name)"
            >
              <p class="font-medium text-ink-gray-9">{{ choice.room_type_name || choice.name }}</p>
              <p class="mt-0.5 text-p-sm" :class="choice.bookable ? 'text-ink-green-3' : 'text-ink-red-3'">
                {{ choice.min_available }} {{ t('page.availability.min_available') }}
              </p>
            </button>
          </div>

          <FormControl
            v-if="form.room_type"
            v-model="form.rate_plan"
            type="select"
            :label="t('page.reservation_new.rate_plan')"
            :options="ratePlanOptions"
          />
        </div>

        <div v-if="quote.loading" class="rounded border border-outline-gray-1 p-4">
          <LoadingState />
        </div>
        <ErrorState v-else-if="quote.error" :error="quote.error" :on-retry="runQuote" />

        <div v-else-if="quote.data" class="space-y-3 rounded border border-outline-gray-1 p-4">
          <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.reservation_new.quote') }}</p>

          <table class="w-full text-p-sm">
            <tbody>
              <tr v-for="line in quote.data.lines" :key="line.rate_date" class="text-ink-gray-7">
                <td class="py-0.5">{{ formatDate(line.rate_date) }}</td>
                <td class="py-0.5 text-end">{{ formatCurrency(line.net_rate, quote.data.currency) }}</td>
              </tr>
            </tbody>
          </table>

          <dl class="grid grid-cols-2 gap-2 border-t border-outline-gray-1 pt-3 text-p-sm">
            <dt class="text-ink-gray-5">{{ t('page.reservation_new.average_nightly_rate') }}</dt>
            <dd class="text-end text-ink-gray-8">
              {{ formatCurrency(quote.data.average_nightly_rate, quote.data.currency) }}
            </dd>
            <dt class="text-ink-gray-5">{{ t('page.reservation_new.total_per_room') }}</dt>
            <dd class="text-end text-ink-gray-8">
              {{ formatCurrency(quote.data.total_per_room, quote.data.currency) }}
            </dd>
            <dt class="font-medium text-ink-gray-8">{{ t('page.reservation_new.total_amount') }}</dt>
            <dd class="text-end font-medium text-ink-gray-9">
              {{ formatCurrency(quote.data.total_amount, quote.data.currency) }}
            </dd>
          </dl>
        </div>

        <div class="space-y-3 rounded border border-outline-gray-1 p-4">
          <div class="grid gap-3 sm:grid-cols-2">
            <FormControl
              v-model="form.reservation_type"
              type="select"
              :label="t('page.reservation_new.reservation_type')"
              :options="reservationTypeOptions"
            />
            <FormControl v-model="form.booking_source" type="text" :label="t('page.reservation_new.booking_source')" />
          </div>
          <FormControl
            v-model="form.special_requests"
            type="textarea"
            rows="2"
            :label="t('page.reservation_new.special_requests')"
          />
        </div>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" :loading="saving === 'Draft'" :disabled="!canSave" @click="save('Draft')">
            {{ t('page.reservation_new.save_draft') }}
          </Button>
          <Button variant="solid" :loading="saving === 'Tentative'" :disabled="!canSave" @click="save('Tentative')">
            {{ t('page.reservation_new.save_tentative') }}
          </Button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { Autocomplete, Button, ErrorMessage, FormControl, toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { availabilitySearchResource } from '@/resources/availability'
import { searchGuestsResource } from '@/resources/guests'
import { createReservationResource, quoteResource } from '@/resources/reservations'
import { listResource } from '@/resources'
import { property } from '@/stores/property'
import { normaliseError } from '@/utils/errors'
import { formatCurrency, formatDate, toServerDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const router = useRouter()

const search = availabilitySearchResource()
const quote = quoteResource()
const guestSearch = searchGuestsResource()
const createReservation = createReservationResource()
const ratePlans = listResource('Rate Plan', { fields: ['name', 'rate_plan_name'] })

const today = new Date()
const tomorrow = new Date(today.getTime() + 86400000)

const guestMode = ref('existing')
const guestOption = ref(null)
const errorMessage = ref('')
const saving = ref('')
let queryTimer = null

const form = reactive({
  arrival: toServerDate(today),
  departure: toServerDate(tomorrow),
  rooms: 1,
  adults: 2,
  children: 0,
  room_type: '',
  rate_plan: '',
  guest_name: '',
  guest_email: '',
  guest_mobile: '',
  reservation_type: 'Individual',
  booking_source: '',
  special_requests: '',
})

const reservationTypeOptions = [
  'Individual',
  'Multi Room',
  'Corporate',
  'Group',
  'Travel Agent',
  'Walk In',
  'Direct Website',
  'OTA',
].map((value) => ({ label: value, value }))

const roomTypeChoices = computed(() => {
  const types = search.data?.room_types || {}
  return Object.entries(types).map(([name, bucket]) => ({ name, ...bucket }))
})

const ratePlanOptions = computed(() => [
  { label: t('page.reservation_new.rate_plan_auto'), value: '' },
  ...(ratePlans.data || []).map((row) => ({ label: row.rate_plan_name || row.name, value: row.name })),
])

const guestOptions = computed(() =>
  (guestSearch.data || []).map((g) => ({
    label: g.guest_name,
    value: g.name,
    description: g.email_id || g.mobile_no || '',
  })),
)

const guestSelected = computed(() => guestMode.value === 'existing' && Boolean(guestOption.value?.value))

const canSave = computed(() => {
  if (!form.room_type || !quote.data) return false
  if (guestMode.value === 'existing') return guestSelected.value
  return Boolean(form.guest_name.trim())
})

function onGuestQuery(query) {
  window.clearTimeout(queryTimer)
  queryTimer = window.setTimeout(() => {
    guestSearch.fetch({ query, limit: 20 })
  }, 300)
}

function checkAvailability() {
  form.room_type = ''
  quote.reset?.()

  search.fetch({
    property: property.activeName.value,
    arrival: form.arrival,
    departure: form.departure,
    rooms: form.rooms,
    adults: form.adults,
    children: form.children,
  })
}

function selectRoomType(name) {
  form.room_type = name
  runQuote()
}

function runQuote() {
  if (!form.room_type) return

  quote.fetch({
    property: property.activeName.value,
    room_type: form.room_type,
    arrival: form.arrival,
    departure: form.departure,
    rate_plan: form.rate_plan || undefined,
    adults: form.adults,
    children: form.children,
    rooms: form.rooms,
  })
}

watch(() => form.rate_plan, () => {
  if (form.room_type) runQuote()
})

watch(
  () => property.activeName.value,
  (value) => {
    if (value) ratePlans.filters = { property: value, is_active: 1 }
    ratePlans.reload()
  },
  { immediate: true },
)

async function save(status) {
  saving.value = status
  errorMessage.value = ''

  const payload = {
    property: property.activeName.value,
    reservation_type: form.reservation_type,
    reservation_status: status,
    arrival_date: form.arrival,
    departure_date: form.departure,
    booking_source: form.booking_source.trim() || undefined,
    special_requests: form.special_requests.trim() || undefined,
    guest_email: form.guest_email.trim() || undefined,
    guest_mobile: form.guest_mobile.trim() || undefined,
    rooms: [
      {
        room_type: form.room_type,
        rooms: form.rooms,
        arrival_date: form.arrival,
        departure_date: form.departure,
        adults: form.adults,
        children: form.children,
        rate_plan: form.rate_plan || undefined,
      },
    ],
  }

  if (guestMode.value === 'existing') {
    payload.guest = guestOption.value?.value
  } else {
    payload.guest_name = form.guest_name.trim()
  }

  try {
    const result = await createReservation.submit({ reservation: payload })
    toast.success(t('page.reservation_new.created'))
    router.push({ name: 'Reservation', params: { id: result.reservation.name } })
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = ''
  }
}
</script>
