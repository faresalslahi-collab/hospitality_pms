<!--
  Assign a specific room to a reservation room line, before arrival.

  Until now the only way to choose a room in `/pms` was during check-in, which
  made pre-assignment — the normal thing to do for a VIP, a connecting pair or
  a group — a Desk-only job. The rules have not moved: the server locks the
  room and re-checks it is assignable (services/reservations.py `assign_room`).
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.reservation.assign_room_title'), size: 'md' }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-p-sm text-ink-gray-6">{{ t('page.reservation.assign_room_hint') }}</p>

        <p v-if="line" class="text-p-sm text-ink-gray-8">
          {{ line.room_type }} · {{ formatDate(line.arrival_date) }} →
          {{ formatDate(line.departure_date) }}
        </p>

        <LoadingState v-if="rooms.loading && !rooms.data" />

        <EmptyState v-else-if="!roomOptions.length" :message="t('page.reservation.no_assignable')" />

        <template v-else>
          <FormControl
            v-model="form.room"
            type="select"
            :label="t('page.reservation.assign_room')"
            :options="roomOptions"
          />

          <!--
            The override is only offered once an unready room is actually
            chosen, so it never reads as a general permission to ignore
            housekeeping.
          -->
          <div
            v-if="selectedUnready"
            class="space-y-2 rounded border border-outline-amber-1 bg-surface-amber-1 p-3"
          >
            <p class="text-p-sm text-ink-amber-3">{{ t('page.reservation.allow_unready_hint') }}</p>
            <label class="flex items-center gap-2 text-p-sm text-ink-amber-3">
              <input v-model="form.allowUnready" type="checkbox" class="size-4" />
              {{ t('page.reservation.allow_unready') }}
            </label>
          </div>
        </template>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!canSubmit" @click="submit">
            {{ t('page.reservation.assign_room') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import EmptyState from '@/components/states/EmptyState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { assignableRoomsResource } from '@/resources/availability'
import { assignRoomResource } from '@/resources/reservations'
import { property } from '@/stores/property'
import { normaliseError } from '@/utils/errors'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  reservation: { type: String, default: '' },
  line: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const rooms = assignableRoomsResource()
const assignRoom = assignRoomResource()

const saving = ref(false)
const errorMessage = ref('')
const form = reactive({ room: '', allowUnready: false })

const roomOptions = computed(() =>
  (rooms.data || []).map((room) => ({
    label: room.ready
      ? room.room_number
      : `${room.room_number} (${t('page.reservation.unready_room')})`,
    value: room.name,
  })),
)

const selected = computed(() => (rooms.data || []).find((room) => room.name === form.room) || null)
const selectedUnready = computed(() => Boolean(selected.value && !selected.value.ready))

const canSubmit = computed(() => {
  if (!form.room || saving.value) return false
  return selectedUnready.value ? form.allowUnready : true
})

watch(
  () => [props.modelValue, props.line?.name],
  ([isOpen]) => {
    if (!isOpen || !props.line) return

    errorMessage.value = ''
    form.room = ''
    form.allowUnready = false

    rooms.fetch({
      property: property.activeName.value,
      room_type: props.line.room_type,
      arrival: props.line.arrival_date,
      departure: props.line.departure_date,
      // Unready rooms are listed so the desk can see the whole picture; the
      // tick above, and the server, decide whether one may actually be used.
      include_unready: 1,
    })
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await assignRoom.submit({
      reservation: props.reservation,
      room_line: props.line.name,
      room: form.room,
      allow_unready: form.allowUnready ? 1 : 0,
    })

    emit('changed')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
