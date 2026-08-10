<!--
  Register a new guest.

  The duplicate check is the server's (`guests.create_guest` → `find_duplicates`),
  not a second algorithm written here: the desk and the Desk-side controller must
  agree on what counts as the same person, and two implementations would not stay
  in step. A duplicate-looking payload comes back as `created: false` with scored
  candidates, and the receptionist chooses — open the record we already hold, or
  create anyway. Nothing is merged automatically.

  Identification documents are not on this screen. Whether a user may see them at
  all is a permlevel decision only the server can answer, and it answers it by
  including or omitting the field in `get_guest` — which there is no record to ask
  for yet. They are added from the edit screen, where that answer exists.
-->
<template>
  <div>
    <PageHeader :title="t('page.guest_new.title')" :subtitle="t('page.guest_new.subtitle')">
      <template #actions>
        <Button variant="subtle" @click="router.push({ name: 'Guests' })">{{ t('common.cancel') }}</Button>
        <Button variant="solid" :loading="saving" :disabled="!canSave" @click="submit(false)">
          {{ t('page.guest_new.create') }}
        </Button>
      </template>
    </PageHeader>

    <div class="space-y-4 p-5">
      <GuestForm :form="form" />

      <p class="text-p-sm text-ink-gray-5">{{ t('page.guest_new.identification_hint') }}</p>

      <ErrorMessage :message="errorMessage" />

      <div class="flex justify-end">
        <Button variant="solid" :loading="saving" :disabled="!canSave" @click="submit(false)">
          {{ t('page.guest_new.create') }}
        </Button>
      </div>
    </div>

    <GuestDuplicateDialog
      v-model="duplicatesOpen"
      :duplicates="duplicates"
      :saving="saving"
      :error-message="errorMessage"
      @open-guest="openGuest"
      @create-anyway="submit(true)"
    />
  </div>
</template>

<script setup>
import { Button, ErrorMessage, toast } from 'frappe-ui'
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import GuestDuplicateDialog from '@/components/GuestDuplicateDialog.vue'
import GuestForm from '@/components/GuestForm.vue'
import PageHeader from '@/components/PageHeader.vue'
import { createGuestResource } from '@/resources/guests'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const router = useRouter()
const createGuest = createGuestResource()

const saving = ref(false)
const errorMessage = ref('')
const duplicates = ref([])
const duplicatesOpen = ref(false)

const form = reactive({
  salutation: '',
  first_name: '',
  middle_name: '',
  last_name: '',
  gender: '',
  date_of_birth: '',
  nationality: '',
  preferred_language: '',
  mobile_no: '',
  phone: '',
  email_id: '',
  address_line_1: '',
  address_line_2: '',
  city: '',
  state: '',
  country: '',
  pincode: '',
  guest_type: 'Individual',
  vip_status: '',
  market_segment: '',
  source: '',
  dietary_requirements: '',
  allergies: '',
  accessibility_requirements: '',
  notes: '',
  preferences: [],
})

// A guest needs at least a first or last name (the controller composes the
// display name from them and refuses an empty one). Checking it here only saves
// a round trip; the server still decides.
const canSave = computed(() => Boolean(form.first_name.trim() || form.last_name.trim()))

/**
 * Empty strings are sent as they are rather than stripped.
 *
 * Frappe reads "" as "no value" for dates and links, and keeping the shape
 * identical to the edit screen's payload means one server-side allow list
 * covers both.
 */
function payload() {
  return { ...form }
}

async function submit(ignoreDuplicates) {
  saving.value = true
  errorMessage.value = ''

  try {
    const result = await createGuest.submit({
      guest: payload(),
      ignore_duplicates: ignoreDuplicates ? 1 : 0,
    })

    // Not an error: the server is asking the desk to look before it creates.
    if (!result.created) {
      duplicates.value = result.duplicates || []
      duplicatesOpen.value = true
      return
    }

    toast.success(t('page.guest_new.created'))
    router.push({ name: 'GuestProfile', params: { id: result.guest.name } })
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}

function openGuest(name) {
  duplicatesOpen.value = false
  router.push({ name: 'GuestProfile', params: { id: name } })
}
</script>
