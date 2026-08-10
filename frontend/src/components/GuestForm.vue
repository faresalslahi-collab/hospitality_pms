<!--
  Guest details, shared by the create and edit screens.

  Fields and validation *display* only. Nothing here decides whether a value is
  acceptable: the guest controller composes the display name, normalises the
  contact fields and enforces the identification rules, and its refusal is what
  the user is shown (Frontend Standards section 5, CLAUDE.md layering).

  The parent owns `form` and submits it, so the same object is what the server
  receives — there is no second, divergent copy of the payload in here.

  `showIdentification` is driven by the server's answer, never by a role check
  in the browser: `get_guest` omits the `identifications` key entirely for a
  user who is not cleared for permlevel 1, and an editable section for a table
  that user cannot read would only produce writes the server discards.
-->
<template>
  <div class="space-y-5">
    <section class="space-y-3 rounded border border-outline-gray-1 p-4">
      <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.guest_form.identity') }}</p>

      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <FormControl
          v-model="form.salutation"
          type="select"
          :label="t('page.guest_form.salutation')"
          :options="salutationOptions"
        />
        <FormControl v-model="form.first_name" type="text" :label="t('page.guest_form.first_name')" />
        <FormControl v-model="form.middle_name" type="text" :label="t('page.guest_form.middle_name')" />
        <FormControl v-model="form.last_name" type="text" :label="t('page.guest_form.last_name')" />
        <FormControl
          v-model="form.gender"
          type="select"
          :label="t('page.guest_form.gender')"
          :options="genderOptions"
        />
        <FormControl v-model="form.date_of_birth" type="date" :label="t('page.guest_form.date_of_birth')" />
        <FormControl
          v-model="form.nationality"
          type="select"
          :label="t('page.guest_form.nationality')"
          :options="countryOptions"
        />
        <FormControl
          v-model="form.preferred_language"
          type="select"
          :label="t('page.guest_form.preferred_language')"
          :options="languageOptions"
        />
      </div>
    </section>

    <section class="space-y-3 rounded border border-outline-gray-1 p-4">
      <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.guest_form.contact') }}</p>

      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <FormControl v-model="form.mobile_no" type="text" :label="t('page.guest_form.mobile_no')" />
        <FormControl v-model="form.phone" type="text" :label="t('page.guest_form.phone')" />
        <FormControl v-model="form.email_id" type="text" :label="t('page.guest_form.email_id')" />
        <FormControl v-model="form.address_line_1" type="text" :label="t('page.guest_form.address_line_1')" />
        <FormControl v-model="form.address_line_2" type="text" :label="t('page.guest_form.address_line_2')" />
        <FormControl v-model="form.city" type="text" :label="t('page.guest_form.city')" />
        <FormControl v-model="form.state" type="text" :label="t('page.guest_form.state')" />
        <FormControl
          v-model="form.country"
          type="select"
          :label="t('page.guest_form.country')"
          :options="countryOptions"
        />
        <FormControl v-model="form.pincode" type="text" :label="t('page.guest_form.pincode')" />
      </div>
    </section>

    <section class="space-y-3 rounded border border-outline-gray-1 p-4">
      <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.guest_form.classification') }}</p>

      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FormControl
          v-model="form.guest_type"
          type="select"
          :label="t('page.guest_form.guest_type')"
          :options="guestTypeOptions"
        />
        <FormControl
          v-model="form.vip_status"
          type="select"
          :label="t('page.guest_form.vip_status')"
          :options="vipStatusOptions"
        />
        <FormControl v-model="form.market_segment" type="text" :label="t('page.guest_form.market_segment')" />
        <FormControl v-model="form.source" type="text" :label="t('page.guest_form.source')" />
      </div>
    </section>

    <section v-if="showIdentification" class="space-y-3 rounded border border-outline-gray-1 p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.guest_form.identification') }}</p>
        <Button variant="subtle" @click="addIdentification">{{ t('page.guest_form.add_identification') }}</Button>
      </div>

      <p v-if="!form.identifications.length" class="text-p-sm text-ink-gray-5">
        {{ t('page.guest_form.no_identifications') }}
      </p>

      <div
        v-for="(row, index) in form.identifications"
        :key="index"
        class="space-y-3 rounded border border-outline-gray-1 p-3"
      >
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <FormControl
            v-model="row.id_type"
            type="select"
            :label="t('page.guest_form.id_type')"
            :options="idTypeOptions"
          />
          <FormControl v-model="row.id_number" type="text" :label="t('page.guest_form.id_number')" />
          <FormControl
            v-model="row.issuing_country"
            type="select"
            :label="t('page.guest_form.issuing_country')"
            :options="countryOptions"
          />
          <FormControl v-model="row.issue_date" type="date" :label="t('page.guest_form.issue_date')" />
          <FormControl v-model="row.expiry_date" type="date" :label="t('page.guest_form.expiry_date')" />
        </div>

        <div class="flex flex-wrap items-center gap-4">
          <FormControl v-model="row.is_primary" type="checkbox" :label="t('page.guest_form.is_primary')" />
          <FormControl v-model="row.verified" type="checkbox" :label="t('page.guest_form.verified')" />
          <Button class="ms-auto" variant="ghost" theme="red" @click="form.identifications.splice(index, 1)">
            {{ t('common.remove') }}
          </Button>
        </div>
      </div>
    </section>

    <section class="space-y-3 rounded border border-outline-gray-1 p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.guest_form.preferences') }}</p>
        <Button variant="subtle" @click="addPreference">{{ t('page.guest_form.add_preference') }}</Button>
      </div>

      <p v-if="!form.preferences.length" class="text-p-sm text-ink-gray-5">
        {{ t('page.guest_form.no_preferences') }}
      </p>

      <div v-for="(row, index) in form.preferences" :key="index" class="grid items-end gap-3 sm:grid-cols-4">
        <FormControl
          v-model="row.preference_category"
          type="select"
          :label="t('page.guest_form.preference_category')"
          :options="preferenceCategoryOptions"
        />
        <FormControl v-model="row.preference" type="text" :label="t('page.guest_form.preference')" />
        <FormControl v-model="row.notes" type="text" :label="t('common.notes')" />
        <Button variant="ghost" theme="red" @click="form.preferences.splice(index, 1)">
          {{ t('common.remove') }}
        </Button>
      </div>
    </section>

    <section class="space-y-3 rounded border border-outline-gray-1 p-4">
      <p class="text-p-sm font-medium text-ink-gray-8">{{ t('page.guest_form.requirements') }}</p>

      <div class="grid gap-3 sm:grid-cols-3">
        <FormControl
          v-model="form.dietary_requirements"
          type="textarea"
          rows="2"
          :label="t('page.guest_form.dietary_requirements')"
        />
        <FormControl v-model="form.allergies" type="textarea" rows="2" :label="t('page.guest_form.allergies')" />
        <FormControl
          v-model="form.accessibility_requirements"
          type="textarea"
          rows="2"
          :label="t('page.guest_form.accessibility_requirements')"
        />
      </div>

      <FormControl v-model="form.notes" type="textarea" rows="3" :label="t('page.guest_form.notes')" />
    </section>
  </div>
