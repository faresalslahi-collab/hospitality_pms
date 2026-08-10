<!--
  Correct an existing guest.

  Two things are deliberately not on this screen. Blacklist status is one: the
  flag is permlevel 2 and lifting or placing it is an audited, role-gated
  transition owned by the guest controller, so it is shown here (when the server
  sends it) and changed elsewhere. Stay statistics and the ERPNext Customer link
  are the other: both are rolled up or created by services, and a field the desk
  could type into would put a second, wrong source of truth on the screen.

  Identification is rendered only when `get_guest` actually returned the key.
  An absent key means "you are not cleared for permlevel 1", which is a
  different thing from "this guest has no documents on file" — so the section
  disappears rather than reading as empty.

  The duplicate warning is non-blocking. On an edit the record already exists;
  finding a look-alike is information for the desk, not a reason to refuse a
  correction. `exclude` keeps the guest being edited out of its own results.
-->
<template>
  <div>
    <LoadingState v-if="detail.loading && !detail.data" />
    <ErrorState v-else-if="detail.error" :error="detail.error" :on-retry="load" />

    <div v-else-if="guest">
      <PageHeader :title="t('page.guest_edit.title')" :subtitle="guest.guest_name">
        <template #actions>
          <Badge
            v-if="hasField(guest, 'is_blacklisted') && guest.is_blacklisted"
            theme="red"
            variant="subtle"
            :label="t('page.guest_profile.blacklisted')"
          />
          <Button variant="subtle" @click="router.push({ name: 'GuestProfile', params: { id: guest.name } })">
            {{ t('common.cancel') }}
          </Button>
          <Button variant="solid" :loading="saving" :disabled="!canSave" @click="submit">
            {{ t('common.save') }}
          </Button>
        </template>
      </PageHeader>

      <div class="space-y-4 p-5">
        <div
          v-if="matches.length"
          class="rounded border border-outline-amber-1 bg-surface-amber-1 p-4"
        >
          <p class="text-p-sm font-medium text-ink-amber-3">{{ t('page.guest_edit.duplicate_warning') }}</p>
          <ul class="mt-2 space-y-1">
            <li v-for="candidate in matches" :key="candidate.name" class="flex flex-wrap items-center gap-2">
              <span class="text-p-sm text-ink-gray-8">{{ candidate.guest_name }}</span>
              <span class="text-p-sm text-ink-gray-5">
                {{ (candidate.match_reasons || []).join(' · ') }}
              </span>
              <Button
                variant="ghost"
                @click="router.push({ name: 'GuestProfile', params: { id: candidate.name } })"
              >
                {{ t('page.guest_edit.open_duplicate') }}
              </Button>
            </li>
          </ul>
        </div>

        <div
          v-if="hasField(guest, 'is_blacklisted') && guest.is_blacklisted"
          class="rounded border border-outline-red-1 bg-surface-red-1 p-4"
        >
          <p class="font-medium text-ink-red-4">{{ t('page.guest_profile.blacklist_status') }}</p>
          <p v-if="hasField(guest, 'blacklist_reason') && guest.blacklist_reason" class="mt-1 text-p-sm text-ink-red-4">
            {{ t('page.guest_profile.blacklist_reason') }}: {{ guest.blacklist_reason }}
          </p>
          <p class="mt-1 text-p-sm text-ink-red-4">{{ t('page.guest_edit.blacklist_readonly') }}</p>
        </div>

        <GuestForm :form="form" :show-identification="canEditIdentification" />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="router.push({ name: 'GuestProfile', params: { id: guest.name } })">
            {{ t('common.cancel') }}
          </Button>
          <Button variant="solid" :loading="saving" :disabled="!canSave" @click="submit">
            {{ t('common.save') }}
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge, Button, ErrorMessage, toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import GuestForm from '@/components/GuestForm.vue'
import PageHeader from '@/components/PageHeader.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import {
  findGuestMatchesResource,
  getGuestResource,
  hasField,
  updateGuestResource,
} from '@/resources/guests'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const route = useRoute()
const router = useRouter()

const detail = getGuestResource()
const updateGuest = updateGuestResource()
const findMatches = findGuestMatchesResource()

