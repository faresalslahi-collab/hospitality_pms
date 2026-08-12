<!--
  Cashier & Folio workspace: charges, payments, accounting state and balance.

  Tabbed since 16.7.5, mirroring the Guest 360 shell — the tab lives in `?tab=`,
  panels carry the a11y wiring, and switching uses `replace` because it is not a
  step in the cashier's history. Kept on the existing `Folio` route and
  `/folios/:id` path: Checkout, Departures and Guest 360 all navigate here by
  name.

  **No money is calculated here.** Every total and the balance are read from the
  server as opaque numbers. `total_charges` already includes tax, reversed
  charges stay on the ledger and are cancelled by their compensating line, and
  `total_adjustments` counts Adjustment but not Discount — three rules a client
  cannot reconstruct from the rows, and three reasons it must not try.

  Only the transitions the server returned in `allowed_transitions` are
  offered (same rule as Reservation.vue). Reversing a charge is always a
  reversal, never an edit: the original stays on the ledger and a
  compensating line is posted next to it, and both are kept visually paired
  below.
-->
<template>
  <div>
    <LoadingState v-if="detail.loading && !detail.data" />

    <!-- A permission failure is not a fault this user can retry out of. -->
    <PermissionDenied v-else-if="permissionDenied" :message="errorDetails.message" />
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

      <div class="border-b border-outline-gray-1">
        <div
          class="flex gap-1 overflow-x-auto px-5"
          role="tablist"
          :aria-label="t('page.folio.tab.summary')"
          @keydown="onTabKeydown"
        >
          <button
            v-for="tab in tabs"
            :id="`folio-tab-${tab.key}`"
            :key="tab.key"
            ref="tabButtons"
            role="tab"
            type="button"
            class="whitespace-nowrap border-b-2 px-3 py-2 text-p-sm"
            :class="
              activeTab === tab.key
                ? 'border-outline-gray-4 font-medium text-ink-gray-9'
                : 'border-transparent text-ink-gray-6'
            "
            :aria-selected="activeTab === tab.key"
            :aria-controls="`folio-panel-${tab.key}`"
            :tabindex="activeTab === tab.key ? 0 : -1"
            @click="selectTab(tab.key)"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>

      <section v-bind="panelAttrs('summary')">
        <dl v-if="activeTab === 'summary'" class="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3 lg:grid-cols-4">
          <div>
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.folio.balance') }}</dt>
            <dd class="mt-1">
              <FolioBalance :balance="folio.balance" :currency="folio.currency" size="md" />
            </dd>
          </div>
          <div v-for="item in moneyTiles" :key="item.key">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ item.label }}</dt>
            <dd class="mt-1"><MoneyDisplay :value="item.value" :currency="folio.currency" /></dd>
          </div>
          <div v-for="item in contextTiles" :key="item.key">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ item.label }}</dt>
            <dd class="mt-1 text-p-sm text-ink-gray-8">{{ item.value }}</dd>
          </div>
        </dl>
      </section>

      <section v-bind="panelAttrs('invoices')">
        <div v-if="activeTab === 'invoices'" class="space-y-3">
          <EmptyState v-if="!postedCharges.length" :message="t('page.folio.no_invoices')" />

          <div v-else class="divide-y divide-outline-gray-1 rounded border border-outline-gray-1">
            <div v-for="row in postedCharges" :key="row.name" class="flex items-start justify-between gap-3 p-4">
              <div>
                <p class="font-medium text-ink-gray-9">{{ row.description }}</p>
                <p class="mt-0.5 text-p-sm text-ink-gray-6">
                  {{ row.charge_type }} · {{ formatDate(row.business_date) }}
                  <span v-if="row.sales_invoice"> · {{ row.sales_invoice }}</span>
                </p>
              </div>
              <Badge theme="green" variant="subtle" :label="t('page.folio.posted')" />
            </div>
          </div>
        </div>
      </section>

      <section v-bind="panelAttrs('charges')">
        <div v-if="activeTab === 'charges'">
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
        </div>
      </section>

      <section v-bind="panelAttrs('payments')">
        <div v-if="activeTab === 'payments'">
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
                <div class="flex items-center gap-3">
                  <p class="font-medium text-ink-green-3">
                    {{ formatCurrency(row.amount, folio.currency) }}
                  </p>
                  <!-- Offered only where a gateway transaction backs the row.
                       Whether it may actually be refunded is the server's
                       answer: it re-checks the state and the ceiling under a
                       lock, and refuses in its own words. -->
                  <Button
                    v-if="row.reference && row.amount > 0"
                    variant="subtle"
                    :loading="busy === `refund:${row.name}`"
                    @click="openRefund(row)"
                  >
                    {{ t('page.payments.refund') }}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <RefundPaymentDialog
      v-model="refundOpen"
      :transaction="refundTarget"
      :currency="folio?.currency"
      @refunded="load"
    />
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
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import FolioBalance from '@/components/operational/FolioBalance.vue'
import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import PostAdjustmentDialog from '@/components/PostAdjustmentDialog.vue'
import PostChargeDialog from '@/components/PostChargeDialog.vue'
import RefundPaymentDialog from '@/components/RefundPaymentDialog.vue'
import PostPaymentDialog from '@/components/PostPaymentDialog.vue'
import SplitFolioDialog from '@/components/SplitFolioDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import PermissionDenied from '@/components/states/PermissionDenied.vue'
import {
  folioResource,
  folioStatusTheme,
  folioTransitionResource,
  reverseChargeResource,
} from '@/resources/folio'
import { paymentTransactionResource } from '@/resources/payments'
import { normaliseError } from '@/utils/errors'
import { formatCurrency, formatDate } from '@/utils/format'
import { isRTL, t } from '@/utils/i18n'

