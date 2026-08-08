<!--
  Shared presentation for loading, empty, error and permission states so every
  operational screen communicates the same way (Frontend Standards section 3).
-->
<template>
  <div
    class="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center"
    role="status"
    :aria-busy="busy ? 'true' : 'false'"
  >
    <LoadingIndicator v-if="busy" class="size-6 text-ink-gray-5" />
    <FeatherIcon v-else-if="icon" :name="icon" class="size-6" :class="iconClass" />

    <div class="space-y-1">
      <p class="text-base font-medium text-ink-gray-8">{{ title }}</p>
      <p v-if="message" class="max-w-md text-p-sm text-ink-gray-6">{{ message }}</p>
    </div>

    <slot />
  </div>
</template>

<script setup>
import { FeatherIcon, LoadingIndicator } from 'frappe-ui'

defineProps({
  title: { type: String, required: true },
  message: { type: String, default: '' },
  icon: { type: String, default: '' },
  iconClass: { type: String, default: 'text-ink-gray-5' },
  busy: { type: Boolean, default: false },
})
</script>
