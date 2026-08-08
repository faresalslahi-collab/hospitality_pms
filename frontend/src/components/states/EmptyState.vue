<template>
  <StateMessage
    icon="inbox"
    :title="title || t('state.empty_title')"
    :message="message ?? t('state.empty_message')"
  >
    <slot />
  </StateMessage>
</template>

<script setup>
import StateMessage from '@/components/states/StateMessage.vue'
import { t } from '@/utils/i18n'

defineProps({
  title: { type: String, default: '' },
  message: { type: String, default: undefined },
})
</script>
