<!--
  Departures board for the property's business date, on the shared operational table.

  One request returns the whole day, including each stay's checkout blockers, which
  the server has already worded and translated. The filter and search below are
  client side for the same reason as the arrivals board.

  `can_check_out` is the server's answer and is never recomputed here — it weighs a
  disputed folio and the individual split folios, neither of which reaches this
  page. A blocked stay still shows its Check out action, because the checkout
  screen is where a manager resolves the blocker; the badge explains why it is not
  a clean exit. Nothing here is disabled on a blocker: the blocked rows are exactly
  the ones a supervisor has to be able to open.

  16.7.1 adds Take payment, and adds it to the drawer only. Two reasons, both about
  money:

  - The drawer is the one place on this screen where the balance is already
    displayed in full (`FolioBalance`, `size="md"`). A payment dialog reached from a
    row button would take an amount with the balance off screen, which is how 40
    becomes 400.
  - A row with split folios is not payable from one button. `get_departure_blockers`
    blocks on each folio individually, and a control bound to `row.folio` settles
    only the primary — so the blocker survives the payment and the agent pays
    twice. On a split row the verb is withheld and the folio link is the route.
-->
<template>
  <div>
    <PageHeader :title="t('page.departures.title')" :subtitle="property.active.value?.property_name || ''">
      <template #actions>
        <Button variant="subtle" :loading="board.loading" @click="reload">
          <template #prefix><FeatherIcon name="refresh-cw" class="size-4" /></template>
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <div class="space-y-4 p-5">
      <div v-if="rows.length" class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div v-for="tile in tiles" :key="tile.key" class="rounded border border-outline-gray-1 px-3 py-2">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ tile.label }}</p>
          <p class="mt-0.5 text-lg font-semibold text-ink-gray-9">{{ tile.value }}</p>
        </div>
      </div>

      <OperationalDataTable
        :columns="columns"
        :rows="visibleRows"
        row-key="key"
        :loading="board.loading"
        :error="board.error"
        :empty-message="emptyMessage"
        :actions="actions"
        searchable
        :search="search"
        :search-label="t('page.departures.search_label')"
        :aria-label="t('page.departures.title')"
        sticky-header
        @search-change="search = $event"
        @row-action="onRowAction"
      >
        <template #toolbar>
          <div class="w-full sm:w-56">
            <FormControl
              v-model="filter"
              type="select"
              size="sm"
              :label="t('page.departures.filter')"
              :options="filterOptions"
            />
          </div>
        </template>

        <template #error="{ error }">
          <ErrorState :error="error" :on-retry="reload" />
        </template>

        <template #cell:guest_name="{ row }">
          <span class="text-ink-gray-9">{{ row.guest_name }}</span>
          <Badge
            v-if="row.vip_status"
            class="ms-1"
            :theme="vipStatusTheme(row.vip_status)"
            variant="subtle"
            :label="row.vip_status"
          />
        </template>

        <template #cell:room_number="{ row }">
          <RouterLink
            :to="{ name: 'Stay', params: { id: row.stay } }"
            class="font-medium text-ink-blue-3 hover:underline"
          >
            {{ row.room_number }}
          </RouterLink>
        </template>

        <template #cell:stay_dates="{ row }">
          <span>{{ formatDate(row.arrival_date) }} – {{ formatDate(row.departure_date) }}</span>
          <span class="ms-2 text-ink-gray-5">{{ row.nights }} {{ t('page.reservations.nights') }}</span>
        </template>

        <template #cell:folio="{ row }">
          <RouterLink
            v-if="row.folio"
            :to="{ name: 'Folio', params: { id: row.folio } }"
            class="text-ink-blue-3 hover:underline"
          >
            {{ row.folio }}
          </RouterLink>
          <span v-else class="text-ink-gray-5">—</span>
        </template>

        <!-- Split folios are counted, not summed into the primary balance: the
             two numbers settle separately and merging them would mislead. -->
        <template #cell:balance="{ row }">
          <FolioBalance :balance="row.balance" :currency="row.currency" :show-label="false" />
          <p v-if="row.related_folios > 0" class="mt-1 text-xs text-ink-gray-5">
            {{ t('page.departures.split_folios', { count: row.related_folios }) }}
          </p>
        </template>

        <!--
          The server's verdict, restated. Nothing here derives readiness from the
          balance: a settled folio is not permission to leave.
        -->
        <template #cell:readiness="{ row }">
          <Badge
            v-if="row.is_checked_out"
            theme="gray"
            variant="subtle"
            :label="t('page.departures.checked_out')"
          />
          <Badge
            v-else-if="row.can_check_out"
            theme="green"
            variant="subtle"
            :label="t('page.departures.ready')"
          />
          <template v-else>
            <Badge theme="orange" variant="subtle" :label="t('page.departures.blocked')" />
            <!-- Blockers arrive already worded and translated by the server. -->
            <ul v-if="row.blockers?.length" class="mt-1 list-disc ps-4 text-xs text-ink-gray-6">
              <li v-for="(blocker, index) in row.blockers" :key="index">{{ blocker }}</li>
            </ul>
          </template>
        </template>
      </OperationalDataTable>
    </div>

    <ActionDrawer
      v-model="drawerOpen"
      :title="selected?.guest_name || ''"
      :subtitle="selected ? `${t('page.departures.room')} ${selected.room_number}` : ''"
    >
      <div v-if="selected" class="space-y-4">
        <FolioBalance :balance="selected.balance" :currency="selected.currency" size="md" />

        <dl class="space-y-3">
          <div v-for="item in detailItems" :key="item.label">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ item.label }}</dt>
            <dd class="text-p-sm text-ink-gray-8">{{ item.value }}</dd>
          </div>
        </dl>

        <div v-if="!selected.can_check_out && selected.blockers?.length">
          <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.departures.blockers') }}</p>
          <ul class="mt-1 list-disc ps-4 text-p-sm text-ink-gray-7">
            <li v-for="(blocker, index) in selected.blockers" :key="index">{{ blocker }}</li>
          </ul>
        </div>
      </div>

      <template #footer>
        <Button variant="subtle" @click="openStay">{{ t('page.departures.action.open_stay') }}</Button>
        <Button variant="subtle" @click="openGuest">{{ t('page.departures.action.guest_profile') }}</Button>
        <Button v-if="selected?.folio" variant="subtle" @click="openFolio">
          {{ t('page.departures.action.open_folio') }}
        </Button>
        <Button v-if="canExtend(selected)" variant="subtle" @click="extendFromDrawer">
          {{ t('page.departures.action.extend') }}
        </Button>
        <Button v-if="canTakePayment(selected)" variant="subtle" @click="paymentFromDrawer">
          {{ t('page.folio.take_payment') }}
        </Button>
        <Button v-if="selected && !selected.is_checked_out" variant="solid" @click="openCheckout">
          {{ t('page.departures.action.checkout') }}
        </Button>
      </template>
    </ActionDrawer>

    <ExtendStayDialog v-model="extendOpen" :stay="extendTarget" @changed="reload" />

    <!--
      The balance and the guest travel with the folio, so the figure the agent read
      in the drawer is the figure in front of them while they type. `@posted`
      reloads the board: a payment is not a settlement, and until the board is
      refetched the row still shows the balance from before it.
    -->
    <PostPaymentDialog
      v-model="paymentOpen"
      :folio="paymentTarget?.folio || ''"
      :balance="paymentTarget?.balance ?? null"
      :currency="paymentTarget?.currency || null"
      :guest-name="paymentTarget?.guest_name || ''"
      @posted="reload"
    />
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import ExtendStayDialog from '@/components/ExtendStayDialog.vue'
import PageHeader from '@/components/PageHeader.vue'
import PostPaymentDialog from '@/components/PostPaymentDialog.vue'
import ActionDrawer from '@/components/operational/ActionDrawer.vue'
import FolioBalance from '@/components/operational/FolioBalance.vue'
import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import { departuresBoardResource } from '@/resources/frontOffice'
import { vipStatusTheme } from '@/resources/guests'
import { STAY_OPERATION_ROLES, stayStatusTheme } from '@/resources/stays'
import { property } from '@/stores/property'
import { session } from '@/stores/session'
import { formatCurrency, formatDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const router = useRouter()
const board = departuresBoardResource()

const filter = ref('all')
const search = ref('')

const drawerOpen = ref(false)
const selected = ref(null)

const extendOpen = ref(false)
const extendTarget = ref(null)

// Held apart from `selected` so the drawer can close before the dialog opens
// without the dialog losing the folio and the balance it was opened for.
const paymentOpen = ref(false)
const paymentTarget = ref(null)

/** Predicates over the rows already in memory; no filter re-fetches the board. */
const FILTERS = {
  all: () => true,
  due_out: (row) => !row.is_checked_out,
  ready: (row) => Boolean(row.can_check_out),
  balance_pending: (row) => Math.abs(Number(row.balance || 0) + Number(row.related_balance || 0)) > 0.005,
  checked_out: (row) => Boolean(row.is_checked_out),
}

// Computed, not a plain const: the language switcher changes the locale in
// place without reloading, so labels built once would stay in the old language.
const filterOptions = computed(() =>
  Object.keys(FILTERS).map((value) => ({ label: t(`page.departures.filter.${value}`), value })),
)

const columns = computed(() => [
  { key: 'guest_name', label: t('page.departures.guest'), secondary: true },
  { key: 'room_number', label: t('page.departures.room'), primary: true, nowrap: true },
  { key: 'stay_dates', label: t('page.departures.stay'), field: 'arrival_date', nowrap: true },
  { key: 'folio', label: t('page.departures.folio'), nowrap: true, hideBelow: 'lg' },
  { key: 'balance', label: t('page.departures.balance'), nowrap: true },
  {
    key: 'stay_status',
    label: t('page.departures.status'),
    type: 'badge',
    theme: (row) => stayStatusTheme(row.stay_status),
  },
  { key: 'readiness', label: t('page.departures.readiness'), field: 'can_check_out' },
])

/**
 * Row actions.
 *
 * Checkout is offered on a blocked row on purpose (see the file header). Extend
 * mirrors the stay-operation role because it opens a mutating dialog from this
 * board, and it is withheld from an already-departed stay, which the server
 * refuses outright — this board carries checked-out rows by design.
 */
const actions = computed(() => [
  { key: 'details', label: t('page.departures.action.details'), icon: 'info' },
  {
    key: 'folio',
    label: t('page.departures.action.open_folio'),
    available: (row) => Boolean(row.folio),
  },
  {
    key: 'checkout',
    label: t('page.departures.action.checkout'),
    theme: 'blue',
    available: (row) => !row.is_checked_out,
  },
])

const rows = computed(() => board.data?.rows || [])

const visibleRows = computed(() => {
  const predicate = FILTERS[filter.value] || FILTERS.all
  const term = search.value.trim().toLowerCase()

  return rows.value.filter((row) => {
    if (!predicate(row)) return false
    if (!term) return true

    return [row.guest_name, row.room_number, row.folio, row.stay]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(term))
  })
})

