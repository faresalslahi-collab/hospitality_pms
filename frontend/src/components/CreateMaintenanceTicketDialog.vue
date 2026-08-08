<!--
  Raise a maintenance ticket from the board.

  A ticket may be against a room, a zone or a free-text area (a lobby, a
  plant room); the server does not require any of them, so none is marked
  mandatory here beyond title, description and category.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.maintenance.create_title'), size: 'lg' }">
    <template #body-content>
      <div class="space-y-4">
        <FormControl v-model="form.title" type="text" :label="t('page.maintenance.ticket_title')" />
        <FormControl v-model="form.description" type="textarea" :label="t('page.maintenance.description')" rows="3" />

        <div class="grid gap-2 sm:grid-cols-3">
          <FormControl
            v-model="form.category"
            type="select"
            :label="t('page.maintenance.category')"
            :options="categoryOptions"
          />
          <FormControl
            v-model="form.ticket_type"
            type="select"
            :label="t('page.maintenance.ticket_type')"
            :options="typeOptions"
          />
          <FormControl
            v-model="form.priority"
            type="select"
            :label="t('page.maintenance.priority')"
            :options="priorityOptions"
          />
        </div>

        <div class="grid gap-2 sm:grid-cols-3">
          <FormControl v-model="form.room" type="text" :label="t('page.maintenance.room')" />
          <FormControl v-model="form.zone" type="text" :label="t('page.maintenance.zone')" />
          <FormControl v-model="form.area" type="text" :label="t('page.maintenance.area')" />
        </div>
        <p class="text-p-sm text-ink-gray-5">{{ t('page.maintenance.room_hint') }}</p>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button
            variant="solid"
            :loading="saving"
            :disabled="!form.title.trim() || !form.description.trim()"
            @click="submit"
          >
            {{ t('page.maintenance.create') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import {
  createMaintenanceTicketResource,
  TICKET_CATEGORIES,
  TICKET_PRIORITIES,
  TICKET_TYPES,
} from '@/resources/maintenance'
import { property } from '@/stores/property'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const create = createMaintenanceTicketResource()

const saving = ref(false)
const errorMessage = ref('')

function emptyForm() {
  return {
    title: '',
    description: '',
    category: 'Other',
    ticket_type: 'Corrective',
    priority: 'Normal',
    room: '',
    zone: '',
    area: '',
  }
}

const form = reactive(emptyForm())

const categoryOptions = TICKET_CATEGORIES.map((value) => ({ label: value, value }))
const typeOptions = TICKET_TYPES.map((value) => ({ label: value, value }))
const priorityOptions = TICKET_PRIORITIES.map((value) => ({ label: value, value }))

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return

    errorMessage.value = ''
    Object.assign(form, emptyForm())
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await create.submit({
      property: property.activeName.value,
      title: form.title.trim(),
      description: form.description.trim(),
      category: form.category,
      priority: form.priority,
      ticket_type: form.ticket_type,
      room: form.room || undefined,
      zone: form.zone || undefined,
      area: form.area || undefined,
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
