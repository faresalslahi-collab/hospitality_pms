<!--
  Merge two guest records into one.

  A merge repoints every reservation, stay and folio that named the source onto
  the target, and retires the source. Getting it wrong costs far more than a
  duplicate record does, which is why this is a deliberate, reason-mandatory
  action reached from the workspace — not a button on the duplicate dialog that
  New Guest already shows.

  **The server is the authority, twice over.** `services.guests.merge_guests`
  refuses anyone outside `MERGE_ROLES`, refuses a guest merged into itself, and
  refuses a blank reason. This dialog is only shown when the workspace payload
  reported `disclosure.merge`, which is navigation comfort and never a security
  boundary: a caller who reaches the endpoint another way is refused there.

  The direction is fixed and stated in words rather than left to a pair of
  identical pickers: the guest whose workspace is open is always the one kept.
  A dialog where either record might be destroyed depending on which field the
  agent filled first is a dialog that will eventually destroy the wrong one.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.guest_profile.merge_title') }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-p-sm text-ink-gray-6">{{ t('page.guest_profile.merge_intro') }}</p>

        <div>
          <span class="text-xs uppercase tracking-wide text-ink-gray-5">
            {{ t('page.guest_profile.merge_target') }}
          </span>
          <p class="mt-0.5 text-p-sm font-medium text-ink-gray-8">
            {{ targetName }} <span class="text-ink-gray-5">· {{ target }}</span>
          </p>
        </div>

        <Autocomplete
          v-model="source"
          :options="options"
          :placeholder="t('page.guest_profile.merge_source_hint')"
          :label="t('page.guest_profile.merge_source')"
          @update:query="onQuery"
        />

        <FormControl
          v-model="reason"
          type="textarea"
          :rows="3"
          :label="t('page.guest_profile.merge_reason')"
          :placeholder="t('page.guest_profile.merge_reason_hint')"
        />

        <p class="text-p-sm text-ink-red-4">{{ t('page.guest_profile.merge_warning') }}</p>

        <ErrorMessage :message="errorMessage" />
      </div>
    </template>

    <template #actions>
      <div class="flex justify-end gap-2">
        <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
        <Button
          variant="solid"
          theme="red"
          :loading="saving"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ t('page.guest_profile.merge_confirm') }}
        </Button>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Autocomplete, Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import { searchGuestsResource } from '@/resources/guests'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** The guest being kept — always the one whose workspace is open. */
  target: { type: String, required: true },
  targetName: { type: String, default: '' },
  saving: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'merge'])

const search = searchGuestsResource()

const source = ref(null)
const reason = ref('')

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

/**
 * The target is filtered out of its own picker.
 *
 * The server refuses a self-merge outright, so this is not the control — it is
 * so the agent is never offered a choice that can only fail.
 */
const options = computed(() =>
  (search.data || [])
    .filter((guest) => guest.name !== props.target)
    .map((guest) => ({
      value: guest.name,
      label: guest.guest_name,
      description: [guest.email_id, guest.mobile_no].filter(Boolean).join(' · '),
    })),
)

const canSubmit = computed(() => Boolean(source.value?.value) && Boolean(reason.value.trim()))

// Cleared on close so a reason typed for one merge cannot be submitted with a
// source picked for another.
watch(open, (value) => {
  if (!value) {
    source.value = null
    reason.value = ''
  }
})

function onQuery(query) {
  if (!query || query.length < 2) return

  search.fetch({ query })
}

function submit() {
  if (!canSubmit.value) return

  emit('merge', { source: source.value.value, reason: reason.value.trim() })
}
</script>