const route = useRoute()
const router = useRouter()

/** Fixed order. A tab is never hidden here — every panel reads folio data the
 *  caller already proved they may read, so there is nothing to disclose-gate. */
const TAB_KEYS = ['summary', 'charges', 'payments', 'invoices']

const tabButtons = ref([])

const detail = folioResource()
const reverseCharge = reverseChargeResource()
const transitionResource = folioTransitionResource()

const busy = ref('')
const actionError = ref('')

const postChargeOpen = ref(false)
const postPaymentOpen = ref(false)
const postAdjustmentOpen = ref(false)
const splitOpen = ref(false)

const transaction = paymentTransactionResource()
const refundOpen = ref(false)
const refundTarget = ref(null)

const reverseOpen = ref(false)
const reverseTarget = ref(null)
const reverseReason = ref('')

const transitionOpen = ref(false)
const transitionTarget = ref('')
const transitionReason = ref('')

const errorDetails = computed(() => normaliseError(detail.error))
const permissionDenied = computed(
  () => Boolean(detail.error) && errorDetails.value.kind === 'permission',
)

const tabs = computed(() => TAB_KEYS.map((key) => ({ key, label: t(`page.folio.tab.${key}`) })))

const activeTab = computed(() => {
  const wanted = String(route.query.tab || '')

  return TAB_KEYS.includes(wanted) ? wanted : 'summary'
})

function panelAttrs(key) {
  return {
    id: `folio-panel-${key}`,
    role: 'tabpanel',
    'aria-labelledby': `folio-tab-${key}`,
    tabindex: 0,
    hidden: activeTab.value !== key,
    class: activeTab.value === key ? 'p-5' : '',
  }
}

/** `replace`, not `push`: switching tabs is not a step in the cashier's history. */
function selectTab(key) {
  if (!TAB_KEYS.includes(key) || key === activeTab.value) return

  router.replace({ query: { ...route.query, tab: key } })
}

function onTabKeydown(event) {
  const forward = isRTL.value ? 'ArrowLeft' : 'ArrowRight'
  const backward = isRTL.value ? 'ArrowRight' : 'ArrowLeft'

  if (![forward, backward, 'Home', 'End'].includes(event.key)) return

  event.preventDefault()

  const current = TAB_KEYS.indexOf(activeTab.value)
  let next = current

  if (event.key === forward) next = (current + 1) % TAB_KEYS.length
  else if (event.key === backward) next = (current - 1 + TAB_KEYS.length) % TAB_KEYS.length
  else if (event.key === 'Home') next = 0
  else next = TAB_KEYS.length - 1

  selectTab(TAB_KEYS[next])
  tabButtons.value[next]?.focus()
}

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

/** Charges the server says reached the accounting system. */
const postedCharges = computed(() => charges.value.filter((row) => row.is_posted_to_erp))

/**
 * The four totals, rendered through `MoneyDisplay`.
 *
 * Read, never derived. The balance is separate because it carries settled /
 * due / credit semantics that a formatted string throws away.
 */
const moneyTiles = computed(() => {
  const f = folio.value
  if (!f) return []

  return [
    { key: 'total_charges', label: t('page.folio.total_charges'), value: f.total_charges },
    { key: 'total_taxes', label: t('page.folio.total_taxes'), value: f.total_taxes },
    { key: 'total_payments', label: t('page.folio.total_payments'), value: f.total_payments },
    { key: 'total_adjustments', label: t('page.folio.total_adjustments'), value: f.total_adjustments },
  ]
})

const contextTiles = computed(() => {
  const f = folio.value
  if (!f) return []

  return [
    { key: 'stay', label: t('page.folio.stay'), value: f.stay || '—' },
    { key: 'reservation', label: t('page.folio.reservation'), value: f.reservation || '—' },
    { key: 'room', label: t('page.folio.room'), value: f.room || '—' },
    {
      key: 'billing_instructions',
      label: t('page.folio.billing_instructions'),
      value: f.billing_instructions || '—',
    },
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

/**
 * Open the refund dialog for the gateway transaction behind a folio payment.
 *
 * The transaction is fetched rather than reconstructed: the folio row carries
 * the amount that was received, and a refund needs what has *already* been
 * refunded and the current state, both of which live on the transaction and
 * both of which the server re-reads under a lock before it acts.
 */
async function openRefund(row) {
  busy.value = `refund:${row.name}`
  actionError.value = ''

  try {
    await transaction.fetch({ transaction: row.reference })
    refundTarget.value = transaction.data
    refundOpen.value = true
  } catch (error) {
    actionError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

function load() {
  return detail.fetch({ folio: route.params.id })
}

watch(() => route.params.id, load, { immediate: true })
</script>
