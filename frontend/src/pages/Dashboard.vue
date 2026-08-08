<template>
  <div>
    <PageHeader :title="t('page.dashboard.title')" :subtitle="t('page.dashboard.subtitle')">
      <template #actions>
        <Badge variant="subtle" theme="gray">v{{ version }}</Badge>
      </template>
    </PageHeader>

    <div class="p-5">
      <div class="rounded border border-outline-gray-1 p-5">
        <p class="text-p-base text-ink-gray-7">{{ t('page.dashboard.baseline') }}</p>

        <dl class="mt-4 grid gap-4 sm:grid-cols-3">
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('common.language') }}
            </dt>
            <dd class="mt-0.5 text-p-base text-ink-gray-8">{{ session.language.value }}</dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">User</dt>
            <dd class="mt-0.5 truncate text-p-base text-ink-gray-8">
              {{ session.user.value?.full_name }}
            </dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">Roles</dt>
            <dd class="mt-0.5 text-p-base text-ink-gray-8">{{ session.roles.value.length }}</dd>
          </div>
        </dl>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge } from 'frappe-ui'
import { computed } from 'vue'

import PageHeader from '@/components/PageHeader.vue'
import { session } from '@/stores/session'
import { t } from '@/utils/i18n'

const version = computed(() => session.state.system?.app_version || '')
</script>
