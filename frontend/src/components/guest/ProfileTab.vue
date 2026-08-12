<!--
  Profile: the guest's own record, as labelled pairs.

  Read-only. Editing goes through the existing `GuestEdit` route and its shared
  `GuestForm`, which already owns the write allow list the server enforces — a
  second editor here would be a second place for those two lists to drift apart.

  The fields rendered are the ones the server chose to send (`PROFILE_FIELDS`),
  not every column on the Guest DocType. Blank values show as an em dash because
  every field here is permlevel 0 and was disclosed: an empty `city` genuinely
  means no city on file. That is the opposite of the rule on the Identity and
  Alerts tabs, where a *missing block* means "not shown to you" and must never be
  drawn as an empty one.
-->
<template>
  <div class="space-y-6">
    <section v-for="group in groups" :key="group.key">
      <h3 class="mb-2 text-xs uppercase tracking-wide text-ink-gray-5">{{ group.label }}</h3>

      <dl class="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="field in group.fields" :key="field.key">
          <dt class="text-xs text-ink-gray-5">{{ field.label }}</dt>
          <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ field.value }}</dd>
        </div>
      </dl>
    </section>

    <section v-if="care">
      <h3 class="mb-2 text-xs uppercase tracking-wide text-ink-gray-5">
        {{ t('page.guest_profile.section_care') }}
      </h3>

      <dl class="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-3">
        <div v-for="field in careFields" :key="field.key">
          <dt class="text-xs text-ink-gray-5">{{ field.label }}</dt>
          <dd class="mt-0.5 whitespace-pre-line text-p-sm text-ink-gray-8">{{ field.value }}</dd>
        </div>
      </dl>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'

import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The `guest` block from the workspace payload. */
  guest: { type: Object, default: () => ({}) },
  /** The `care` block: dietary, allergies, accessibility. */
  care: { type: Object, default: null },
  /** `standing`, for the two classification fields that live there. */
  standing: { type: Object, default: () => ({}) },
})

const DASH = '—'

function value(field, format) {
  const raw = props.guest?.[field]

  if (raw === null || raw === undefined || raw === '') return DASH

  return format ? format(raw) : String(raw)
}

const groups = computed(() => [
  {
    key: 'identity',
    label: t('page.guest_profile.section_identity'),
    fields: [
      { key: 'salutation', label: t('page.guest_profile.salutation'), value: value('salutation') },
      { key: 'first_name', label: t('page.guest_profile.first_name'), value: value('first_name') },
      { key: 'middle_name', label: t('page.guest_profile.middle_name'), value: value('middle_name') },
      { key: 'last_name', label: t('page.guest_profile.last_name'), value: value('last_name') },
      { key: 'gender', label: t('page.guest_profile.gender'), value: value('gender') },
      {
        key: 'date_of_birth',
        label: t('page.guest_profile.date_of_birth'),
        value: value('date_of_birth', formatDate),
      },
      { key: 'nationality', label: t('page.guest_profile.nationality'), value: value('nationality') },
      {
        key: 'preferred_language',
        label: t('page.guest_profile.preferred_language'),
        value: value('preferred_language'),
      },
    ],
  },
  {
    key: 'contact',
    label: t('page.guest_profile.section_contact'),
    fields: [
      { key: 'mobile_no', label: t('page.guest_profile.mobile'), value: value('mobile_no') },
      { key: 'phone', label: t('page.guest_profile.phone'), value: value('phone') },
      { key: 'email_id', label: t('page.guest_profile.email'), value: value('email_id') },
    ],
  },
  {
    key: 'address',
    label: t('page.guest_profile.section_address'),
    fields: [
      {
        key: 'address_line_1',
        label: t('page.guest_profile.address_line_1'),
        value: value('address_line_1'),
      },
      {
        key: 'address_line_2',
        label: t('page.guest_profile.address_line_2'),
        value: value('address_line_2'),
      },
      { key: 'city', label: t('page.guest_profile.city'), value: value('city') },
      { key: 'state', label: t('page.guest_profile.state'), value: value('state') },
      { key: 'country', label: t('page.guest_profile.country'), value: value('country') },
      { key: 'pincode', label: t('page.guest_profile.pincode'), value: value('pincode') },
    ],
  },
  {
    key: 'classification',
    label: t('page.guest_profile.section_classification'),
    fields: [
      {
        key: 'guest_type',
        label: t('page.guest_profile.guest_type'),
        value: props.standing?.guest_type || DASH,
      },
      {
        key: 'vip_status',
        label: t('page.guest_profile.vip_status'),
        value: props.standing?.vip_status || DASH,
      },
      {
        key: 'market_segment',
        label: t('page.guest_profile.market_segment'),
        value: value('market_segment'),
      },
      { key: 'source', label: t('page.guest_profile.source'), value: value('source') },
      {
        key: 'originating_property',
        label: t('page.guest_profile.originating_property'),
        value: value('originating_property'),
      },
    ],
  },
])

const careFields = computed(() => [
  {
    key: 'dietary_requirements',
    label: t('page.guest_profile.dietary_requirements'),
    value: props.care?.dietary_requirements || DASH,
  },
  {
    key: 'allergies',
    label: t('page.guest_profile.allergies'),
    value: props.care?.allergies || DASH,
  },
  {
    key: 'accessibility_requirements',
    label: t('page.guest_profile.accessibility_requirements'),
    value: props.care?.accessibility_requirements || DASH,
  },
])
</script>
