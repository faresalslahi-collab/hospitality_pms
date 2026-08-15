<!--
  Property context indicator.

  Shows the operating property and, importantly, its business date - which is
  not necessarily today. Front desk staff need to see at a glance which day
  their charges are landing on, so the date is given the emphasis normally
  reserved for a title rather than being tucked under one.

  Lives inside the dark navigation rail, and is styled for it.
-->
<template>
  <div v-if="active" class="px-3 pb-3">
    <component
      :is="canSwitch ? 'button' : 'div'"
      class="relative flex w-full items-stretch gap-3 overflow-hidden rounded-xl bg-navy-800 p-3 text-start
        ring-1 ring-inset ring-white/10 transition-colors"
      :class="canSwitch ? 'hover:bg-navy-700' : ''"
      @click="canSwitch && (open = true)"
    >
      <span class="min-w-0 flex-1">
        <span class="flex items-center gap-1.5">
          <span class="truncate text-p-base font-semibold text-white">
            {{ active.property_name }}
          </span>
          <FeatherIcon
            v-if="canSwitch"
            name="chevron-down"
            class="size-4 shrink-0 text-navy-300"
          />
        </span>

        <span class="mt-2 block text-[11px] uppercase tracking-wider text-navy-300">
          {{ t('common.business_date') }}
        </span>
        <span class="mt-0.5 flex items-center gap-1.5">
          <FeatherIcon name="calendar" class="size-3.5 shrink-0 text-navy-300" />
          <span class="truncate text-p-sm font-semibold text-white">
            {{ formatDate(active.business_date) }}
          </span>
        </span>

        <!--
          The gap between the operating day and the real one, said plainly and
          only when there is one.

          It sits with the business date because that is the figure it qualifies
          — a date the desk would otherwise read as current. It reports the lag;
          it does not cause it and cannot close it. Only the Night Audit moves a
          business date forward.
        -->
        <span
          v-if="lag"
          class="mt-2 flex items-start gap-1.5 rounded-lg bg-amber-400/15 px-2 py-1 text-[11px]
            leading-tight text-amber-200 ring-1 ring-inset ring-amber-400/25"
        >
          <FeatherIcon name="alert-triangle" class="mt-px size-3 shrink-0" aria-hidden="true" />
          <span class="min-w-0">{{ tCount('common.audit_lag', lag) }}</span>
        </span>
      </span>

      <!--
        A property mark, not a photograph: Property carries no image field, and
        inventing one would put a picture of a hotel nobody chose on the screen.
      -->
      <span
        class="flex w-11 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-navy-500 to-navy-700
          ring-1 ring-inset ring-white/10"
        aria-hidden="true"
      >
        <FeatherIcon name="home" class="size-5 text-white/70" />
      </span>
    </component>

    <Dialog v-model="open" :options="{ title: t('common.property') }">
      <template #body-content>
        <div class="space-y-1">
          <button
            v-for="item in property.list.value"
            :key="item.name"
            class="flex w-full items-center justify-between gap-2 rounded px-3 py-2 text-start hover:bg-surface-gray-2"
            @click="select(item.name)"
          >
            <span class="min-w-0">
              <span class="block truncate text-p-base text-ink-gray-8">{{ item.property_name }}</span>
              <span class="block truncate text-xs text-ink-gray-5">{{ item.property_code }}</span>
            </span>
            <FeatherIcon
              v-if="item.name === property.activeName.value"
              name="check"
              class="size-4 shrink-0 text-ink-green-3"
            />
          </button>
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { Dialog, FeatherIcon } from 'frappe-ui'
import { computed, ref } from 'vue'

import { property } from '@/stores/property'
import { formatDate } from '@/utils/format'
import { t, tCount } from '@/utils/i18n'

const open = ref(false)

const active = computed(() => property.active.value)
const canSwitch = computed(() => property.list.value.length > 1)

/** Days the operating day is behind the property's calendar day; 0 when level. */
const lag = computed(() => property.businessDateLag.value)

function select(name) {
  property.setActive(name)
  open.value = false
}
</script>
