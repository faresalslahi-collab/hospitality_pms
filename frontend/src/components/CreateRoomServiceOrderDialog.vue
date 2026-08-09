<!--
  Take a room service order.

  No price is entered here and none is sent. The server prices every line from
  the menu record whatever the caller supplies, which is what stops a client
  from giving the hotel's food away (HPMS-DEC-088). The figures shown beside
  each item are the menu's, for the person on the phone to read out — the total
  the guest is charged is the one the server returns.
-->
<template>
  <Dialog v-model="open" :options="{ title: t('page.kitchen.new_order'), size: 'xl' }">
    <template #body-content>
      <div class="space-y-4">
        <EmptyState v-if="!stayOptions.length" :message="t('page.kitchen.no_stays')" />

        <template v-else>
          <FormControl
            v-model="form.stay"
            type="select"
            :label="t('page.kitchen.select_stay')"
            :options="stayOptions"
            :description="t('page.kitchen.select_stay_hint')"
          />

          <FormControl
            v-model="form.order_type"
            type="select"
            :label="t('page.kitchen.order_type')"
            :options="typeOptions"
          />

          <EmptyState v-if="!menuOptions.length" :message="t('page.kitchen.no_menu')" />

          <div v-else class="space-y-2">
            <p class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.kitchen.lines') }}
            </p>

            <div
              v-for="(line, index) in form.lines"
              :key="index"
              class="flex flex-wrap items-end gap-2 rounded border border-outline-gray-1 p-2"
            >
              <FormControl
                v-model="line.menu_item"
                class="min-w-48 flex-1"
                type="select"
                :label="t('page.kitchen.menu_item')"
                :options="menuOptions"
              />
              <FormControl
                v-model.number="line.quantity"
                class="w-24"
                type="number"
                min="1"
                :label="t('common.quantity')"
              />
              <FormControl v-model="line.notes" class="min-w-40 flex-1" type="text" :label="t('common.notes')" />
              <Button
                v-if="form.lines.length > 1"
                variant="subtle"
                :aria-label="t('common.remove')"
                @click="form.lines.splice(index, 1)"
              >
                <template #icon><FeatherIcon name="trash-2" class="size-4" /></template>
              </Button>
            </div>

            <Button variant="subtle" @click="addLine">
              <template #prefix><FeatherIcon name="plus" class="size-4" /></template>
              {{ t('page.kitchen.add_line') }}
            </Button>
          </div>

          <FormControl
            v-model="form.special_instructions"
            type="textarea"
            rows="2"
            :label="t('page.kitchen.special_instructions')"
          />

          <p class="text-p-sm text-ink-gray-5">{{ t('page.kitchen.priced_by_server') }}</p>
        </template>

        <ErrorMessage :message="errorMessage" />

        <div class="flex justify-end gap-2">
          <Button variant="subtle" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button variant="solid" :loading="saving" :disabled="!canSubmit" @click="submit">
            {{ t('page.kitchen.place_order') }}
          </Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

import EmptyState from '@/components/states/EmptyState.vue'
import { ORDER_TYPES, createOrderResource, menuItemsResource } from '@/resources/kitchen'
import { inHouseResource } from '@/resources/stays'
import { property } from '@/stores/property'
import { normaliseError } from '@/utils/errors'
import { formatCurrency } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'created'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const menu = menuItemsResource()
const board = inHouseResource()
const createOrder = createOrderResource()

const saving = ref(false)
const errorMessage = ref('')
const form = reactive({
  stay: '',
  order_type: ORDER_TYPES[0],
  special_instructions: '',
  lines: [{ menu_item: '', quantity: 1, notes: '' }],
})

const typeOptions = ORDER_TYPES.map((value) => ({ label: value, value }))

// An order is charged to a folio, so only guests actually in house can have one.
const stayOptions = computed(() =>
  (board.data?.stays || []).map((stay) => ({
    label: `${stay.room} · ${stay.guest_name}`,
    value: stay.name,
  })),
)

const menuOptions = computed(() =>
  (menu.data?.menu_items || []).map((item) => ({
    label: `${item.menu_item_name} · ${formatCurrency(item.selling_rate, item.currency || property.currency.value)}`,
    value: item.name,
  })),
)

const canSubmit = computed(
  () => Boolean(form.stay) && form.lines.some((line) => line.menu_item) && !saving.value,
)

function addLine() {
  form.lines.push({ menu_item: '', quantity: 1, notes: '' })
}

watch(
  () => props.modelValue,
  (isOpen) => {
    if (!isOpen) return

    errorMessage.value = ''
    form.stay = ''
    form.order_type = ORDER_TYPES[0]
    form.special_instructions = ''
    form.lines = [{ menu_item: '', quantity: 1, notes: '' }]

    board.fetch({ property: property.activeName.value })
    loadMenu()
  },
)

/** The menu depends on the order type: a minibar item is not room service. */
function loadMenu() {
  menu.fetch({ property: property.activeName.value, order_type: form.order_type })
}

watch(
  () => form.order_type,
  () => {
    if (!props.modelValue) return

    form.lines.forEach((line) => (line.menu_item = ''))
    loadMenu()
  },
)

async function submit() {
  saving.value = true
  errorMessage.value = ''

  try {
    const result = await createOrder.submit({
      property: property.activeName.value,
      stay: form.stay,
      order_type: form.order_type,
      special_instructions: form.special_instructions.trim() || undefined,
      // Only the item and how many. Never a rate — the server sets that.
      lines: form.lines
        .filter((line) => line.menu_item)
        .map((line) => ({
          menu_item: line.menu_item,
          quantity: Number(line.quantity) || 1,
          notes: line.notes?.trim() || undefined,
        })),
    })

    emit('created', result)
    open.value = false
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    saving.value = false
  }
}
</script>
