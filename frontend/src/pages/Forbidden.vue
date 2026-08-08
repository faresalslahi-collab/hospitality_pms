<template>
  <PermissionDenied>
    <Button variant="subtle" @click="router.push({ name: 'Dashboard' })">
      {{ t('page.not_found.back') }}
    </Button>
  </PermissionDenied>
</template>

<script setup>
import { Button } from 'frappe-ui'
import { useRouter } from 'vue-router'

import PermissionDenied from '@/components/states/PermissionDenied.vue'
import { t } from '@/utils/i18n'

const router = useRouter()
</script>
