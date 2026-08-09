<!--
  One stay, and everything the desk can do to it while the guest is here.

  Room moves, extensions, shortenings and notes all lived only in Desk until
  now, which put them out of reach of the six operational roles that have no
  Desk at all. Every action below calls the same service Desk called; nothing
  about the rules has moved, only where they can be reached from.
-->
<template>
  <div>
    <LoadingState v-if="detail.loading && !detail.data" />
    <ErrorState v-else-if="detail.error" :error="detail.error" :on-retry="load" />

    <div v-else-if="stay">
      <PageHeader :title="t('page.stay.title')" :subtitle="stay.guest_name || stay.name">
        <template #actions>
          <Badge :theme="stayStatusTheme(stay.stay_status)" variant="subtle" :label="stay.stay_status" />
          <Button variant="subtle" :loading="detail.loading" @click="load">
            <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
            {{ t('common.refresh') }}
          </Button>
        </template>
      </PageHeader>

      <div class="space-y-5 p-5">
        <div
          v-if="stay.readiness_override"
          class="rounded border border-outline-amber-1 bg-surface-amber-1 p-3"
        >
          <p class="text-p-sm text-ink-amber-3">{{ t('page.stay.readiness_override') }}</p>
        </div>

        <!-- The stay itself -->
        <div class="rounded border border-outline-gray-1 p-4">
          <dl class="grid gap-4 sm:grid-cols-3 lg:grid-cols-4">
            <div v-for="field in fields" :key="field.key">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ field.label }}</dt>
              <dd class="mt-0.5 text-p-base text-ink-gray-8">
                <RouterLink
                  v-if="field.to"
                  :to="field.to"
                  class="text-ink-blue-3 hover:underline"
                >
                  {{ field.value }}
                </RouterLink>
                <span v-else>{{ field.value }}</span>
              </dd>
            </div>
          </dl>
        </div>

        <!-- What the desk can do -->
        <section v-if="canOperate" class="space-y-2">
          <h2 class="text-base font-medium text-ink-gray-8">{{ t('page.stay.actions') }}</h2>

          <div class="flex flex-wrap gap-2">
            <Button v-for="action in actions" :key="action.key" variant="subtle" @click="action.run">
              <template #prefix><FeatherIcon :name="action.icon" class="size-4" /></template>
              {{ action.label }}
            </Button>
          </div>
        </section>

        <!-- Companions -->
        <section v-if="companions.length" class="space-y-2">
          <h2 class="text-base font-medium text-ink-gray-8">{{ t('page.stay.companions') }}</h2>

          <div class="flex flex-wrap gap-2">
            <Badge
              v-for="(companion, index) in companions"
              :key="index"
              variant="subtle"
              :theme="companion.is_primary ? 'blue' : 'gray'"
              :label="companion.guest_name"
            />
          </div>
        </section>

        <!-- Notes: the shift handover -->
        <section class="space-y-2">
          <h2 class="text-base font-medium text-ink-gray-8">{{ t('page.stay.notes') }}</h2>

          <EmptyState v-if="!notes.length" :message="t('page.stay.no_notes')" />

          <ul v-else class="divide-y divide-outline-gray-1 rounded border border-outline-gray-1">
            <li v-for="(note, index) in notes" :key="index" class="p-3">
              <div class="flex flex-wrap items-center gap-2">
                <Badge variant="subtle" theme="gray" :label="note.note_type" />
                <span class="text-xs text-ink-gray-5">
                  {{ note.noted_by }} · {{ formatDateTime(note.noted_on) }}
                </span>
              </div>
              <p class="mt-1 text-p-sm text-ink-gray-8">{{ note.note }}</p>
            </li>
          </ul>
        </section>

        <!-- Room moves -->
        <section class="space-y-2">
          <h2 class="text-base font-medium text-ink-gray-8">{{ t('page.stay.room_moves') }}</h2>

          <EmptyState v-if="!roomMoves.length" :message="t('page.stay.no_moves')" />

          <ul v-else class="divide-y divide-outline-gray-1 rounded border border-outline-gray-1">
            <li v-for="(move, index) in roomMoves" :key="index" class="p-3">
              <p class="text-p-sm font-medium text-ink-gray-9">
                {{ t('page.stay.moved_from_to', { from_room: move.from_room, to_room: move.to_room }) }}
              </p>
              <p class="mt-0.5 text-xs text-ink-gray-5">{{ formatDateTime(move.moved_on) }}</p>
              <p v-if="move.reason" class="mt-1 text-p-sm text-ink-gray-7">{{ move.reason }}</p>
            </li>
          </ul>
        </section>
      </div>
    </div>

    <ChangeRoomDialog v-model="changeRoomOpen" :stay="stay" @changed="onChanged('page.stay.moved')" />
    <ExtendStayDialog v-model="extendOpen" :stay="stay" @changed="onChanged('page.stay.extended')" />
    <ShortenStayDialog v-model="shortenOpen" :stay="stay" @changed="onChanged('page.stay.shortened')" />
    <AddStayNoteDialog v-model="noteOpen" :stay="stay" @changed="onChanged('page.stay.note_added')" />
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import AddStayNoteDialog from '@/components/AddStayNoteDialog.vue'
import ChangeRoomDialog from '@/components/ChangeRoomDialog.vue'
import ExtendStayDialog from '@/components/ExtendStayDialog.vue'
import PageHeader from '@/components/PageHeader.vue'
import ShortenStayDialog from '@/components/ShortenStayDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { STAY_OPERATION_ROLES, stayResource, stayStatusTheme } from '@/resources/stays'
import { property } from '@/stores/property'
import { session } from '@/stores/session'
import { formatCurrency, formatDate, formatDateTime } from '@/utils/format'
import { t } from '@/utils/i18n'

