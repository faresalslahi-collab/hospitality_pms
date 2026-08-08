<template>
  <StateMessage
    icon="lock"
    icon-class="text-ink-amber-3"
    :title="t('state.denied_title')"
    :message="message ?? t('state.denied_message')"
  >
    <slot />
  </StateMessage>
</template>

<script setup>
import StateMessage from '@/components/states/StateMessage.vue'
import { t } from '@/utils/i18n'

defineProps({
  message: { type: String, default: undefined },
})
</script>
