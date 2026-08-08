<!--
  Guest folio: charges, payments and the running balance.

  Only the transitions the server returned in `allowed_transitions` are
  offered (same rule as Reservation.vue). Reversing a charge is always a
  reversal, never an edit: the original stays on the ledger and a
  compensating line is posted next to it, and both are kept visually paired
  below.
-->
<template>
  <div>
    <LoadingState v-if="detail.loading && !detail.data" />
    <ErrorState v-else-if="detail.error" :error="detail.error" :on-retry="load" />

    <div v-else-if="folio">
      <PageHeader :title="folio.guest_name || folio.name" :subtitle="folio.name">
        <template #actions>
          <Badge :theme="folioStatusTheme(folio.folio_status)" variant="subtle" :label="folio.folio_status" />

          <Button
            v-for="target in allowed"
            :key="target"
            variant="subtle"
            :loading="busy === `transition:${target}`"
            @click="openTransition(target)"
          >
            {{ t('page.folio.transition_to', { status: target }) }}
          </Button>

          <Button variant="subtle" @click="postChargeOpen = true">
            {{ t('page.folio.post_charge') }}
          </Button>
          <Button variant="subtle" @click="postPaymentOpen = true">
            {{ t('page.folio.take_payment') }}
          </Button>
          <Button variant="subtle" @click="postAdjustmentOpen = true">
            {{ t('page.folio.post_adjustment') }}
          </Button>
          <Button variant="subtle" @click="splitOpen = true">
            {{ t('page.folio.split') }}
          </Button>
        </template>
      </PageHeader>

      <div class="grid gap-5 p-5 lg:grid-cols-3">
        <section class="space-y-4 lg:col-span-2">
          <div class="rounded border border-outline-gray-1">
            <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
              {{ t('page.folio.charges') }}
            </h2>

            <EmptyState v-if="!chargeGroups.length" :message="t('page.folio.no_charges')" />

            <div v-else class="divide-y divide-outline-gray-1">
              <div v-for="group in chargeGroups" :key="group.original.name" class="p-4">
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p
                      class="font-medium text-ink-gray-9"
                      :class="{ 'line-through decoration-ink-gray-4': group.original.is_reversed }"
                    >
                      {{ group.original.description }}
                    </p>
                    <p class="mt-0.5 text-p-sm text-ink-gray-6">
                      {{ formatDate(group.original.charge_date) }} · {{ group.original.charge_type }}
                      · {{ group.original.payer }}
                      <span v-if="group.original.quantity != 1"> · ×{{ group.original.quantity }}</span>
                    </p>
                    <Badge
                      v-if="group.original.is_reversed"
                      class="mt-1"
                      theme="orange"
                      variant="subtle"
                      :label="t('page.folio.reversed')"
                    />
                  </div>
                  <div class="text-end">
                    <p class="font-medium text-ink-gray-9">
                      {{ formatCurrency(group.original.total_amount, folio.currency) }}
                    </p>
                    <Button
                      v-if="!group.original.is_reversed && !group.original.reversal_of"
                      variant="ghost"
                      theme="red"
                      class="mt-1"
                      @click="openReverse(group.original)"
                    >
                      {{ t('page.folio.reverse') }}
                    </Button>
                  </div>
                </div>

                <!-- The compensating line stays visually paired with the charge it reverses. -->
                <div
                  v-if="group.reversal"
                  class="mt-2 flex items-start justify-between gap-3 border-s-2 border-outline-amber-2 ps-3"
                >
                  <div>
                    <p class="text-p-sm font-medium text-ink-amber-3">
                      <FeatherIcon name="corner-down-right" class="me-1 inline size-3.5" />
                      {{ t('page.folio.reversal_of', { description: group.original.description }) }}
                    </p>
                    <p class="mt-0.5 text-xs text-ink-gray-5">
                      {{ formatDate(group.reversal.charge_date) }}
                    </p>
                  </div>
                  <p class="text-p-sm font-medium text-ink-amber-3">
                    {{ formatCurrency(group.reversal.total_amount, folio.currency) }}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div class="rounded border border-outline-gray-1">
            <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
              {{ t('page.folio.payments') }}
            </h2>

            <EmptyState v-if="!payments.length" :message="t('page.folio.no_payments')" />

            <div v-else class="divide-y divide-outline-gray-1">
              <div v-for="row in payments" :key="row.name" class="flex items-start justify-between gap-3 p-4">
                <div>
                  <p class="font-medium text-ink-gray-9">
                    {{ row.payment_type }} · {{ row.payment_method }}
                  </p>
                  <p class="mt-0.5 text-p-sm text-ink-gray-6">
                    {{ formatDate(row.payment_date) }} · {{ row.payer }}
                    <span v-if="row.reference"> · {{ row.reference }}</span>
                  </p>
                </div>
                <p class="font-medium text-ink-green-3">{{ formatCurrency(row.amount, folio.currency) }}</p>
              </div>
            </div>
          </div>
        </section>

        <aside class="space-y-4">
          <dl class="space-y-3 rounded border border-outline-gray-1 p-4">
            <div v-for="item in summary" :key="item.label">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ item.label }}</dt>
              <dd class="mt-0.5 text-p-base text-ink-gray-8">{{ item.value }}</dd>
            </div>
          </dl>
        </aside>
      </div>
    </div>

    <PostChargeDialog v-model="postChargeOpen" :folio="route.params.id" @posted="load" />
    <PostPaymentDialog v-model="postPaymentOpen" :folio="route.params.id" @posted="load" />
    <PostAdjustmentDialog v-model="postAdjustmentOpen" :folio="route.params.id" @posted="load" />
    <SplitFolioDialog
      v-model="splitOpen"
      :folio="route.params.id"
      :currency="folio?.currency"
      :charges="charges"
      @split="onSplit"
    />

    <!-- Reversing a charge is destructive to the ledger's story, so it always asks why. -->
    <Dialog v-model="reverseOpen" :options="{ title: t('page.folio.reverse_title') }">
      <template #body-content>
        <div class="space-y-3">
          <p class="text-p-sm text-ink-gray-6">{{ t('page.folio.reverse_warning') }}</p>
          <p v-if="reverseTarget" class="text-p-sm font-medium text-ink-gray-8">
            {{ reverseTarget.description }} ·
            {{ formatCurrency(reverseTarget.total_amount, folio?.currency) }}
          </p>
          <FormControl v-model="reverseReason" type="textarea" :label="t('page.folio.reason')" rows="3" />
          <ErrorMessage :message="actionError" />
          <div class="flex justify-end gap-2">
            <Button variant="subtle" @click="reverseOpen = false">{{ t('common.close') }}</Button>
            <Button
              variant="solid"
              theme="red"
              :loading="busy === 'reverse'"
              :disabled="!reverseReason.trim()"
              @click="doReverse"
            >
              {{ t('page.folio.reverse_confirm') }}
            </Button>
          </div>
        </div>
      </template>
    </Dialog>

    <!-- Reopening a closed folio is a finance exception; the server demands a reason for it. -->
    <Dialog v-model="transitionOpen" :options="{ title: t('page.folio.transition_title') }">
      <template #body-content>
        <div class="space-y-3">
          <p v-if="transitionReasonRequired" class="text-p-sm text-ink-amber-3">
            {{ t('page.folio.transition_reason_hint') }}
          </p>
          <FormControl
            v-model="transitionReason"
            type="textarea"
            :label="t('page.folio.reason')"
            rows="3"
          />
          <ErrorMessage :message="actionError" />
          <div class="flex justify-end gap-2">
            <Button variant="subtle" @click="transitionOpen = false">{{ t('common.close') }}</Button>
            <Button
              variant="solid"
              :loading="busy === `transition:${transitionTarget}`"
              :disabled="transitionReasonRequired && !transitionReason.trim()"
              @click="doTransition"
            >
              {{ t('page.folio.transition_confirm') }}
            </Button>
          </div>
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { Badge, Button, Dialog, ErrorMessage, FeatherIcon, FormControl, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import PostAdjustmentDialog from '@/components/PostAdjustmentDialog.vue'
import PostChargeDialog from '@/components/PostChargeDialog.vue'
import PostPaymentDialog from '@/components/PostPaymentDialog.vue'
import SplitFolioDialog from '@/components/SplitFolioDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import {
  folioResource,
  folioStatusTheme,
  folioTransitionResource,
  reverseChargeResource,
} from '@/resources/folio'
import { normaliseError } from '@/utils/errors'
import { formatCurrency, formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const route = useRoute()

const detail = folioResource()
const reverseCharge = reverseChargeResource()
const transitionResource = folioTransitionResource()

const busy = ref('')
const actionError = ref('')

const postChargeOpen = ref(false)
const postPaymentOpen = ref(false)
const postAdjustmentOpen = ref(false)
const splitOpen = ref(false)

const reverseOpen = ref(false)
const reverseTarget = ref(null)
const reverseReason = ref('')

const transitionOpen = ref(false)
const transitionTarget = ref('')
const transitionReason = ref('')

const folio = computed(() => detail.data?.folio || null)
const charges = computed(() => detail.data?.charges || [])
const payments = computed(() => detail.data?.payments || [])
const allowed = computed(() => detail.data?.allowed_transitions || [])

const transitionReasonRequired = computed(() => folio.value?.folio_status === 'Closed')

// Pair every original charge with the compensating line that reverses it, so
// the two always render together rather than wherever date order puts them.
const chargeGroups = computed(() => {
  const byReversalOf = new Map()
  for (const row of charges.value) {
    if (row.reversal_of) byReversalOf.set(row.reversal_of, row)
  }

  return charges.value
    .filter((row) => !row.reversal_of)
    .map((row) => ({ original: row, reversal: byReversalOf.get(row.name) || null }))
})

const summary = computed(() => {
  const f = folio.value
  if (!f) return []

  return [
    { label: t('page.folio.balance'), value: formatCurrency(f.balance, f.currency) },
    { label: t('page.folio.total_charges'), value: formatCurrency(f.total_charges, f.currency) },
    { label: t('page.folio.total_taxes'), value: formatCurrency(f.total_taxes, f.currency) },
    { label: t('page.folio.total_payments'), value: formatCurrency(f.total_payments, f.currency) },
    { label: t('page.folio.total_adjustments'), value: formatCurrency(f.total_adjustments, f.currency) },
    { label: t('page.folio.stay'), value: f.stay || '—' },
    { label: t('page.folio.reservation'), value: f.reservation || '—' },
    { label: t('page.folio.room'), value: f.room || '—' },
    { label: t('page.folio.billing_instructions'), value: f.billing_instructions || '—' },
  ]
})

function openReverse(charge) {
  actionError.value = ''
  reverseReason.value = ''
  reverseTarget.value = charge
  reverseOpen.value = true
}

async function doReverse() {
  busy.value = 'reverse'
  actionError.value = ''

  try {
    await reverseCharge.submit({
      folio: route.params.id,
      charge_row: reverseTarget.value.name,
      reason: reverseReason.value.trim(),
    })

    await load()
    reverseOpen.value = false
    toast.success(t('page.folio.updated'))
  } catch (error) {
    actionError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

function openTransition(target) {
  actionError.value = ''
  transitionReason.value = ''
  transitionTarget.value = target
  transitionOpen.value = true
}

async function doTransition() {
  const key = `transition:${transitionTarget.value}`
  busy.value = key
  actionError.value = ''

  try {
    await transitionResource.submit({
      folio: route.params.id,
      target: transitionTarget.value,
      reason: transitionReason.value.trim() || undefined,
    })

    await load()
    transitionOpen.value = false
    toast.success(t('page.folio.updated'))
  } catch (error) {
    actionError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

function onSplit(targetFolio) {
  load()
  if (targetFolio) {
    toast.success(t('page.folio.split_success', { folio: targetFolio }))
  }
}

function load() {
  return detail.fetch({ folio: route.params.id })
}

watch(() => route.params.id, load, { immediate: true })
</script>
