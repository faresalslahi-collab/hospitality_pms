<!--
  Property context indicator.

  Shows the operating property and, importantly, its business date - which is
  not necessarily today. Front desk staff need to see at a glance which day
  their charges are landing on.
-->
<template>
  <div v-if="active" class="px-2 pb-2">
    <component
      :is="canSwitch ? 'button' : 'div'"
      class="flex w-full items-center gap-2 rounded border border-outline-gray-1 px-2.5 py-1.5 text-start"
      :class="canSwitch ? 'hover:bg-surface-gray-2' : ''"
      @click="canSwitch && (open = true)"
    >
      <FeatherIcon name="map-pin" class="size-4 shrink-0 text-ink-gray-5" />
      <span class="min-w-0 flex-1">
        <span class="block truncate text-p-sm font-medium text-ink-gray-8">
          {{ active.property_name }}
        </span>
        <span class="block truncate text-xs text-ink-gray-5">
          {{ t('common.business_date') }}: {{ formatDate(active.business_date) }}
        </span>
      </span>
      <FeatherIcon v-if="canSwitch" name="chevron-down" class="size-4 shrink-0 text-ink-gray-5" />
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
import { t } from '@/utils/i18n'

const open = ref(false)

const active = computed(() => property.active.value)
const canSwitch = computed(() => property.list.value.length > 1)

function select(name) {
  property.setActive(name)
  open.value = false
}
</script>
