<!--
  Operational navigation.

  A permanently dark rail, so the shell never competes with the record on the
  work surface: at front desk brightness the eye finds "where am I" by tone
  long before it reads a label.

  Layout is direction-agnostic: it relies on flex order and logical properties
  (`border-e`, `ps-*`, `ms-auto`), so the whole shell mirrors correctly when
  `dir="rtl"` is set on the document. Nothing here hardcodes left or right.
-->
<template>
  <aside
    class="flex w-60 shrink-0 flex-col border-e border-navy-950/60 bg-navy-900"
    :aria-label="t('app.name')"
  >
    <div class="flex items-center gap-2.5 px-4 pb-3 pt-4">
      <div
        class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white/10 text-white ring-1 ring-inset ring-white/15"
        aria-hidden="true"
      >
        <FeatherIcon name="key" class="size-[18px]" />
      </div>
      <div class="min-w-0">
        <p class="truncate text-base font-semibold leading-tight text-white">{{ t('app.name') }}</p>
        <p class="truncate text-xs leading-tight text-navy-300">{{ t('app.tagline') }}</p>
      </div>
    </div>

    <PropertySelector />

    <nav class="flex-1 overflow-y-auto px-3 pb-4 pt-1">
      <div v-for="group in groups" :key="group.key" class="mb-4 last:mb-0">
        <p class="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-navy-400">
          {{ t(group.labelKey) }}
        </p>

        <component
          :is="item.href ? 'a' : RouterLink"
          v-for="item in group.items"
          :key="item.key"
          v-bind="item.href ? { href: item.href } : { to: item.to }"
          class="group mb-0.5 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-p-sm font-medium
            text-navy-100 transition-colors hover:bg-white/10 hover:text-white"
          :active-class="item.href ? undefined : 'bg-blue-600 text-white shadow-card hover:bg-blue-600'"
        >
          <FeatherIcon :name="item.icon" class="size-[17px] shrink-0" />
          <span class="min-w-0 flex-1 truncate">{{ t(item.labelKey) }}</span>

          <!--
            Open work, from the counts the dashboard already loaded. Absent
            until then, and never rendered as a zero.
          -->
          <span
            v-if="badgeFor(item.key)"
            class="ms-auto shrink-0 rounded-full bg-white/15 px-1.5 py-0.5 text-[11px]
              font-semibold leading-none text-white"
          >
            {{ badgeFor(item.key) }}
          </span>
          <FeatherIcon
            v-else-if="item.href"
            name="external-link"
            class="ms-auto size-3.5 shrink-0 text-navy-400 flip-rtl"
          />
        </component>
      </div>
    </nav>

    <div class="space-y-1.5 border-t border-white/10 p-3">
      <LanguageSwitcher />

      <Dropdown :options="userOptions" placement="top">
        <button
          class="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-start transition-colors hover:bg-white/10"
        >
          <Avatar size="md" :label="user?.full_name || ''" :image="user?.user_image" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-p-sm font-medium text-white">{{ user?.full_name }}</span>
            <span class="block truncate text-xs text-navy-300">{{ user?.name }}</span>
          </span>
          <FeatherIcon name="chevron-up" class="size-4 shrink-0 text-navy-300" />
        </button>
      </Dropdown>
    </div>
  </aside>
</template>

<script setup>
import { Avatar, Dropdown, FeatherIcon } from 'frappe-ui'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import PropertySelector from '@/components/PropertySelector.vue'
import { visibleNavigationGroups } from '@/router/navigation'
import { session } from '@/stores/session'
import { workload } from '@/stores/workload'
import { t } from '@/utils/i18n'

const groups = computed(() => visibleNavigationGroups(session))
const user = computed(() => session.user.value)

const badgeFor = (key) => workload.badgeFor(key)

const userOptions = computed(() => [
  {
    label: t('common.logout'),
    icon: 'log-out',
    onClick: () => session.logout(),
  },
])
</script>
