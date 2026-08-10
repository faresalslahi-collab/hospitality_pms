<!--
  One count from the day's position, as a link where the board behind it can
  actually be opened.

  A tile that is a dead end and a tile that goes somewhere look the same at
  rest and separate on hover, so the row stays even.
-->
<template>
  <component
    :is="to ? RouterLink : 'div'"
    v-bind="to ? { to } : {}"
    class="group flex items-center gap-3 rounded-xl border border-outline-gray-1 bg-surface-white px-3.5 py-3 shadow-card"
    :class="to ? 'transition-shadow hover:border-outline-gray-2 hover:shadow-card-hover' : ''"
  >
    <span
      class="flex size-9 shrink-0 items-center justify-center rounded-lg"
      :class="iconClass"
      aria-hidden="true"
    >
      <FeatherIcon :name="icon" class="size-[18px]" />
    </span>

    <!-- The label wraps rather than truncating: "Pending check-outs" cut to
         "Pending ch…" is the same three words as "Pending check-ins". -->
    <span class="min-w-0">
      <span class="block break-words text-xs font-medium leading-tight text-ink-gray-6">{{ label }}</span>
      <span class="mt-1 block truncate text-2xl font-semibold leading-none tracking-tight" :class="tone">
        {{ value }}
      </span>
    </span>
  </component>
</template>

<script setup>
import { FeatherIcon } from 'frappe-ui'
import { RouterLink } from 'vue-router'

defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  icon: { type: String, default: 'circle' },
  iconClass: { type: String, default: 'bg-blue-50 text-blue-600' },
  /** Amber and red are for work still outstanding, never for a plain count. */
  tone: { type: String, default: 'text-ink-gray-9' },
  to: { type: [Object, String], default: null },
})
</script>
