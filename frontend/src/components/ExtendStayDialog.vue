<!--
  Extend a stay by pushing its departure date out.

  Whether the room is free for the extra nights is the availability engine's
  decision, taken under a lock when this is confirmed. The only check here is
  that the new date is actually later than the current one — asking the server
  to "extend" a stay to an earlier date would just be a confusing refusal.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.stay.extend_title'), size: 'md' }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-p-sm text-ink-gray-6">{{ t('page.stay.extend_hint') }}</p>

        <p class="text-p-sm text-ink-gray-8">
          {{ stay?.guest_name }} · {{ t('page.stay.room') }} {{ stay?.room }} ·
          {{ formatDate(stay?.departure_date) }}
        </p>

        <FormControl
          v-model="form.departure"
          type="date"
          :label="t('page.stay.new_departure')"
          :min="minDate"
        />

        <p v-if="tooEarly" class="text-p-sm text-ink-red-3">
          {{ t('page.stay.extend_later_only') }}
        </p>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!canSubmit" @click="submit">
            {{ t('page.stay.extend') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { extendStayResource } from '@/resources/stays'
import { normaliseError } from '@/utils/errors'
import { formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  stay: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const extendStay = extendStayResource()

const saving = ref(false)
const errorMessage = ref('')
const form = reactive({ departure: '' })

const minDate = computed(() => props.stay?.departure_date || '')
const tooEarly = computed(
  () => Boolean(form.departure) && form.departure <= (props.stay?.departure_date || ''),
)
const canSubmit = computed(() => Boolean(form.departure) && !tooEarly.value && !saving.value)

watch(
  () => [props.modelValue, props.stay?.name],
  ([isOpen]) => {
    if (!isOpen) return

    errorMessage.value = ''
    form.departure = ''
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await extendStay.submit({ stay: props.stay.name, new_departure: form.departure })

    emit('changed')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
