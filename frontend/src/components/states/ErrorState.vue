<!--
  Failures that need user action are shown in place, not as a transient toast
  (Frontend Standards section 13).
-->
<template>
  <StateMessage
    :icon="details.kind === 'permission' ? 'lock' : 'alert-triangle'"
    icon-class="text-ink-red-3"
    :title="details.title"
    :message="details.message"
  >
    <Button v-if="details.retryable && onRetry" variant="subtle" @click="onRetry">
      {{ t('common.retry') }}
    </Button>
    <slot />
  </StateMessage>
</template>

<script setup>
import { Button } from 'frappe-ui'
import { computed } from 'vue'

import StateMessage from '@/components/states/StateMessage.vue'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  error: { type: [Object, String], default: null },
  onRetry: { type: Function, default: null },
})

const details = computed(() => normaliseError(props.error))
</script>