const emptyMessage = computed(() =>
  rows.value.length ? t('page.departures.filter_empty') : t('page.departures.empty'),
)

const tiles = computed(() => {
  const s = board.data?.summary || {}
  const currency = board.data?.currency || property.currency.value

  return [
    { key: 'total', label: t('page.departures.total'), value: s.total ?? 0 },
    { key: 'due_out', label: t('page.departures.due_out'), value: s.due_out ?? 0 },
    { key: 'checked_out', label: t('page.departures.checked_out'), value: s.checked_out ?? 0 },
    { key: 'ready', label: t('page.departures.ready'), value: s.ready ?? 0 },
    { key: 'blocked', label: t('page.departures.blocked'), value: s.blocked ?? 0 },
    { key: 'balance_pending', label: t('page.departures.balance_pending'), value: s.balance_pending ?? 0 },
    {
      key: 'outstanding',
      label: t('page.departures.outstanding'),
      value: formatCurrency(s.outstanding_balance ?? 0, currency),
    },
  ]
})

const detailItems = computed(() => {
  const row = selected.value
  if (!row) return []

  return [
    { label: t('page.departures.status'), value: row.stay_status },
    { label: t('page.stay.arrival'), value: formatDate(row.arrival_date) },
    { label: t('page.stay.departure'), value: formatDate(row.departure_date) },
    { label: t('page.departures.nights'), value: String(row.nights ?? '') },
    { label: t('page.departures.folio'), value: row.folio || '—' },
    {
      label: t('page.departures.readiness'),
      value: row.is_checked_out
        ? t('page.departures.checked_out')
        : row.can_check_out
          ? t('page.departures.ready')
          : t('page.departures.blocked'),
    },
  ]
})

