<!-- Resolve one Night Audit exception. A note is always required (SAD audit rules). -->
<template>
  <Dialog v-model="open" :options="{ title: t('page.night_audit.resolve_title'), size: 'md' }">
    <template #body-content>
      <div v-if="exception" class="space-y-3">
        <div class="flex items-center gap-2">
          <Badge :theme="severityTheme(exception.severity)" variant="subtle" :label="exception.severity" />
          <span class="text-p-sm font-medium text-ink-gray-8">{{ exception.type }}</span>
        </div>
        <p class="text-p-sm text-ink-gray-6">{{ exception.description }}</p>

        <FormControl
          v-model="resolution"
          type="textarea"
          rows="3"
          :label="t('page.night_audit.resolution_note')"
          :placeholder="t('page.night_audit.resolution_required')"
        />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button
            variant="solid"
            :loading="saving"
            :disabled="!resolution.trim()"
            @click="submit"
          >
            {{ t('page.night_audit.resolve') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Badge, Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import { resolveExceptionResource, severityTheme } from '@/resources/nightAudit'
import { normaliseError } from '@/utils/errors'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  audit: { type: String, default: '' },
  exception: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'resolved'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const resolveResource = resolveExceptionResource()

const saving = ref(false)
const errorMessage = ref('')
const resolution = ref('')

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return
    errorMessage.value = ''
    resolution.value = ''
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await resolveResource.submit({
      audit: props.audit,
      row_name: props.exception?.name,
      resolution: resolution.value.trim(),
    })

    emit('resolved')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
