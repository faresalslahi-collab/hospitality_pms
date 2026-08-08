<template>
  <StateMessage icon="compass" :title="t('page.not_found.title')" :message="t('page.not_found.message')">
    <Button variant="subtle" @click="router.push({ name: 'Dashboard' })">
      {{ t('page.not_found.back') }}
    </Button>
  </StateMessage>
</template>

<script setup>
import { Button } from 'frappe-ui'
import { useRouter } from 'vue-router'

import StateMessage from '@/components/states/StateMessage.vue'
import { t } from '@/utils/i18n'

const router = useRouter()
</script>
