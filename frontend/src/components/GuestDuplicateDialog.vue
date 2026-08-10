<!--
  Possible existing records for a guest the desk is about to create.

  The server answers a duplicate-looking create with `created: false` and a
  scored candidate list rather than an error, because this is a decision, not a
  failure. The two ways out are both explicit and both taken by a human: open
  the record we already hold, or create a second one anyway.

  Nothing is merged here, and nothing is merged automatically anywhere. A merge
  repoints reservation, stay and folio history onto another guest; getting it
  wrong costs far more than a duplicate record does, so it stays a separate,
  role-gated action (services/guests.py `merge_guests`).

  `match_score` and `match_reasons` come from the server already scored and
  already translated — the frontend only lays them out.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.guest_duplicates.title'), size: '2xl' }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-p-sm text-ink-gray-6">{{ t('page.guest_duplicates.hint') }}</p>

        <div class="divide-y divide-outline-gray-1 rounded border border-outline-gray-1">
          <div
            v-for="candidate in duplicates"
            :key="candidate.name"
            class="flex flex-wrap items-start justify-between gap-3 p-4"
          >
            <div class="min-w-0">
              <p class="font-medium text-ink-gray-9">
                {{ candidate.guest_name }}
                <span class="ms-1 text-p-sm font-normal text-ink-gray-5">{{ candidate.name }}</span>
              </p>
              <p class="mt-0.5 text-p-sm text-ink-gray-6">
                {{ [candidate.email_id, candidate.mobile_no, candidate.nationality].filter(Boolean).join(' · ') || '—' }}
              </p>
              <p class="mt-0.5 text-p-sm text-ink-gray-5">
                {{ t('page.guest_duplicates.stays', { count: candidate.total_stays ?? 0 }) }}
                <template v-if="candidate.last_stay_on">
                  · {{ t('page.guest_duplicates.last_stay', { date: formatDate(candidate.last_stay_on) }) }}
                </template>
              </p>
              <div class="mt-2 flex flex-wrap gap-1">
                <Badge
                  v-for="(reason, index) in candidate.match_reasons || []"
                  :key="index"
                  theme="orange"
                  variant="subtle"
                  :label="reason"
                />
              </div>
            </div>

            <div class="flex shrink-0 flex-col items-end gap-2">
              <Badge
                theme="gray"
                variant="subtle"
                :label="t('page.guest_duplicates.match_score', { score: candidate.match_score })"
              />
              <Button variant="subtle" @click="emit('open-guest', candidate.name)">
                {{ t('page.guest_duplicates.open_guest') }}
              </Button>
            </div>
          </div>
        </div>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" theme="red" :loading="saving" @click="emit('create-anyway')">
            {{ t('page.guest_duplicates.create_anyway') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Badge, Button, Dialog, ErrorMessage } from 'frappe-ui'
import { computed } from 'vue'

import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  duplicates: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
})

// Routing and re-submitting both belong to the page that owns the payload, so
// this dialog only reports which button was pressed.
const emit = defineEmits(['update:modelValue', 'create-anyway', 'open-guest'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
</script>
