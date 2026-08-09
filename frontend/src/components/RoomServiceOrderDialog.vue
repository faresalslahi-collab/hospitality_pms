<!--
  One room service order: what was ordered, and what happens to it next.

  Delivering is separated from the other status moves on purpose. Preparing and
  Ready change nothing but the kitchen's own state; delivering posts money to
  the guest's folio, so it is its own confirmed action with the amount spelled
  out. The server charges once under an idempotency key however many times this
  is pressed (HPMS-DEC-088).
-->
<template>
  <Dialog v-model="open" :options="{ title: order?.name || t('page.kitchen.order'), size: 'lg' }">
    <template #body-content>
      <LoadingState v-if="detail.loading && !detail.data" />
      <ErrorState v-else-if="detail.error" :error="detail.error" />

      <div v-else-if="order" class="space-y-4">
        <div class="flex flex-wrap items-center gap-2">
          <Badge :theme="orderStatusTheme(order.order_status)" variant="subtle" :label="order.order_status" />
          <Badge variant="subtle" theme="gray" :label="order.order_type" />
          <span class="text-p-sm text-ink-gray-6">
            {{ t('page.kitchen.room') }} {{ order.room }} · {{ formatDateTime(order.ordered_on) }}
          </span>
        </div>

        <div class="overflow-x-auto rounded border border-outline-gray-1">
          <table class="w-full min-w-max text-p-sm">
            <thead class="bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5">
              <tr>
                <th class="p-2 text-start">{{ t('page.kitchen.menu_item') }}</th>
                <th class="p-2 text-start">{{ t('common.quantity') }}</th>
                <th class="p-2 text-end">{{ t('page.kitchen.rate') }}</th>
                <th class="p-2 text-end">{{ t('page.kitchen.amount') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="line in lines" :key="line.name" class="border-t border-outline-gray-1">
                <td class="p-2">
                  {{ line.item_name }}
                  <span v-if="line.notes" class="block text-xs text-ink-gray-5">{{ line.notes }}</span>
                </td>
                <td class="p-2">{{ line.quantity }}</td>
                <td class="p-2 text-end whitespace-nowrap">
                  {{ formatCurrency(line.rate, order.currency) }}
                </td>
                <td class="p-2 text-end whitespace-nowrap">
                  {{ formatCurrency(line.amount, order.currency) }}
                </td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="border-t border-outline-gray-1 bg-surface-gray-1">
                <td class="p-2 font-medium" colspan="3">{{ t('page.kitchen.total') }}</td>
                <td class="p-2 text-end font-medium whitespace-nowrap">
                  {{ formatCurrency(order.total_amount, order.currency) }}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>

        <p v-if="order.special_instructions" class="text-p-sm text-ink-gray-7">
          {{ t('page.kitchen.special_instructions') }}: {{ order.special_instructions }}
        </p>

        <div v-if="order.folio_charge_row" class="rounded bg-surface-green-2 px-3 py-2">
          <p class="text-p-sm text-ink-green-3">{{ t('page.kitchen.delivered_note') }}</p>
        </div>

        <ErrorMessage :message="errorMessage" />

        <div class="flex flex-wrap justify-end gap-2">
          <RouterLink
            v-if="order.folio"
            :to="{ name: 'Folio', params: { id: order.folio } }"
            class="self-center text-p-sm text-ink-blue-3 hover:underline"
          >
            {{ t('page.kitchen.open_folio') }}
          </RouterLink>

          <Button
            v-for="step in nextSteps"
            :key="step.value"
            variant="subtle"
            :loading="busy === step.value"
            @click="move(step.value)"
          >
            {{ step.label }}
          </Button>

          <Button
            v-if="canDeliver"
            variant="solid"
            theme="green"
            :loading="busy === 'Delivered'"
            @click="deliver"
          >
            {{ t('page.kitchen.deliver') }}
          </Button>
        </div>

        <p v-if="canDeliver" class="text-end text-xs text-ink-gray-5">
          {{ t('page.kitchen.deliver_warning', { amount: formatCurrency(order.total_amount, order.currency) }) }}
        </p>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Badge, Button, Dialog, ErrorMessage } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import {
  NEXT_STATUS,
  OPEN_ORDER_STATUSES,
  deliverOrderResource,
  orderResource,
  orderStatusTheme,
  setOrderStatusResource,
} from '@/resources/kitchen'
import { normaliseError } from '@/utils/errors'
import { formatCurrency, formatDateTime } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  orderName: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'changed'])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const detail = orderResource()
const setStatus = setOrderStatusResource()
const deliverOrder = deliverOrderResource()

const busy = ref('')
const errorMessage = ref('')

const order = computed(() => detail.data?.order || null)
const lines = computed(() => detail.data?.lines || [])

// Cancelled and Delivered are terminal, so nothing is offered from there.
const nextSteps = computed(() =>
  (NEXT_STATUS[order.value?.order_status] || []).map((value) => ({
    value,
    label: t(
      value === 'Preparing'
        ? 'page.kitchen.mark_preparing'
        : value === 'Ready'
          ? 'page.kitchen.mark_ready'
          : 'page.kitchen.mark_cancelled',
    ),
  })),
)

const canDeliver = computed(() => OPEN_ORDER_STATUSES.includes(order.value?.order_status))

watch(
  () => [props.modelValue, props.orderName],
  ([isOpen, name]) => {
    if (!isOpen || !name) return

    errorMessage.value = ''
    detail.fetch({ order: name })
  },
  { immediate: true },
)

async function run(action, label) {
  busy.value = label
  errorMessage.value = ''

  try {
    await action()
    await detail.fetch({ order: props.orderName })
    emit('changed')
  } catch (error) {
    errorMessage.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

function move(status) {
  return run(() => setStatus.submit({ order: props.orderName, status }), status)
}

function deliver() {
  return run(() => deliverOrder.submit({ order: props.orderName }), 'Delivered')
}
</script>
