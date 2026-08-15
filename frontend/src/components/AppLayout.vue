<!--
  Shell for every operational page: navigation, a mobile drawer for tablet use
  on housekeeping and maintenance rounds, and a scrolling content area.
-->
<template>
  <div class="flex h-full overflow-hidden bg-surface-white">
    <AppSidebar class="hidden md:flex" />

    <!-- Mobile / tablet drawer -->
    <Transition
      enter-active-class="transition-opacity duration-150"
      leave-active-class="transition-opacity duration-150"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div v-if="drawerOpen" class="fixed inset-0 z-40 md:hidden">
        <div class="absolute inset-0 bg-black/30" @click="drawerOpen = false" />
        <AppSidebar class="absolute inset-y-0 start-0 flex shadow-xl" />
      </div>
    </Transition>

    <div class="flex min-w-0 flex-1 flex-col">
      <div class="flex items-center gap-2 bg-navy-900 px-3 py-2 md:hidden">
        <Button variant="ghost" :aria-label="t('app.name')" @click="drawerOpen = true">
          <template #icon><FeatherIcon name="menu" class="size-4 text-white" /></template>
        </Button>
        <span class="truncate text-base font-semibold text-white">{{ t('app.name') }}</span>
      </div>

      <!--
        No global search bar here.

        The shell used to carry one above every page, which made a box for
        finding *any* record the first thing on screens that already have their
        own, better-scoped search — the reservations filter, the guest lookup,
        every board's column search. Two search boxes stacked a few pixels apart,
        answering different questions, is a screen that has to be explained.

        Global search now lives on the Command Center alone, under its header,
        placed by the page (`pages/Dashboard.vue`). The Command Center is where
        somebody arrives without knowing which screen they need; everywhere else
        the page's own control is the right one. That also keeps it to a single
        mounted instance — two would each hold their own open panel and their own
        live region.
      -->
      <main class="min-h-0 flex-1 overflow-y-auto">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup>
import { Button, FeatherIcon } from 'frappe-ui'
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppSidebar from '@/components/AppSidebar.vue'
import { t } from '@/utils/i18n'

const drawerOpen = ref(false)
const route = useRoute()

// Navigating from the drawer should close it, otherwise it covers the page the
// user just asked for.
watch(() => route.fullPath, () => (drawerOpen.value = false))
</script>
