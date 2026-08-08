<!--
  Checkout: settle the folio, post to ERPNext, release the room.

  The summary is loaded first and its blockers are rendered before anything
  else — Check out stays disabled while any blocker remains, because the
  server is what decides whether departure is actually possible (SAD section
  11), not this screen.
-->
<template>
  <div>
    <LoadingState v-if="summary.loading && !summary.data" />
    <ErrorState v-else-if="summary.error" :error="summary.error" :on-retry="load" />

    <div v-else-if="summary.data">
      <PageHeader :title="summary.data.guest_name || t('page.checkout.title')" :subtitle="summary.data.room || ''">
        <template #actions>
          <RouterLink
            v-if="summary.data.folio"
            :to="{ name: 'Folio', params: { id: summary.data.folio } }"
            class="text-p-sm text-ink-blue-3 hover:underline"
          >
            {{ t('page.checkout.go_to_folio') }}
          </RouterLink>
        </template>
      </PageHeader>

      <div class="grid gap-5 p-5 lg:grid-cols-3">
        <section class="space-y-4 lg:col-span-2">
          <div v-if="summary.data.blockers.length" class="rounded border border-outline-red-1 bg-surface-red-1 p-4">
            <p class="font-medium text-ink-red-4">{{ t('page.checkout.blockers_title') }}</p>
            <ul class="mt-2 list-inside list-disc space-y-1 text-p-sm text-ink-red-4">
              <li v-for="(blocker, index) in summary.data.blockers" :key="index">{{ blocker }}</li>
            </ul>
          </div>

          <div v-else class="rounded border border-outline-green-1 bg-surface-green-1 p-4">
            <p class="text-p-sm text-ink-green-3">{{ t('page.checkout.no_blockers') }}</p>
          </div>

          <div v-if="summary.data.related_folios.length" class="rounded border border-outline-gray-1">
            <h2 class="border-b border-outline-gray-1 px-4 py-2 text-p-sm font-medium text-ink-gray-8">
              {{ t('page.checkout.related_folios') }}
            </h2>
            <div class="divide-y divide-outline-gray-1">
              <RouterLink
                v-for="row in summary.data.related_folios"
                :key="row.name"
                :to="{ name: 'Folio', params: { id: row.name } }"
                class="flex items-center justify-between px-4 py-2 text-p-sm hover:bg-surface-gray-1"
              >
                <span class="text-ink-blue-3">{{ row.name }} · {{ row.folio_type }}</span>
                <span class="font-medium text-ink-gray-9">
                  {{ formatCurrency(row.balance, summary.data.currency) }}
                </span>
              </RouterLink>
            </div>
          </div>

          <div v-if="checkoutResult" class="rounded border border-outline-green-1 bg-surface-green-1 p-4">
            <p class="font-medium text-ink-green-3">{{ t('page.checkout.checkout_success_title') }}</p>
            <ul class="mt-2 space-y-1 text-p-sm text-ink-gray-8">
              <li>{{ t('page.checkout.folio_closed') }}</li>
              <li>{{ t('page.checkout.room_released') }}</li>
              <li v-if="checkoutResult.housekeeping_task">
                {{ t('page.checkout.housekeeping_raised', { task: checkoutResult.housekeeping_task }) }}
              </li>
              <li v-else class="text-ink-gray-5">{{ t('page.checkout.no_housekeeping_task') }}</li>
            </ul>
          </div>

          <div v-if="reverseResult" class="rounded border border-outline-amber-1 bg-surface-amber-1 p-4">
            <p class="font-medium text-ink-amber-3">{{ t('page.checkout.reverse_success') }}</p>
            <p class="mt-1 text-p-sm text-ink-gray-8">{{ reverseResult.note }}</p>
            <p v-if="reverseResult.standing_invoices?.length" class="mt-1 text-p-sm text-ink-gray-7">
              {{ reverseResult.standing_invoices.join(', ') }}
            </p>
          </div>
        </section>

        <aside class="space-y-4">
          <dl class="space-y-3 rounded border border-outline-gray-1 p-4">
            <div v-for="item in details" :key="item.label">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ item.label }}</dt>
              <dd class="mt-0.5 text-p-base text-ink-gray-8">{{ item.value }}</dd>
            </div>
          </dl>

          <div class="space-y-3 rounded border border-outline-gray-1 p-4">
            <FormControl v-model="postToErp" type="checkbox" :label="t('page.checkout.post_to_erp')" />

            <Button
              class="w-full"
              variant="solid"
              :loading="busy === 'check_out'"
              :disabled="summary.data.blockers.length > 0"
              @click="doCheckOut"
            >
              {{ t('page.checkout.check_out') }}
            </Button>

            <!--
              Offered only when every blocker is a balance blocker (see
              isBalanceOnlyBlocked): a button that cannot work server-side is
              worse than no button. Kept visually secondary - it is never a
              substitute for the normal Check out button above.
            -->
            <Button
              v-if="isBalanceOnlyBlocked"
              class="w-full"
              variant="subtle"
              theme="orange"
              @click="openCityLedger"
            >
              {{ t('page.checkout.city_ledger') }}
            </Button>

            <Button class="w-full" variant="subtle" theme="red" @click="openReverse">
              {{ t('page.checkout.reverse') }}
            </Button>

            <ErrorMessage :message="actionError" />
          </div>
        </aside>
      </div>
    </div>

    <!-- Undoing a checkout reopens a settled folio; the server always demands a reason. -->
    <Dialog v-model="reverseOpen" :options="{ title: t('page.checkout.reverse_title') }">
      <template #body-content>
        <div class="space-y-3">
          <p class="text-p-sm text-ink-red-4">{{ t('page.checkout.reverse_warning') }}</p>
          <FormControl v-model="reverseReason" type="textarea" :label="t('page.checkout.reason')" rows="3" />
          <ErrorMessage :message="reverseError" />
          <div class="flex justify-end gap-2">
            <Button variant="subtle" @click="reverseOpen = false">{{ t('common.close') }}</Button>
            <Button
              variant="solid"
              theme="red"
              :loading="busy === 'reverse'"
              :disabled="!reverseReason.trim()"
              @click="doReverse"
            >
              {{ t('page.checkout.reverse_confirm') }}
            </Button>
          </div>
        </div>
      </template>
    </Dialog>

    <!--
      City ledger: a corporate guest may leave with a balance that transfers
      to accounts receivable instead of being collected at the desk. The
      server (services/checkout.py::check_out) requires a manager role and a
      non-empty reason; this dialog states both plainly rather than promising
      an outcome the server may still refuse.
    -->
    <Dialog v-model="cityLedgerOpen" :options="{ title: t('page.checkout.city_ledger_title') }">
      <template #body-content>
        <div class="space-y-3">
          <p class="text-p-sm text-ink-red-4">{{ t('page.checkout.city_ledger_warning') }}</p>

          <div>
            <p class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.checkout.city_ledger_outstanding') }}
            </p>
            <p class="mt-0.5 text-p-base font-medium text-ink-gray-9">
              {{ formatCurrency(summary.data.balance, summary.data.currency) }}
            </p>
          </div>

          <p class="text-p-sm text-ink-amber-3">{{ t('page.checkout.city_ledger_manager_notice') }}</p>

          <FormControl v-model="cityLedgerReason" type="textarea" :label="t('page.checkout.reason')" rows="3" />
          <ErrorMessage :message="cityLedgerError" />

          <div class="flex justify-end gap-2">
            <Button variant="subtle" @click="cityLedgerOpen = false">{{ t('common.close') }}</Button>
            <Button
              variant="solid"
              theme="orange"
              :loading="busy === 'city_ledger'"
              :disabled="!cityLedgerReason.trim()"
              @click="doCityLedgerCheckOut"
            >
              {{ t('page.checkout.city_ledger_confirm') }}
            </Button>
          </div>
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { checkOutResource, checkoutSummaryResource, reverseCheckoutResource } from '@/resources/checkout'
import { normaliseError } from '@/utils/errors'
import { formatCurrency, formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const route = useRoute()

const summary = checkoutSummaryResource()
const checkOut = checkOutResource()
const reverseCheckout = reverseCheckoutResource()

const busy = ref('')
const actionError = ref('')
const postToErp = ref(true)
const checkoutResult = ref(null)

const reverseOpen = ref(false)
const reverseReason = ref('')
const reverseError = ref('')
const reverseResult = ref(null)

const cityLedgerOpen = ref(false)
const cityLedgerReason = ref('')
const cityLedgerError = ref('')

// Whether the ONLY thing stopping checkout is money outstanding, so the
// city-ledger override (services/checkout.py::check_out, `allow_open_balance`)
// could actually apply. The server itself decides this by checking whether
// every blocker string contains the (already-translated) word "balance" -
// something we deliberately do not copy client-side, because matching
// translated text is fragile and would silently break in Arabic.
//
// Instead we rebuild the same count from the numeric fields the summary
// already returns: get_checkout_summary appends exactly one blocker for the
// folio's own balance when it exceeds 0.005, and exactly one more per related
// (split) folio whose balance also exceeds 0.005 - nothing else contributes
// more than one blocker per condition. So if the number of blockers that
// balance data alone would explain equals the total blocker count, no other
// kind of blocker (stay status, disputed folio) can be present.
const balanceBlockerCount = computed(() => {
  const s = summary.data
  if (!s) return 0

  const ownBalance = Math.abs(s.balance) > 0.005 ? 1 : 0
  const relatedBalances = (s.related_folios || []).filter(
    (row) => Math.abs(row.balance) > 0.005,
  ).length

  return ownBalance + relatedBalances
})

const isBalanceOnlyBlocked = computed(() => {
  const s = summary.data
  if (!s || !s.blockers.length) return false

  return balanceBlockerCount.value === s.blockers.length
})

const details = computed(() => {
  const s = summary.data
  if (!s) return []

  return [
    { label: t('page.checkout.stay'), value: s.stay },
    { label: t('page.reservations.arrival'), value: formatDate(s.arrival_date) },
    { label: t('page.reservations.departure'), value: formatDate(s.departure_date) },
    { label: t('page.checkout.total_charges'), value: formatCurrency(s.total_charges, s.currency) },
    { label: t('page.checkout.total_payments'), value: formatCurrency(s.total_payments, s.currency) },
    { label: t('page.checkout.balance'), value: formatCurrency(s.balance, s.currency) },
  ]
})

async function doCheckOut() {
  busy.value = 'check_out'
  actionError.value = ''

  try {
    checkoutResult.value = await checkOut.submit({
      stay: route.params.stay,
      post_to_erp: postToErp.value ? 1 : 0,
    })

    reverseResult.value = null
    await load()
    toast.success(t('page.checkout.checkout_success_title'))
  } catch (error) {
    actionError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

function openReverse() {
  reverseError.value = ''
  reverseReason.value = ''
  reverseOpen.value = true
}

async function doReverse() {
  busy.value = 'reverse'
  reverseError.value = ''

  try {
    reverseResult.value = await reverseCheckout.submit({
      stay: route.params.stay,
      reason: reverseReason.value.trim(),
    })

    checkoutResult.value = null
    await load()
    reverseOpen.value = false
    toast.success(t('page.checkout.reverse_success'))
  } catch (error) {
    reverseError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

function openCityLedger() {
  cityLedgerError.value = ''
  cityLedgerReason.value = ''
  cityLedgerOpen.value = true
}

async function doCityLedgerCheckOut() {
  busy.value = 'city_ledger'
  cityLedgerError.value = ''

  try {
    checkoutResult.value = await checkOut.submit({
      stay: route.params.stay,
      post_to_erp: postToErp.value ? 1 : 0,
      allow_open_balance: 1,
      reason: cityLedgerReason.value.trim(),
    })

    reverseResult.value = null
    cityLedgerOpen.value = false
    await load()
    toast.success(t('page.checkout.checkout_success_title'))
  } catch (error) {
    // A refusal here (missing role, empty reason once trimmed to nothing,
    // more than a balance actually blocking) is the server's own message -
    // surfaced as-is rather than guessed at client-side.
    cityLedgerError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

function load() {
  return summary.fetch({ stay: route.params.stay })
}

watch(() => route.params.stay, load, { immediate: true })
</script>
