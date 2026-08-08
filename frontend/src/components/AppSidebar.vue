<!--
  Operational navigation.

  Layout is direction-agnostic: it relies on flex order and logical borders, so
  the whole shell mirrors correctly when `dir="rtl"` is set on the document.
-->
<template>
  <aside
    class="flex w-60 shrink-0 flex-col border-e border-outline-gray-1 bg-surface-menu-bar"
    :aria-label="t('app.name')"
  >
    <div class="flex items-center gap-2 px-4 py-4">
      <div
        class="flex size-8 items-center justify-center rounded bg-surface-gray-7 text-ink-white"
        aria-hidden="true"
      >
        <FeatherIcon name="key" class="size-4" />
      </div>
      <div class="min-w-0">
        <p class="truncate text-base font-semibold text-ink-gray-9">{{ t('app.name') }}</p>
        <p class="truncate text-xs text-ink-gray-5">{{ t('app.tagline') }}</p>
      </div>
    </div>

    <PropertySelector />

    <nav class="flex-1 overflow-y-auto px-2 pb-4">
      <component
        :is="item.href ? 'a' : RouterLink"
        v-for="item in items"
        :key="item.key"
        v-bind="item.href ? { href: item.href } : { to: item.to }"
        class="mb-0.5 flex items-center gap-2 rounded px-2.5 py-1.5 text-p-base text-ink-gray-7 hover:bg-surface-gray-2"
        :active-class="item.href ? undefined : 'bg-surface-selected font-medium text-ink-gray-9'"
      >
        <FeatherIcon :name="item.icon" class="size-4 shrink-0" />
        <span class="truncate">{{ t(item.labelKey) }}</span>
        <FeatherIcon
          v-if="item.href"
          name="external-link"
          class="ms-auto size-3.5 shrink-0 text-ink-gray-4 flip-rtl"
        />
      </component>
    </nav>

    <div class="space-y-1 border-t border-outline-gray-1 p-2">
      <LanguageSwitcher />

      <Dropdown :options="userOptions" placement="top">
        <button
          class="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-start hover:bg-surface-gray-2"
        >
          <Avatar size="sm" :label="user?.full_name || ''" :image="user?.user_image" />
          <span class="min-w-0 flex-1 truncate text-p-sm text-ink-gray-7">
            {{ user?.full_name }}
          </span>
          <FeatherIcon name="more-horizontal" class="size-4 shrink-0 text-ink-gray-5" />
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
import { visibleNavigation } from '@/router/navigation'
import { session } from '@/stores/session'
import { t } from '@/utils/i18n'

const items = computed(() => visibleNavigation(session))
const user = computed(() => session.user.value)

const userOptions = computed(() => [
  {
    label: t('common.logout'),
    icon: 'log-out',
    onClick: () => session.logout(),
  },
])
</script>
