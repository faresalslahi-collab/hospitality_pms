<!--
  Raise a guest request or complaint.

  Every field the server accepts is offered; the server is the one that
  validates a subject and description are present (Frontend Standards
  section 5) — this dialog only keeps the submit button honest so an empty
  form is not a wasted round trip.

  The four link fields — room, guest, reservation, stay — can be prefilled by the
  caller (16.7.1). Raised from the guest services page there is no context to
  prefill and the props are simply absent, which is the behaviour this dialog has
  always had. Raised from an operational board there is a row, and the context is
  the operational value of the request: a complaint typed against a mistyped room
  number is worse than none, because it sends someone to the wrong door. The
  fields stay editable — the row is a starting point, not a verdict.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.guest_services.create_title'), size: 'lg' }">
    <template #body-content>
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <FormControl
            v-model="form.request_type"
            type="select"
            :label="t('page.guest_services.request_type')"
            :options="requestTypeOptions"
          />
          <FormControl
            v-model="form.priority"
            type="select"
            :label="t('page.guest_services.priority_label')"
            :options="priorityOptions"
          />
          <FormControl
            v-model="form.category"
            type="select"
            :label="t('page.guest_services.category_label')"
            :options="categoryOptions"
          />
          <FormControl v-model="form.sla_minutes" type="number" min="1" :label="t('page.guest_services.sla_optional')" />
        </div>

        <FormControl v-model="form.subject" type="text" :label="t('page.guest_services.subject_label')" />
        <FormControl v-model="form.description" type="textarea" rows="3" :label="t('page.guest_services.description_label')" />

        <div class="grid gap-3 sm:grid-cols-2">
          <FormControl v-model="form.room" type="text" :label="t('page.guest_services.room_optional')" />
          <FormControl v-model="form.guest" type="text" :label="t('page.guest_services.guest_optional')" />
          <FormControl v-model="form.reservation" type="text" :label="t('page.guest_services.reservation_optional')" />
          <FormControl v-model="form.stay" type="text" :label="t('page.guest_services.stay_optional')" />
        </div>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button
            variant="solid"
            :loading="saving"
            :disabled="!form.subject.trim() || !form.description.trim() || !form.category"
            @click="submit"
          >
            {{ t('page.guest_services.create') }}
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
  CATEGORY_OPTIONS,
  PRIORITY_OPTIONS,
  REQUEST_TYPE_OPTIONS,
  createGuestRequestResource,
} from '@/resources/guestServices'
import { property } from '@/stores/property'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /**
   * Optional context to start the form from. All four default to '', so a caller
   * that has none — the guest services page — is unaffected.
   */
  room: { type: String, default: '' },
  guest: { type: String, default: '' },
  reservation: { type: String, default: '' },
  stay: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'created'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const createResource = createGuestRequestResource()

const saving = ref(false)
const errorMessage = ref('')

function blankForm() {
  return {
    request_type: 'Request',
    priority: 'Normal',
    category: '',
    sla_minutes: '',
    subject: '',
    description: '',
    // The caller's context, re-read on every open so a second request raised
    // from a different row does not inherit the first row's room.
    room: props.room || '',
    guest: props.guest || '',
    reservation: props.reservation || '',
    stay: props.stay || '',
  }
}

const form = reactive(blankForm())

const requestTypeOptions = REQUEST_TYPE_OPTIONS.map((value) => ({ label: value, value }))
const priorityOptions = PRIORITY_OPTIONS.map((value) => ({ label: value, value }))
const categoryOptions = CATEGORY_OPTIONS.map((value) => ({ label: value, value }))

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return
    errorMessage.value = ''
    Object.assign(form, blankForm())
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await createResource.submit({
      property: property.activeName.value,
      subject: form.subject.trim(),
      description: form.description.trim(),
      category: form.category,
      request_type: form.request_type,
      priority: form.priority,
      room: form.room || undefined,
      guest: form.guest || undefined,
      reservation: form.reservation || undefined,
      stay: form.stay || undefined,
      sla_minutes: form.sla_minutes || undefined,
    })

    emit('created')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
