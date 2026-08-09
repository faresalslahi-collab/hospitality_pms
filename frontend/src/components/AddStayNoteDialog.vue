<!--
  Add a note to a stay.

  This is where shift handover lives: the note types come from the stay note
  record itself, so what the desk can record here is what the domain models,
  not a list invented on this screen.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.stay.note_title'), size: 'md' }">
    <template #body-content>
      <div class="space-y-4">
        <FormControl
          v-model="form.note_type"
          type="select"
          :label="t('page.stay.note_type')"
          :options="typeOptions"
        />

        <FormControl
          v-model="form.note"
          type="textarea"
          :label="t('page.stay.note_text')"
          rows="4"
        />

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!form.note.trim()" @click="submit">
            {{ t('common.add') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import { STAY_NOTE_TYPES, addStayNoteResource } from '@/resources/stays'
import { normaliseError } from '@/utils/errors'
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

const addNote = addStayNoteResource()

const saving = ref(false)
const errorMessage = ref('')
const form = reactive({ note_type: STAY_NOTE_TYPES[0], note: '' })

const typeOptions = STAY_NOTE_TYPES.map((value) => ({ label: value, value }))

watch(
  () => [props.modelValue, props.stay?.name],
  ([isOpen]) => {
    if (!isOpen) return

    errorMessage.value = ''
    form.note_type = STAY_NOTE_TYPES[0]
    form.note = ''
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    await addNote.submit({
      stay: props.stay.name,
      note: form.note.trim(),
      note_type: form.note_type,
    })

    emit('changed')
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
