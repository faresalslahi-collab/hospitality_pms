<!--
  One counter from the day's position, as an operational card.

  The card is the link, not the chip inside it: a receptionist aims at the whole
  tile, and an anchor nested inside an anchor is invalid markup that assistive
  technology reads twice. The chip at the foot is therefore a span that *names*
  where the card goes — it is the affordance, and the card is the target.

  Read top to bottom the card answers three questions in the order the desk asks
  them: what kind of work is this (icon and title), how much of it is left
  (number), and where do I go to clear it (helper line, then chip).
-->
<template>
  <component
    :is="to ? RouterLink : 'div'"
    v-bind="to ? { to } : {}"
    class="group flex h-full flex-col items-center gap-2 rounded-xl border border-outline-gray-1
      bg-surface-white px-3 py-4 text-center shadow-card"
    :class="to ? 'cursor-pointer transition-shadow hover:border-outline-gray-2 hover:shadow-card-hover' : ''"
  >
    <span
      class="flex size-11 shrink-0 items-center justify-center rounded-full"
      :class="iconClass"
      aria-hidden="true"
    >
      <FeatherIcon :name="icon" class="size-5" />
    </span>

    <!-- The label wraps rather than truncating: "Pending check-outs" cut to
         "Pending ch…" is the same three words as "Pending check-ins". -->
    <span class="block break-words text-xs font-semibold leading-tight text-ink-gray-7">{{ label }}</span>

    <span class="block text-3xl font-semibold leading-none tracking-tight tabular-nums text-ink-gray-9">
      {{ value }}
    </span>

    <span v-if="hint" class="block break-words text-xs leading-tight text-ink-gray-5">{{ hint }}</span>

    <!--
      `mt-auto` so every chip in the row sits on the same baseline however many
      lines the label above it took. A card with no destination shows no chip
      rather than a disabled-looking one.
    -->
    <span
      v-if="to && actionLabel"
      class="mt-auto flex w-full items-center justify-center gap-1 rounded-lg px-2 py-1.5 text-xs
        font-medium transition-colors group-hover:brightness-95"
      :class="actionClass"
    >
      <FeatherIcon :name="actionIcon" class="size-3.5 shrink-0" />
      <span class="min-w-0 truncate">{{ actionLabel }}</span>
      <FeatherIcon name="chevron-right" class="size-3.5 shrink-0 flip-rtl" aria-hidden="true" />
    </span>
  </component>
</template>

<script setup>
import { FeatherIcon } from 'frappe-ui'
import { RouterLink } from 'vue-router'

defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  /** One short operational sentence: what the number is counting, in rooms. */
  hint: { type: String, default: '' },
  icon: { type: String, default: 'circle' },
  iconClass: { type: String, default: 'bg-blue-50 text-blue-600' },
  /** Named for the screen it opens, so the chip reads as an instruction. */
  actionLabel: { type: String, default: '' },
  actionIcon: { type: String, default: 'arrow-right' },
  actionClass: { type: String, default: 'bg-blue-50 text-blue-700' },
  to: { type: [Object, String], default: null },
})
</script>