const route = useRoute()
const detail = stayResource()

const changeRoomOpen = ref(false)
const extendOpen = ref(false)
const shortenOpen = ref(false)
const noteOpen = ref(false)

const stay = computed(() => detail.data?.stay || null)
const companions = computed(() => detail.data?.companions || [])
const notes = computed(() => detail.data?.notes || [])
const roomMoves = computed(() => detail.data?.room_moves || [])

// Offered only to roles the server will accept. A stay that has already left
// is history, not something to move or extend.
const canOperate = computed(
  () =>
    session.hasRole(STAY_OPERATION_ROLES) &&
    ['In House', 'Due Out'].includes(stay.value?.stay_status),
)

const fields = computed(() => {
  const s = stay.value
  if (!s) return []

  return [
    { key: 'guest', label: t('page.stay.guest'), value: s.guest_name || '—' },
    { key: 'room', label: t('page.stay.room'), value: s.room || '—' },
    { key: 'room_type', label: t('page.stay.room_type'), value: s.room_type || '—' },
    { key: 'status', label: t('page.stay.status'), value: s.stay_status },
    { key: 'arrival', label: t('page.stay.arrival'), value: formatDate(s.arrival_date) },
    { key: 'departure', label: t('page.stay.departure'), value: formatDate(s.departure_date) },
    { key: 'nights', label: t('page.stay.nights'), value: s.nights },
    { key: 'pax', label: t('page.stay.pax'), value: `${s.adults}A ${s.children}C` },
    {
      key: 'rate',
      label: t('page.stay.rate'),
      value: formatCurrency(s.room_rate, s.currency || property.currency.value),
    },
    s.folio && {
      key: 'folio',
      label: t('page.stay.folio'),
      value: s.folio,
      to: { name: 'Folio', params: { id: s.folio } },
    },
    s.reservation && {
      key: 'reservation',
      label: t('page.stay.reservation'),
      value: s.reservation,
      to: { name: 'Reservation', params: { id: s.reservation } },
    },
  ].filter(Boolean)
})

const actions = computed(() => [
  {
    key: 'move',
    label: t('page.stay.change_room'),
    icon: 'move',
    run: () => (changeRoomOpen.value = true),
  },
  {
    key: 'extend',
    label: t('page.stay.extend'),
    icon: 'calendar',
    run: () => (extendOpen.value = true),
  },
  {
    key: 'shorten',
    label: t('page.stay.shorten'),
    icon: 'scissors',
    run: () => (shortenOpen.value = true),
  },
  {
    key: 'note',
    label: t('page.stay.add_note'),
    icon: 'edit-3',
    run: () => (noteOpen.value = true),
  },
])

function load() {
  return detail.fetch({ stay: route.params.id })
}

/** Each dialog says what it did; a shared "saved" would tell the desk nothing. */
function onChanged(messageKey) {
  toast.success(t(messageKey))
  load()
}

watch(() => route.params.id, load, { immediate: true })
</script>
