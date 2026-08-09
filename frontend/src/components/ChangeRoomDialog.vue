<!--
  Move an in-house guest to another room.

  The room list comes from the availability service, which only offers rooms
  free for the rest of the stay — so the desk cannot pick a room that is
  already sold. The server re-checks it under a lock and records the move
  against the stay (services/stays.py `change_room`).
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.stay.change_room_title'), size: 'md' }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-p-sm text-ink-gray-6">{{ t('page.stay.change_room_hint') }}</p>

        <p class="text-p-sm text-ink-gray-8">
          {{ stay?.guest_name }} · {{ t('page.stay.room') }} {{ stay?.room }}
        </p>

        <LoadingState v-if="rooms.loading && !rooms.data" />

        <EmptyState v-else-if="!roomOptions.length" :message="t('page.stay.no_rooms_free')" />

        <template v-else>
          <FormControl
            v-model="form.room"
            type="select"
            :label="t('page.stay.new_room')"
            :options="roomOptions"
          />

          <FormControl
            v-model="form.reason"
            type="textarea"
            :label="t('page.stay.change_room_reason')"
            rows="3"
          />
        </template>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button
            variant="solid"
            :loading="saving"
            :disabled="!form.room || !form.reason.trim()"
            @click="submit"
          >
            {{ t('page.stay.change_room') }}
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
import { changeRoomResource } from '@/resources/stays'
import { property } from '@/stores/property'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  stay: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const rooms = assignableRoomsResource()
const changeRoom = changeRoomResource()

const saving = ref(false)
const errorMessage = ref('')
const form = reactive({ room: '', reason: '' })

// The room the guest is in now is not a move, so it is never offered.
const roomOptions = computed(() =>
  (rooms.data || [])
    .filter((room) => room.name !== props.stay?.room)
    .map((room) => ({
      label: room.ready ? room.room_number : `${room.room_number} (${t('page.arrivals.not_ready')})`,
      value: room.name,
    })),
)

watch(
  () => [props.modelValue, props.stay?.name],
  ([isOpen]) => {
    if (!isOpen || !props.stay) return

    errorMessage.value = ''
    form.room = ''
    form.reason = ''

    rooms.fetch({
      property: property.activeName.value,
      room_type: props.stay.room_type,
      // From today, not from the original arrival: the nights already slept
      // cannot make a room unavailable for the move.
      arrival: property.businessDate.value || props.stay.arrival_date,
      departure: props.stay.departure_date,
    })
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await changeRoom.submit({
      stay: props.stay.name,
      new_room: form.room,
      reason: form.reason.trim(),
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
