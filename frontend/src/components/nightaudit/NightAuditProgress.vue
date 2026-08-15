<!--
  The seven steps of a close, as a rail.

  Every state on this rail is the server's. A step shows a tick because the audit
  record carries the stamp the service wrote when that step completed — never
  because the audit has reached some later status. That distinction is the whole
  point of the component: the rail it replaces derived completion from
  `audit_status`, and because one status spans more than one step it showed
  "Mark No-shows" complete for a sweep that had never run.

  Six states, and `recorded` is the one worth explaining. A stamp on a step
  *after* the current one is real evidence and is never hidden — but drawn in the
  ordinary green it claims the operator has already been through it, which they
  have not. It is drawn in amber instead, with its own words. Nothing is
  falsified in either direction: the evidence shows, and so does the fact that
  the sequence did not produce it.

  Horizontal on a wide screen, where the sequence reads as a sequence. Vertical
  below that, because seven labels squeezed onto a tablet are seven labels nobody
  can read. Both orders are flex, so an Arabic session mirrors with no second
  stylesheet.
-->
<template>
  <ol class="flex flex-col gap-1 lg:flex-row lg:items-start lg:gap-0">
    <li
      v-for="(step, index) in steps"
      :key="step.key"
      class="flex min-w-0 items-center gap-2.5 lg:flex-1 lg:flex-col lg:items-center lg:gap-1.5 lg:text-center"
      :data-step="step.key"
      :data-state="step.state"
      :aria-current="step.state === 'current' ? 'step' : undefined"
    >
      <!-- The marker and its connector. On a wide screen the connector runs
           between markers; the first step has nothing to its reading-near side
           and the last nothing to its far side. -->
      <div class="flex shrink-0 items-center gap-0 lg:w-full lg:justify-center">
        <span class="hidden h-px flex-1 lg:block" :class="index === 0 ? 'bg-transparent' : connector(step)" />

        <span
          class="flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
          :class="marker(step)"
        >
          <FeatherIcon v-if="step.state === 'done'" name="check" class="size-3.5" />
          <!-- A tick the operator has not walked past yet: same evidence, different
               reading. `rotate-ccw` says "this was recorded before now" without the
               alarm of a warning triangle. -->
          <FeatherIcon v-else-if="step.state === 'recorded'" name="rotate-ccw" class="size-3.5" />
          <FeatherIcon v-else-if="step.state === 'blocked'" name="alert-triangle" class="size-3.5" />
          <span v-else>{{ step.position }}</span>
        </span>

        <span
          class="hidden h-px flex-1 lg:block"
          :class="index === steps.length - 1 ? 'bg-transparent' : connector(steps[index + 1])"
        />
      </div>

      <div class="min-w-0 lg:w-full lg:px-1">
        <p class="truncate text-p-sm lg:text-xs" :class="labelClass(step)">{{ step.label }}</p>
        <!-- Named, not just coloured: colour is never the only channel. -->
        <p v-if="step.state !== 'pending'" class="truncate text-[11px]" :class="stateClass(step)">
          {{ step.stateLabel }}
        </p>
      </div>
    </li>
  </ol>
</template>

<script setup>
import { FeatherIcon } from 'frappe-ui'

defineProps({
  /** Steps from `auditStepStates`, already labelled by the page. */
  steps: { type: Array, default: () => [] },
})

function marker(step) {
  if (step.state === 'done') return 'bg-surface-green-1 text-ink-green-3 ring-1 ring-inset ring-outline-green-1'
  // Amber, not green and not red: the step really did complete, so it is not a
  // failure, but it sits ahead of the marker and must not read as progress the
  // operator has made.
  if (step.state === 'recorded') return 'bg-surface-amber-1 text-ink-amber-3 ring-1 ring-inset ring-outline-amber-1'
  if (step.state === 'blocked') return 'bg-surface-red-1 text-ink-red-3 ring-1 ring-inset ring-outline-red-1'
  if (step.state === 'current') return 'bg-ink-blue-3 text-white ring-4 ring-surface-blue-1'
  return 'bg-surface-gray-2 text-ink-gray-5'
}

/** A connector is "travelled" only up to the step that has actually completed. */
function connector(step) {
  return step?.state === 'done' ? 'bg-outline-green-1' : 'bg-outline-gray-2'
}

function labelClass(step) {
  if (step.state === 'current') return 'font-semibold text-ink-gray-9'
  if (step.state === 'recorded') return 'text-ink-gray-7'
  if (step.state === 'pending') return 'text-ink-gray-5'
  if (step.state === 'blocked') return 'font-medium text-ink-red-3'
  return 'text-ink-gray-7'
}

function stateClass(step) {
  if (step.state === 'blocked') return 'text-ink-red-3'
  if (step.state === 'recorded') return 'text-ink-amber-3'
  if (step.state === 'current') return 'text-ink-blue-3'
  return 'text-ink-gray-5'
}
</script>
