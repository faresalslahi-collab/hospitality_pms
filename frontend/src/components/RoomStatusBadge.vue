<!--
  A room status value, rendered the same way everywhere.

  Colour alone never carries the meaning: the label is always present, which
  matters for colour-blind users and for printed shift reports
  (Frontend Standards section 12).
-->
<template>
  <Badge :theme="statusTheme(status)" variant="subtle" :label="status" />
</template>

<script setup>
import { Badge } from 'frappe-ui'

import { statusTheme } from '@/resources/rooms'

defineProps({
  status: { type: String, required: true },
})
</script>
