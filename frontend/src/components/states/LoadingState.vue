<template>
  <StateMessage busy :title="title || t('state.loading_title')" :message="message ?? t('state.loading_message')" />
</template>

<script setup>
import StateMessage from '@/components/states/StateMessage.vue'
import { t } from '@/utils/i18n'

defineProps({
  title: { type: String, default: '' },
  message: { type: String, default: undefined },
})
</script>
