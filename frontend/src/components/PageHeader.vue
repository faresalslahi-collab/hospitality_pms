<!--
  Consistent page title, subtitle and action area for every operational page
  (Frontend Standards section 3).
-->
<template>
  <header
    class="flex flex-wrap items-start justify-between gap-3 border-b border-outline-gray-1 px-5 py-4"
  >
    <div class="min-w-0">
      <h1 class="truncate text-lg font-semibold text-ink-gray-9">{{ title }}</h1>
      <p v-if="subtitle" class="mt-0.5 text-p-sm text-ink-gray-6">{{ subtitle }}</p>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>
