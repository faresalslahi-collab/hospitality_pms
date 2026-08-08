<!--
  Room detail and status change.

  The dimension dropdowns offer every value, and the server refuses the ones
  that are not reachable from the current state. Filtering client-side would
  duplicate the transition table and let the two drift.
-->
<template>
  <Dialog v-model="open" :options="{ title: room?.room_number || '', size: 'lg' }">
    <template #body-content>
      <div v-if="room" class="space-y-4">
        <dl class="grid grid-cols-2 gap-3">
          <div v-for="d in dimensions" :key="d.key">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ d.label }}</dt>
            <dd class="mt-1"><RoomStatusBadge :status="d.value" /></dd>
          </div>
        </dl>

        <div v-if="detail.data?.assignable === false" class="rounded bg-surface-red-1 px-3 py-2">
          <p class="text-p-sm text-ink-red-4">{{ t('page.rack.not_assignable') }}</p>
        </div>

        <div class="space-y-3 border-t border-outline-gray-1 pt-4">
          <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.rack.change_status') }}</p>

          <div class="grid gap-2 sm:grid-cols-2">
            <FormControl
              v-model="form.dimension"
              type="select"
              :label="t('page.rack.dimension')"
              :options="dimensionOptions"
            />
            <FormControl
              v-model="form.status"
              type="select"
              :label="t('page.rack.new_status')"
              :options="statusOptions"
            />
          </div>

          <FormControl
            v-model="form.reason"
            type="textarea"
            :label="t('page.rack.reason')"
            :placeholder="t('page.rack.reason_hint')"
            rows="2"
          />

          <ErrorMessage :message="errorMessage" />

          <div class="flex justify-end gap-2">
            <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
            <Button
              variant="solid"
              :loading="saving"
              :disabled="!form.dimension || !form.status"
              @click="apply"
            >
              {{ t('common.confirm') }}
            </Button>
          </div>
        </div>

        <div v-if="detail.data?.history?.length" class="border-t border-outline-gray-1 pt-4">
          <p class="mb-2 text-p-sm font-medium text-ink-gray-8">{{ t('page.rack.history') }}</p>
          <ul class="max-h-48 space-y-1 overflow-y-auto">
            <li
              v-for="(entry, index) in detail.data.history"
              :key="index"
              class="flex flex-wrap items-baseline gap-x-2 text-xs text-ink-gray-6"
            >
              <span class="text-ink-gray-8">{{ entry.dimension }}</span>
              <span>{{ entry.from_status || '—' }} → {{ entry.to_status }}</span>
              <span class="ms-auto">{{ formatDateTime(entry.changed_at) }}</span>
            </li>
          </ul>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import RoomStatusBadge from '@/components/RoomStatusBadge.vue'
import { ROOM_DIMENSIONS, roomResource, setRoomStatusResource } from '@/resources/rooms'
import { normaliseError } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  room: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const detail = roomResource()
const setStatus = setRoomStatusResource()

const saving = ref(false)
const errorMessage = ref('')

const form = reactive({ dimension: 'Housekeeping', status: '', reason: '' })

const dimensions = computed(() => {
  const source = detail.data?.room || props.room || {}

  return [
    { key: 'occupancy', label: t('page.rack.occupancy'), value: source.occupancy_status },
    { key: 'housekeeping', label: t('page.rack.housekeeping'), value: source.housekeeping_status },
    { key: 'maintenance', label: t('page.rack.maintenance'), value: source.maintenance_status },
    { key: 'inventory', label: t('page.rack.inventory'), value: source.inventory_status },
  ].filter((d) => d.value)
})

const dimensionOptions = Object.keys(ROOM_DIMENSIONS).map((key) => ({ label: key, value: key }))

const statusOptions = computed(() =>
  (ROOM_DIMENSIONS[form.dimension] || []).map((value) => ({ label: value, value })),
)

watch(
  () => form.dimension,
  () => {
    form.status = ''
  },
)

watch(
  () => [props.modelValue, props.room?.name],
  ([isOpen, name]) => {
    if (!isOpen || !name) return

    errorMessage.value = ''
    form.reason = ''
    form.status = ''
    detail.fetch({ room: name })
  },
)

async function apply() {
  saving.value = true
  errorMessage.value = ''

  try {
    await setStatus.submit({
      room: props.room.name,
      dimension: form.dimension,
      status: form.status,
      reason: form.reason,
    })

    await detail.fetch({ room: props.room.name })
    emit('changed')
    form.reason = ''
    form.status = ''
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
