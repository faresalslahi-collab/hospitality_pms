<!--
  Step rail for the walk-in wizard.

  Presentation only: it never decides whether a step may be entered. The page
  owns that, because "can I move on" depends on what the server has answered so
  far, not on where the agent clicked.

  The connector between steps is a plain rule rather than a chevron so the rail
  reads the same left-to-right and right-to-left; nothing here points at a
  direction.
-->
<template>
  <ol class="flex flex-wrap items-center gap-2">
    <li v-for="(step, index) in steps" :key="step.key" class="flex flex-1 items-center gap-2">
      <button
        type="button"
        class="flex items-center gap-2 rounded px-2 py-1 text-start transition-colors"
        :class="[
          index === current ? 'bg-surface-gray-2' : '',
          isReachable(index) ? 'hover:bg-surface-gray-1' : 'cursor-default',
        ]"
        :disabled="!isReachable(index)"
        :aria-current="index === current ? 'step' : undefined"
        @click="isReachable(index) && emit('select', index)"
      >
        <span
          class="flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-medium"
          :class="
            index < current
              ? 'bg-surface-green-3 text-ink-white'
              : index === current
                ? 'bg-surface-gray-7 text-ink-white'
                : 'bg-surface-gray-2 text-ink-gray-5'
          "
        >
          <FeatherIcon v-if="index < current" name="check" class="size-3.5" />
          <template v-else>{{ index + 1 }}</template>
        </span>

        <span
          class="truncate text-p-sm"
          :class="index <= current ? 'font-medium text-ink-gray-8' : 'text-ink-gray-5'"
        >
          {{ step.label }}
        </span>
      </button>

      <span v-if="index < steps.length - 1" class="h-px min-w-4 flex-1 bg-outline-gray-2" aria-hidden="true" />
    </li>
  </ol>
</template>

<script setup>
import { FeatherIcon } from 'frappe-ui'

const props = defineProps({
  /** `[{ key, label }]`, already translated by the page. */
  steps: { type: Array, required: true },
  /** Zero-based index of the step being shown. */
  current: { type: Number, required: true },
  /** Highest index the page will allow the agent to jump to. */
  furthest: { type: Number, default: 0 },
})

const emit = defineEmits(['select'])

// Going back is always allowed; going forward only as far as the page says.
function isReachable(index) {
  return index <= Math.max(props.current, props.furthest)
}
</script>
