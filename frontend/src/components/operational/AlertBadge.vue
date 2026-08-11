<!--
  "This record carries alerts" — and nothing more (16.7.0 UI kit).

  PRIVACY BOUNDARY. Guest alerts and blacklist entries are the most sensitive
  text in the system, and an operational board is the least controlled place it
  could appear: it is on screen at a counter, in front of the guest, and it
  prints. `services/front_office.get_guest_flags` sends the boards
  `is_blacklisted` and `vip_status` and deliberately never sends a reason; the
  reason stays behind the guest endpoints that authorise reading it.

  This component is built so that boundary cannot be crossed by accident:

  - It accepts no `reason`, `reasons`, `detail`, `notes` or `blacklistReason`
    prop. There is nowhere to put alert text.
  - It has no slot. A caller cannot inject arbitrary content into it.
  - `inheritAttrs` is false, so a stray attribute on the tag — `reason="..."`,
    `title="..."`, `data-note="..."` — is dropped instead of landing in the DOM,
    where it would be readable, inspectable and printable. Callers style the
    surrounding cell, not this badge.

  What it does say: that an alert exists, how many if the server counted them,
  and how severe if the server graded them. Where that hints there is more to
  know, it says so with one generic sentence that is identical for every record,
  so the sentence itself reveals nothing.

  Colour never carries the severity alone: the severity word is always in text.
  It is not, however, printed twice. Where the caller named the alert itself —
  the arrivals board passes `label: t('common.blacklisted')` for the one flag it
  receives — the chip reads "Blacklisted", not "Blacklisted High", which is poor
  copy in English and worse in Arabic. The grade still selects the theme, and it
  stays in the accessible name and the tooltip, so a screen-reader user hears
  "Blacklisted High" and no user anywhere is left with the grade in colour alone.
  A bare presence or a count has no caller wording to lean on, so there the
  severity word is rendered visibly.
-->
<template>
  <Badge v-if="visible" :theme="theme" variant="subtle" :aria-label="accessibleName" :title="tooltip">
    <span>{{ text }}</span>
    <span v-if="visibleSeverityWord" class="font-medium">{{ visibleSeverityWord }}</span>
  </Badge>
</template>

<script setup>
import { Badge } from 'frappe-ui'
import { computed } from 'vue'

import { t } from '@/utils/i18n'

defineOptions({
  // See the note above: attribute fall-through is a leak vector, so it is closed.
  inheritAttrs: false,
})

const props = defineProps({
  /** How many alerts, when the server counted them. `null` means "not counted". */
  count: { type: Number, default: null },
  /** An alert exists, but no count came with it. */
  present: { type: Boolean, default: false },
  /** `high` | `medium` | `low`, and only when the server graded the alert. */
  severity: { type: String, default: '' },
  /** Optional caller-supplied wording, already translated. Never alert content. */
  label: { type: String, default: '' },
  /** Render an explicit "No alerts" state instead of nothing. */
  showNone: { type: Boolean, default: false },
})

/**
 * Badge theme per severity.
 *
 * Mirrors the colour semantics `guests.ALERT_SEVERITY_THEME` already uses for
 * Info/Warning/Critical, so a red badge means the same thing on every screen.
 * An ungraded alert is neutral: inventing urgency the server did not send would
 * be this component making an operational judgement.
 */
const SEVERITY_THEME = {
  high: 'red',
  medium: 'orange',
  low: 'blue',
}

/** A count is only a count when the server sent a real number above zero. */
const counted = computed(() => Number.isFinite(props.count) && props.count > 0)

/** An explicit zero is "no alerts", whatever else was passed. */
const hasAlert = computed(() => counted.value || (props.present && props.count !== 0))

/** Nothing is rendered for a record with no alerts unless the caller asks. */
const visible = computed(() => hasAlert.value || props.showNone)

/** The grade in words. Always computed, so it can never be colour-only. */
const severityWord = computed(() =>
  hasAlert.value && SEVERITY_THEME[props.severity] ? t(`ui.alert_badge.severity.${props.severity}`) : '',
)

/**
 * Whether the chip's visible wording came from the caller.
 *
 * Only when the caller's label is what is actually rendered: a server count
 * outranks the label, so a graded count is not "named by the caller" and keeps
 * its grade on screen.
 */
const labelled = computed(() => hasAlert.value && !counted.value && Boolean(props.label))

/**
 * The grade on screen — suppressed when the caller already named the alert, so
 * "Blacklisted" does not read "Blacklisted High". The grade is never lost: it
 * selects the theme and stays in `accessibleName` and the tooltip.
 */
const visibleSeverityWord = computed(() => (labelled.value ? '' : severityWord.value))

const theme = computed(() => {
  if (!hasAlert.value) return 'gray'

  // Ungraded alerts share the neutral operational theme rather than borrowing
  // a severity colour they were never given.
  return SEVERITY_THEME[props.severity] || 'gray'
})

const text = computed(() => {
  if (!hasAlert.value) return t('ui.alert_badge.none')

  // A count is more informative than a caller's generic wording, so it wins.
  if (counted.value) {
    return props.count === 1 ? t('ui.alert_badge.one') : t('ui.alert_badge.count', { count: props.count })
  }

  return props.label || t('ui.alert_badge.one')
})

/** Meaning in text, never colour alone. */
const accessibleName = computed(() => [text.value, severityWord.value].filter(Boolean).join(' '))

/**
 * The tooltip adds the one generic sentence that says detail exists elsewhere.
 * It is the same sentence for every record, so it discloses nothing about this one.
 */
const tooltip = computed(() =>
  hasAlert.value ? [accessibleName.value, t('ui.alert_badge.restricted')].join(' ') : accessibleName.value,
)
</script>