/**
 * Extending needs the stay-operation role and an in-house stay. The status test
 * is the server's own rule restated for visibility only: `extend_stay` refuses
 * anything that is not in house, and re-checks under a lock.
 */
function canExtend(row) {
  if (!row) return false

  return !row.is_checked_out && session.hasRole(STAY_OPERATION_ROLES)
}

/**
 * Taking a payment needs a folio to take it against, and needs that folio to be
 * the only one on the stay.
 *
 * The split-folio case is withheld rather than disabled, because the right route
 * exists next to it: Open folio, where each folio is settled on its own terms. It
 * is not a role decision — the folio screen gates this dialog on no role either,
 * and `folio.post_payment` authorises the posting itself. The stay status is not
 * tested: whether money may be posted is the folio's state, not the stay's, and
 * the server refuses a closed one.
 *
 * No role mirror, and none is needed for the case that matters. A caller who may
 * not read Guest Folio is no longer sent `folio` at all — the board withholds the
 * whole folio position (`front_office._folio_position`) — so the control vanishes
 * with the data rather than being hidden on top of it. A caller who may *read* the
 * folio but not write it still sees the verb and is refused by the server, exactly
 * as they are on the folio screen itself; 16.7.0's authorization review looked at
 * this specific case and said not to invent a folio-write role constant for it.
 */
