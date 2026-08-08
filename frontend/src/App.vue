<template>
  <FrappeUIProvider>
    <div class="h-full">
      <LoadingState v-if="booting" />

      <ErrorState v-else-if="bootError" :error="bootError" :on-retry="boot" />

      <AppLayout v-else>
        <RouterView />
      </AppLayout>
    </div>
  </FrappeUIProvider>
</template>

<script setup>
import { FrappeUIProvider } from 'frappe-ui'
import { computed, onMounted, ref } from 'vue'
import { RouterView } from 'vue-router'

import AppLayout from '@/components/AppLayout.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { property } from '@/stores/property'
import { session } from '@/stores/session'

const bootError = ref(null)

const booting = computed(() => !(session.isLoaded.value && property.isLoaded.value) && !bootError.value)

async function boot() {
  bootError.value = null

  try {
    // The property context depends on knowing who the user is, so these run in
    // order rather than in parallel.
    await session.load()
    await property.load()
  } catch (error) {
    bootError.value = error
  }
}

onMounted(boot)
</script>