const saving = ref(false)
const errorMessage = ref('')
const canEditIdentification = ref(false)

let matchTimer = null

/**
 * The fields this screen may write.
 *
 * The same names the server's allow list accepts, so a payload built from this
 * object cannot contain a field `update_guest` would refuse. `identifications`
 * is handled separately because sending it at all depends on the server having
 * shown it to us.
 */
const EDITABLE_FIELDS = [
  'salutation',
  'first_name',
  'middle_name',
  'last_name',
  'gender',
  'date_of_birth',
  'nationality',
  'preferred_language',
  'mobile_no',
  'phone',
  'email_id',
  'address_line_1',
  'address_line_2',
  'city',
  'state',
  'country',
  'pincode',
  'guest_type',
  'vip_status',
  'market_segment',
  'source',
  'dietary_requirements',
  'allergies',
  'accessibility_requirements',
  'notes',
]

const form = reactive({
  ...Object.fromEntries(EDITABLE_FIELDS.map((field) => [field, ''])),
  preferences: [],
  identifications: [],
})

const guest = computed(() => detail.data || null)
const matches = computed(() => findMatches.data || [])

const canSave = computed(() => Boolean(form.first_name.trim() || form.last_name.trim()))

/** The identification number to match on, if the server let us see one. */
const primaryIdNumber = computed(() => {
  if (!canEditIdentification.value) return undefined

  const rows = form.identifications.filter((row) => row.id_number)

  return (rows.find((row) => row.is_primary) || rows[0])?.id_number || undefined
})

function load() {
  return detail.fetch({ guest: route.params.id })
}

/**
 * Copy the server's payload into the editable form.
 *
 * `get_guest` publishes a preference's category as `category`; the DocType calls
 * it `preference_category` and the server accepts either, so it is renamed once
 * here and the form speaks the DocType's language from then on.
 *
 * Each row's `name` is carried through untouched. It is what tells the server
 * "this is the row you sent me", so an unrelated edit updates the row instead
 * of recreating it and resetting the identification verification stamps.
 */
function fill(payload) {
  for (const field of EDITABLE_FIELDS) {
    form[field] = payload[field] ?? ''
  }

  form.preferences = (payload.preferences || []).map((row) => ({
    name: row.name,
    preference_category: row.preference_category || row.category || '',
    preference: row.preference || '',
    notes: row.notes || '',
  }))

  canEditIdentification.value = hasField(payload, 'identifications')

  form.identifications = (payload.identifications || []).map((row) => ({ ...row }))
}

/**
 * Look for other guests that may be the same person.
 *
 * Debounced because it runs while the desk is still typing a corrected name or
 * a new mobile number, and every keystroke is a POST.
 */
function checkMatches() {
  window.clearTimeout(matchTimer)

  matchTimer = window.setTimeout(() => {
    findMatches.submit({
      first_name: form.first_name || undefined,
      last_name: form.last_name || undefined,
      email_id: form.email_id || undefined,
      mobile_no: form.mobile_no || undefined,
      id_number: primaryIdNumber.value,
      date_of_birth: form.date_of_birth || undefined,
      exclude: route.params.id,
    })
  }, 500)
}

async function submit() {
  saving.value = true
  errorMessage.value = ''

  const changes = Object.fromEntries(EDITABLE_FIELDS.map((field) => [field, form[field]]))
  changes.preferences = form.preferences

  // Only offer the table back when the server offered it to us; sending an
  // empty list we were never shown would read as "delete every document".
  if (canEditIdentification.value) {
    changes.identifications = form.identifications
  }

  try {
    await updateGuest.submit({ guest: route.params.id, changes })

    toast.success(t('page.guest_edit.saved'))
    router.push({ name: 'GuestProfile', params: { id: route.params.id } })
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}

watch(
  () => route.params.id,
  async (id) => {
    if (!id) return

    await load()

    if (detail.data) {
      fill(detail.data)
      checkMatches()
    }
  },
  { immediate: true },
)

watch(
  () => [form.first_name, form.last_name, form.email_id, form.mobile_no, form.date_of_birth],
  checkMatches,
)
</script>