</template>

<script setup>
import { Button, FormControl } from 'frappe-ui'
import { computed } from 'vue'

import { listResource } from '@/resources'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** Reactive payload owned by the parent page; this component mutates it in place. */
  form: { type: Object, required: true },
  /** Render the identification table. Comes from the server's payload, not from a role check. */
  showIdentification: { type: Boolean, default: false },
})

// Link targets are read straight from their DocTypes so a country or salutation
// added in Setup appears here without a frontend change. `pageLength` is raised
// because these are complete reference lists, not paginated operational data.
const countries = listResource('Country', { fields: ['name'], orderBy: 'name asc', pageLength: 500, auto: true })
const salutations = listResource('Salutation', { fields: ['name'], orderBy: 'name asc', pageLength: 100, auto: true })
const genders = listResource('Gender', { fields: ['name'], orderBy: 'name asc', pageLength: 100, auto: true })
const languages = listResource('Language', {
  fields: ['name', 'language_name'],
  orderBy: 'language_name asc',
  pageLength: 500,
  auto: true,
})

/**
 * Select options with a leading "not selected" entry.
 *
 * Every one of these fields is optional on the DocType, so the user must be
 * able to get back to "no value" after picking one by mistake.
 */
function withBlank(options) {
  return [{ label: t('page.guest_form.not_selected'), value: '' }, ...options]
}

function linkOptions(resource, labelField = 'name') {
  return withBlank((resource.data || []).map((row) => ({ label: row[labelField] || row.name, value: row.name })))
}

const countryOptions = computed(() => linkOptions(countries))
const salutationOptions = computed(() => linkOptions(salutations))
const genderOptions = computed(() => linkOptions(genders))
const languageOptions = computed(() => linkOptions(languages, 'language_name'))

// Select options are mirrored from the DocType. They are display choices only —
// the server rejects anything outside them, so this list cannot widen what is
// actually accepted.
const guestTypeOptions = withBlank(
  ['Individual', 'Corporate Guest', 'Travel Agent Guest', 'Group Guest', 'Staff', 'Owner'].map((value) => ({
    label: value,
    value,
  })),
)

const vipStatusOptions = withBlank(
  ['VIP', 'VVIP', 'Loyalty Member', 'Repeat Guest'].map((value) => ({ label: value, value })),
)

const idTypeOptions = ['Passport', 'National ID', 'Residence Permit', 'Driving Licence', 'Other'].map((value) => ({
  label: value,
  value,
}))

const preferenceCategoryOptions = [
  'Room',
  'Bedding',
  'Housekeeping',
  'Food and Beverage',
  'Accessibility',
  'Communication',
  'Other',
].map((value) => ({ label: value, value }))

function addIdentification() {
  props.form.identifications.push({
    id_type: 'Passport',
    id_number: '',
    issuing_country: '',
    issue_date: '',
    expiry_date: '',
    is_primary: 0,
    verified: 0,
  })
}

function addPreference() {
  props.form.preferences.push({ preference_category: 'Room', preference: '', notes: '' })
}
</script>
