<!--
  Notes: two fields, and only two.

  `special_requests` is what the guest asked for; `internal_notes` is what the
  staff need to know. Both are on the server's `DETAIL_WRITABLE_FIELDS` list, and
  the service refuses any key outside it — so this tab does not save a document, it
  contributes two fields to the workspace's single collected edit. The Save control
  lives with that draft, in the shell above the tabs, because the same save also
  carries the Overview tab's three fields: one call, one audit entry.

  Nothing here is the booking's history. The history is written by the server on
  every transition and cannot be edited, which is why the internal-notes hint says
  so out loud: a note is not the place to record that a booking was cancelled.

  Whether either field may be edited is `editability.may_edit_details` — the
  server's statement, never re-derived from the status. Where it says no, the text
  is still readable and the reason is shown in the server's own terms.
-->
<template>
  <div class="grid gap-5 lg:grid-cols-2">
    <section class="rounded border border-outline-gray-1">
      <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
        {{ t('page.reservation.notes.special_requests') }}
      </h2>

      <div class="space-y-3 p-4">
        <p class="text-p-sm text-ink-gray-6">{{ t('page.reservation.notes.special_requests_hint') }}</p>

        <FormControl
          v-if="editable"
          type="textarea"
          :rows="5"
          :label="t('page.reservation.notes.special_requests')"
          :model-value="values.special_requests"
          @update:model-value="onEdit('special_requests', $event)"
        />
        <p v-else class="whitespace-pre-line text-p-sm text-ink-gray-8">
          {{ reservation.special_requests || '—' }}
        </p>
      </div>
    </section>

    <section class="rounded border border-outline-gray-1">
      <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
        {{ t('page.reservation.notes.internal') }}
      </h2>

      <div class="space-y-3 p-4">
        <p class="text-p-sm text-ink-gray-6">{{ t('page.reservation.notes.internal_hint') }}</p>

        <FormControl
          v-if="editable"
          type="textarea"
          :rows="5"
          :label="t('page.reservation.notes.internal')"
          :model-value="values.internal_notes"
          @update:model-value="onEdit('internal_notes', $event)"
        />
        <p v-else class="whitespace-pre-line text-p-sm text-ink-gray-8">
          {{ reservation.internal_notes || '—' }}
        </p>
      </div>
    </section>

    <!-- The server's reason for the read-only rendering above. -->
    <p v-if="!editable" class="text-p-sm text-ink-gray-6 lg:col-span-2">
      {{ t('page.reservation.not_editable_here', { status: editability.status }) }}
    </p>
  </div>
</template>

<script setup>
import { FormControl } from 'frappe-ui'
import { computed } from 'vue'

import { t } from '@/utils/i18n'

const props = defineProps({
  reservation: { type: Object, required: true },
  editability: { type: Object, required: true },
  /** Draft-merged values, so an unsaved note survives a tab change. */
  values: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['edit'])

const editable = computed(() => Boolean(props.editability?.may_edit_details))

function onEdit(field, value) {
  emit('edit', { field, value })
}
</script>
