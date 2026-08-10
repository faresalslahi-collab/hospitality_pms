<!--
  The one card shell every dashboard panel sits in, so a KPI, a board and a
  table all read as the same object on the canvas.
-->
<template>
  <section
    class="flex flex-col rounded-xl border border-outline-gray-1 bg-surface-white shadow-card"
    :aria-labelledby="title ? headingId : undefined"
  >
    <header
      v-if="title || $slots.header || $slots.action"
      class="flex flex-wrap items-center justify-between gap-2"
      :class="dense ? 'px-4 pb-2 pt-3.5' : 'px-5 pb-3 pt-4'"
    >
      <div class="flex min-w-0 items-center gap-2.5">
        <span
          v-if="icon"
          class="flex size-7 shrink-0 items-center justify-center rounded-lg 2xl:size-8"
          :class="iconClass"
          aria-hidden="true"
        >
          <FeatherIcon :name="icon" class="size-4 2xl:size-[17px]" />
        </span>
        <div class="min-w-0">
          <h2 :id="headingId" class="truncate text-p-sm font-semibold text-ink-gray-8 2xl:text-p-base">
            {{ title }}
          </h2>
          <p v-if="subtitle" class="truncate text-xs text-ink-gray-5">{{ subtitle }}</p>
        </div>
        <slot name="header" />
      </div>

      <!-- Wraps rather than clips: a card action can be a link or a whole
           legend, and a legend that loses its last entry is worse than a
           legend on two lines. -->
      <div class="flex min-w-0 flex-wrap items-center gap-2">
        <slot name="action" />
      </div>
    </header>

    <div class="min-w-0 flex-1" :class="bodyClass">
      <slot />
    </div>
  </section>
</template>

<script setup>
import { FeatherIcon } from 'frappe-ui'
import { computed, useId } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  icon: { type: String, default: '' },
  iconClass: { type: String, default: 'bg-blue-50 text-blue-600' },
  dense: { type: Boolean, default: false },
  /** `false` when the body brings its own padding, as a full-bleed table does. */
  padded: { type: Boolean, default: true },
})

const headingId = useId()

const bodyClass = computed(() => {
  if (!props.padded) return ''

  return props.dense ? 'px-4 pb-3.5' : 'px-5 pb-4'
})
</script>
