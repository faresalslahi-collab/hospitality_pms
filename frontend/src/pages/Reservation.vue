<template>
  <div>
    <LoadingState v-if="detail.loading && !detail.data" />
    <ErrorState v-else-if="detail.error" :error="detail.error" :on-retry="load" />

    <div v-else-if="reservation">
      <PageHeader :title="reservation.guest_name || reservation.name" :subtitle="reservation.name">
        <template #actions>
          <Badge
            :theme="reservationStatusTheme(reservation.reservation_status)"
            variant="subtle"
            :label="reservation.reservation_status"
          />

          <!-- Only transitions the server says are reachable are offered. -->
          <Button
            v-for="action in actions"
            :key="action.key"
            :variant="action.variant"
            :theme="action.theme"
            :loading="busy === action.key"
            @click="action.run"
          >
            {{ action.label }}
          </Button>
        </template>
      </PageHeader>

      <div class="grid gap-5 p-5 lg:grid-cols-3">
        <section class="space-y-4 lg:col-span-2">
          <div class="rounded border border-outline-gray-1">
            <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
              {{ t('page.reservation.rooms') }}
            </h2>

            <div v-for="line in detail.data.rooms" :key="line.name" class="border-b border-outline-gray-1 p-4 last:border-b-0">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p class="font-medium text-ink-gray-9">
                    {{ line.rooms }} × {{ line.room_type }}
                  </p>
                  <p class="mt-0.5 text-p-sm text-ink-gray-6">
                    {{ formatDate(line.arrival_date) }} → {{ formatDate(line.departure_date) }}
                    · {{ line.nights }} {{ t('page.reservation.nights') }}
                    · {{ line.adults }}A {{ line.children }}C
                  </p>
                  <p v-if="line.assigned_room" class="mt-0.5 text-p-sm text-ink-green-3">
                    {{ t('page.reservation.assigned') }}: {{ line.assigned_room }}
                  </p>

                  <!--
                    Pre-assignment lives here rather than only in check-in, so
                    a room can be chosen for a VIP or a connecting pair days
                    before they arrive.
                  -->
                  <Button
                    v-if="canAssign"
                    class="mt-2"
                    variant="subtle"
                    size="sm"
                    @click="openAssign(line)"
                  >
                    <template #prefix><FeatherIcon name="key" class="size-3.5" /></template>
                    {{
                      line.assigned_room
                        ? t('page.reservation.change_assigned_room')
                        : t('page.reservation.assign_room')
                    }}
                  </Button>
                </div>
                <p class="font-medium text-ink-gray-9">
                  {{ formatCurrency(line.total_amount, reservation.currency) }}
                </p>
              </div>

              <details v-if="line.rate_lines?.length" class="mt-3">
                <summary class="cursor-pointer text-p-sm text-ink-gray-6">
                  {{ t('page.reservation.rate_breakdown') }}
                </summary>
                <table class="mt-2 w-full text-p-sm">
                  <tbody>
                    <tr v-for="rate in line.rate_lines" :key="rate.rate_date" class="text-ink-gray-7">
                      <td class="py-0.5">{{ formatDate(rate.rate_date) }}</td>
                      <td class="py-0.5 text-end">
                        {{ formatCurrency(rate.net_rate, reservation.currency) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </details>
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
        </aside>
      </div>
    </div>

    <!-- Cancellation is destructive and always asks for a reason. -->
    <Dialog v-model="cancelOpen" :options="{ title: t('page.reservation.cancel_title') }">
      <template #body-content>
        <div class="space-y-3">
          <p class="text-p-sm text-ink-gray-6">{{ t('page.reservation.cancel_warning') }}</p>
          <FormControl v-model="cancelReason" type="textarea" :label="t('page.rack.reason')" rows="3" />
          <ErrorMessage :message="actionError" />
          <div class="flex justify-end gap-2">
            <Button variant="subtle" @click="cancelOpen = false">{{ t('common.close') }}</Button>
            <Button
              variant="solid"
              theme="red"
              :loading="busy === 'cancel'"
              :disabled="!cancelReason.trim()"
              @click="doCancel"
            >
              {{ t('page.reservation.cancel_confirm') }}
            </Button>
          </div>
        </div>
      </template>
    </Dialog>

    <AssignRoomDialog
      v-model="assignOpen"
      :reservation="reservation?.name || ''"
      :line="assignLine"
      @changed="onAssigned"
    />
  </div>
</template>

<script setup>
import { Badge, Button, Dialog, ErrorMessage, FeatherIcon, FormControl, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AssignRoomDialog from '@/components/AssignRoomDialog.vue'
import PageHeader from '@/components/PageHeader.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import {
  cancelReservationResource,
  confirmReservationResource,
  guaranteeReservationResource,
  reservationResource,
  reservationStatusTheme,
} from '@/resources/reservations'
import { FRONT_DESK_ROLES } from '@/resources/frontOffice'
import { session } from '@/stores/session'
import { normaliseError } from '@/utils/errors'
import { formatCurrency, formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const route = useRoute()
const router = useRouter()

const detail = reservationResource()
const confirmResource = confirmReservationResource()
const guaranteeRes = guaranteeReservationResource()
const cancelRes = cancelReservationResource()

const busy = ref('')
const assignOpen = ref(false)
const assignLine = ref(null)
const cancelOpen = ref(false)
const cancelReason = ref('')
const actionError = ref('')

const reservation = computed(() => detail.data?.reservation || null)

// A room is only worth choosing while the booking still holds one. Once it is
// cancelled, checked out or a no-show, the control would only mislead.
const canAssign = computed(
  () =>
    session.hasRole(FRONT_DESK_ROLES) &&
    ['Tentative', 'Confirmed', 'Guaranteed'].includes(reservation.value?.reservation_status),
)

function openAssign(line) {
  assignLine.value = line
  assignOpen.value = true
}

function onAssigned() {
  toast.success(t('page.reservation.assigned_room_saved'))
  load()
}
const allowed = computed(() => detail.data?.allowed_transitions || [])

const summary = computed(() => {
  const r = reservation.value
  if (!r) return []

  return [
    { label: t('page.reservations.arrival'), value: formatDate(r.arrival_date) },
    { label: t('page.reservations.departure'), value: formatDate(r.departure_date) },
    { label: t('page.reservations.nights'), value: r.nights },
    { label: t('page.reservations.rooms'), value: r.total_rooms },
    { label: t('page.reservation.guests'), value: `${r.total_adults}A ${r.total_children}C` },
    { label: t('page.reservations.total'), value: formatCurrency(r.total_amount, r.currency) },
    { label: t('page.reservation.source'), value: r.booking_source || '—' },
  ]
})

const actions = computed(() => {
  const list = []

  if (allowed.value.includes('Checked In')) {
    list.push({
      key: 'check_in',
      label: t('page.reservation.check_in'),
      variant: 'solid',
      theme: 'gray',
      run: () => router.push({ name: 'CheckIn', params: { reservation: route.params.id } }),
    })
  }

  if (allowed.value.includes('Confirmed')) {
    list.push({
      key: 'confirm',
      label: t('page.reservation.confirm'),
      variant: 'solid',
      theme: 'gray',
      run: () => run('confirm', () => confirmResource.submit({ reservation: route.params.id })),
    })
  }

  if (allowed.value.includes('Guaranteed')) {
    list.push({
      key: 'guarantee',
      label: t('page.reservation.guarantee'),
      variant: 'subtle',
      theme: 'gray',
      run: () =>
        run('guarantee', () =>
          guaranteeRes.submit({ reservation: route.params.id, guarantee_type: 'Credit Card' }),
        ),
    })
  }

  if (allowed.value.includes('Cancelled')) {
    list.push({
      key: 'cancel',
      label: t('page.reservation.cancel'),
      variant: 'subtle',
      theme: 'red',
      run: () => {
        actionError.value = ''
        cancelReason.value = ''
        cancelOpen.value = true
      },
    })
  }

  return list
})

async function run(key, fn) {
  busy.value = key
  actionError.value = ''

  try {
    await fn()
    await load()
    toast.success(t('page.reservation.updated'))
  } catch (error) {
    const details = normaliseError(error)
    actionError.value = details.message
    toast.error(details.message)
  } finally {
    busy.value = ''
  }
}

async function doCancel() {
  await run('cancel', () =>
    cancelRes.submit({ reservation: route.params.id, reason: cancelReason.value }),
  )

  if (!actionError.value) cancelOpen.value = false
}

function load() {
  return detail.fetch({ reservation: route.params.id })
}

watch(() => route.params.id, load, { immediate: true })
</script>
