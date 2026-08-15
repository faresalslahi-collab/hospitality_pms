<!--
  The one thing to do next.

  The screen this replaces offered seven identical "Run" buttons and left the
  auditor to work out which one was theirs. This card answers that question
  once: which step, what it does, what the server already knows about it, and a
  button that says what pressing it will do.

  The close step is deliberately a different object — red, with the two dates
  spelled out — because it is the only action on this screen that cannot be
  undone without a manager's reopen.
-->
<template>
  <section
    class="rounded-xl border bg-surface-white p-5 shadow-card"
    :class="isClose ? 'border-outline-red-1' : 'border-outline-blue-1'"
    aria-labelledby="night-audit-current-action"
  >
    <p class="text-xs font-medium uppercase tracking-wide" :class="isClose ? 'text-ink-red-3' : 'text-ink-blue-3'">
      {{ eyebrow }}
    </p>

    <h2 id="night-audit-current-action" class="mt-1 text-xl font-semibold tracking-tight text-ink-gray-9">
      {{ title }}
    </h2>

    <p class="mt-1 max-w-prose text-p-sm text-ink-gray-6">{{ description }}</p>

    <!-- What the server already knows about this step, where it knows anything.
         Figures here are context for the decision, not the day's report. -->
    <dl v-if="context.length" class="mt-4 flex flex-wrap gap-x-6 gap-y-2">
      <div v-for="item in context" :key="item.key" class="min-w-0">
        <dt class="text-xs text-ink-gray-5">{{ item.label }}</dt>
        <dd class="text-p-base font-semibold tabular-nums" :class="item.tone || 'text-ink-gray-9'">
          {{ item.value }}
        </dd>
      </div>
    </dl>

    <!-- The refusal, where there is one. Named before the button it disables, so
         the reason is read first rather than discovered by a dead click. -->
    <p
      v-if="blockedReason"
      class="mt-4 flex items-start gap-2 rounded-lg bg-surface-red-1 px-3 py-2 text-p-sm text-ink-red-3"
    >
      <FeatherIcon name="alert-triangle" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span class="min-w-0">{{ blockedReason }}</span>
    </p>

    <div class="mt-4 flex flex-wrap items-center gap-3">
      <Button
        variant="solid"
        :theme="isClose ? 'red' : 'blue'"
        size="md"
        :loading="loading"
        :disabled="disabled"
        @click="$emit('run')"
      >
        {{ actionLabel }}
      </Button>

      <slot name="secondary" />
    </div>
  </section>
</template>

<script setup>
import { Button, FeatherIcon } from 'frappe-ui'

defineProps({
  /** "Step 4 of 7". */
  eyebrow: { type: String, default: '' },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  /** `{ key, label, value, tone }` — server figures relevant to this step only. */
  context: { type: Array, default: () => [] },
  actionLabel: { type: String, required: true },
  /** Operational wording for why the server will not accept this yet. */
  blockedReason: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  isClose: { type: Boolean, default: false },
})

defineEmits(['run'])
</script>
