<!--
  Consistent page title, subtitle and action area for every operational page
  (Frontend Standards section 3).

  Sticky, on white, above a tinted canvas: the title and the actions stay
  reachable while a long board scrolls under them, which is what a desk
  working a 200-row arrivals list actually needs.
-->
<template>
  <header
    class="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-outline-gray-1
      bg-surface-white px-5 py-3.5"
  >
    <div class="min-w-0">
      <h1 class="truncate text-xl font-semibold tracking-tight text-ink-gray-9">{{ title }}</h1>
      <p v-if="subtitle" class="mt-0.5 truncate text-p-sm text-ink-gray-6">{{ subtitle }}</p>
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