function canTakePayment(row) {
  if (!row?.folio) return false

  return !(Number(row.related_folios) > 0)
}

function onRowAction({ action, row }) {
  if (action === 'details') {
    selected.value = row
    drawerOpen.value = true
    return
  }

  if (action === 'folio') {
    router.push({ name: 'Folio', params: { id: row.folio } })
    return
  }

  if (action === 'checkout') {
    router.push({ name: 'Checkout', params: { stay: row.stay } })
  }
}

/** The stay, in the shape the stay dialogs read it. */
function stayShape(row) {
  return {
    name: row.stay,
    guest_name: row.guest_name,
    room: row.room_number,
    room_type: row.room_type,
    arrival_date: row.arrival_date,
    departure_date: row.departure_date,
  }
}

/** A dialog is never stacked inside the panel: the drawer closes first. */
function extendFromDrawer() {
  const row = selected.value
  drawerOpen.value = false
  extendTarget.value = stayShape(row)
  extendOpen.value = true
}

/** Same rule: the panel closes before the payment dialog takes the overlay. */
function paymentFromDrawer() {
  paymentTarget.value = selected.value
  drawerOpen.value = false
  paymentOpen.value = true
}

function openStay() {
  const row = selected.value
  drawerOpen.value = false
  router.push({ name: 'Stay', params: { id: row.stay } })
}

function openGuest() {
  const row = selected.value
  drawerOpen.value = false
  router.push({ name: 'GuestProfile', params: { id: row.guest } })
}

function openFolio() {
  const row = selected.value
  drawerOpen.value = false
  router.push({ name: 'Folio', params: { id: row.folio } })
}

function openCheckout() {
  const row = selected.value
  drawerOpen.value = false
  router.push({ name: 'Checkout', params: { stay: row.stay } })
}

function reload() {
  board.fetch({ property: property.activeName.value })
}

watch(() => property.activeName.value, reload, { immediate: true })
</script>
