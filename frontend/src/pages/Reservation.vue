<!--
  The Reservation Workspace (16.7.2).

  One booking, one request, six tabs. `reservation_workspace.get_workspace` returns
  the whole aggregate because the tabs are views of a single reservation, and a
  screen that fetched once per tab would show six different moments of it. The
  history is the one exception: a hundred log rows are not needed to paint the page,
  so that tab fetches when it is opened.

  **The server owns every decision this screen renders.** Which verbs are reachable
  is `allowed_transitions`; what may be changed is `editability`. Neither is
  re-derived from the status — there is exactly one statement of the state machine
  and it is not in Vue. A stale offer is not pre-emptively disabled either: the
  services re-read the booking under a lock, so an offer that has expired fails
  cleanly with the server's own words.

  **Absence is meaning.** `guest_standing`, `corporate` and `deposit.credited` are
  omitted for a caller who is not entitled to them, and the tabs report that as
  withheld from the reader rather than as a zero, a dash or "none".

  **One collected edit, one call.** The Overview tab's three details and the Notes
  tab's two fields accumulate into a single draft and save through
  `update_reservation_details` — a field map the service validates, never a document
  save. Leaving with that draft unsaved is stopped and asked about. The transactional
  verbs (confirm, guarantee, cancel, no-show, assign, check-in) are separate server
  operations with their own audit records and are never folded into the draft.

  Tab state lives in the URL (`?tab=notes`), so a reload and a shared link land an
  agent on the same tab.
-->
<template>
  <div>
    <LoadingState v-if="detail.loading && !detail.data" />

    <!-- A permission failure is not a fault this user can retry out of. -->
    <PermissionDenied v-else-if="permissionDenied" :message="errorDetails.message" />
    <ErrorState v-else-if="detail.error" :error="detail.error" :on-retry="load" />

    <div v-else-if="reservation">
      <WorkspaceHeader
        :reservation="reservation"
        :deposit="deposit"
        :assigned-rooms="assignedRooms"
        :lines-differ="linesDiffer"
        :actions="actions"
        :busy="busy"
        @open-tab="selectTab"
      />

      <!--
        The draft is the workspace's, not a tab's: an edit made on Overview and a
        note typed on Notes are one save. The strip stays visible on every tab so
        the change cannot be forgotten behind a tab that no longer shows it.
      -->
      <div
        v-if="dirty"
        class="flex flex-wrap items-center justify-between gap-3 border-b border-outline-amber-1
          bg-surface-amber-1 px-5 py-2"
      >
        <p class="text-p-sm font-medium text-ink-amber-3">{{ t('page.reservation.unsaved_title') }}</p>
        <div class="flex items-center gap-2">
          <Button variant="subtle" :disabled="busy === 'save'" @click="discard">
            {{ t('page.reservation.discard') }}
          </Button>
          <Button variant="solid" :loading="busy === 'save'" @click="save">
            {{ t('page.reservation.save') }}
          </Button>
        </div>
      </div>

      <div v-if="actionError" class="px-5 pt-3">
        <ErrorMessage :message="actionError" />
      </div>

      <!--
        Tabs scroll rather than wrap or shrink: six labels do not fit a phone, and a
        tab that has slid off the edge of the screen is a tab an agent cannot reach.
      -->
      <div class="border-b border-outline-gray-1 bg-surface-white">
        <div class="overflow-x-auto px-5">
          <div
            role="tablist"
            :aria-label="t('page.reservation.workspace')"
            class="flex min-w-max items-center gap-1"
            @keydown="onTabKeydown"
          >
            <button
              v-for="tab in tabs"
              :id="`reservation-tab-${tab.key}`"
              :key="tab.key"
              :ref="(el) => setTabRef(tab.key, el)"
              type="button"
              role="tab"
              :aria-selected="tab.key === activeTab ? 'true' : 'false'"
              :aria-controls="`reservation-panel-${tab.key}`"
              :tabindex="tab.key === activeTab ? 0 : -1"
              class="whitespace-nowrap border-b-2 px-3 py-2 text-p-sm"
              :class="
                tab.key === activeTab
                  ? 'border-outline-gray-4 font-medium text-ink-gray-9'
                  : 'border-transparent text-ink-gray-6 hover:text-ink-gray-8'
              "
              @click="selectTab(tab.key)"
            >
              {{ tab.label }}
            </button>
          </div>
        </div>
      </div>

      <section v-bind="panelAttrs('overview')">
        <OverviewTab
          v-if="activeTab === 'overview'"
          :reservation="reservation"
          :editability="editability"
          :values="values"
          :corporate="corporate"
          :lines-differ="linesDiffer"
          @edit="onEdit"
        />
      </section>

      <!--
        Rooms & rates owns every per-line verb: the interval, the room type, the plan,
        the assignment and the removal all act on one `Reservation Room` and are
        offered per card. Assignment is emitted rather than performed there, because
        `AssignRoomDialog` is this page's and is already hardened; `changed` means a
        line operation succeeded, and the aggregate is re-read whole because each of
        them re-derives the booking's totals and its header interval.
      -->
      <section v-bind="panelAttrs('rooms')">
        <RoomsRatesTab
          v-if="activeTab === 'rooms'"
          :reservation="reservation"
          :rooms="rooms"
          :editability="editability"
          @assign="openAssign"
          @changed="onTransacted"
        />
      </section>

      <section v-bind="panelAttrs('guests')">
        <GuestsTab v-if="activeTab === 'guests'" :reservation="reservation" :standing="guestStanding" />
      </section>

      <section v-bind="panelAttrs('deposit')">
        <DepositTab
          v-if="activeTab === 'deposit' && deposit"
          :reservation="reservation"
          :deposit="deposit"
          :rooms="rooms"
        />
      </section>

      <section v-bind="panelAttrs('notes')">
        <NotesTab
          v-if="activeTab === 'notes'"
          :reservation="reservation"
          :editability="editability"
          :values="values"
          @edit="onEdit"
        />
      </section>

      <section v-bind="panelAttrs('history')">
        <HistoryTab
          v-if="activeTab === 'history'"
          :entries="historyEntries"
          :loading="history.loading"
          :error="history.error"
          :currency="reservation.currency"
          @retry="loadHistory"
        />
      </section>
    </div>

    <!--
      Cancellation and no-show are whole-reservation verbs: `_propagate_status`
      stamps every room line, so both dialogs state the scope before anything else
      and are given the room count the server sent.
    -->
    <CancelReservationDialog
      v-model="cancelOpen"
      :reservation="reservation?.name || ''"
      :rooms="reservation?.total_rooms ?? null"
      :currency="reservation?.currency || null"
      @cancelled="onTransacted"
    />

    <MarkNoShowDialog
      v-model="noShowOpen"
      :reservation="reservation?.name || ''"
      :rooms="reservation?.total_rooms ?? null"
      :currency="reservation?.currency || null"
      @marked="onTransacted"
    />

    <AssignRoomDialog
      v-model="assignOpen"
      :reservation="reservation?.name || ''"
      :line="assignLine"
      @changed="onAssigned"
    />

    <!--
      Leaving with an unsaved draft. The guard returns a promise the router waits
      on, so the navigation is genuinely held rather than allowed and undone.
    -->
    <Dialog v-model="leaveOpen" :options="{ title: t('page.reservation.unsaved_title') }">
      <template #body-content>
        <div class="space-y-3">
          <p class="text-p-sm text-ink-gray-6">{{ t('page.reservation.unsaved_message') }}</p>

          <div class="flex flex-wrap justify-end gap-2">
            <Button variant="subtle" @click="stayHere">{{ t('page.reservation.unsaved_stay') }}</Button>
            <Button variant="solid" theme="red" @click="confirmLeave">
              {{ t('page.reservation.unsaved_leave') }}
            </Button>
          </div>
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'

import AssignRoomDialog from '@/components/AssignRoomDialog.vue'
import CancelReservationDialog from '@/components/CancelReservationDialog.vue'
import MarkNoShowDialog from '@/components/MarkNoShowDialog.vue'
import DepositTab from '@/components/reservation/DepositTab.vue'
import GuestsTab from '@/components/reservation/GuestsTab.vue'
import HistoryTab from '@/components/reservation/HistoryTab.vue'
import NotesTab from '@/components/reservation/NotesTab.vue'
import OverviewTab from '@/components/reservation/OverviewTab.vue'
import RoomsRatesTab from '@/components/reservation/RoomsRatesTab.vue'
import WorkspaceHeader from '@/components/reservation/WorkspaceHeader.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import PermissionDenied from '@/components/states/PermissionDenied.vue'
import { hasField } from '@/resources/guests'
import { NO_SHOW_ROLES, confirmReservationResource, guaranteeReservationResource } from '@/resources/reservations'
import {
  DETAIL_EDIT_FIELDS,
  NOTE_EDIT_FIELDS,
  reservationHistoryResource,
  reservationWorkspaceResource,
  updateReservationDetailsResource,
} from '@/resources/reservationWorkspace'
import { session } from '@/stores/session'
import { normaliseError } from '@/utils/errors'
import { isRTL, t } from '@/utils/i18n'

const route = useRoute()
const router = useRouter()

const detail = reservationWorkspaceResource()
const history = reservationHistoryResource()
const updateDetails = updateReservationDetailsResource()
const confirmResource = confirmReservationResource()
const guaranteeRes = guaranteeReservationResource()

const busy = ref('')
const actionError = ref('')
const assignOpen = ref(false)
const assignLine = ref(null)
const cancelOpen = ref(false)
const noShowOpen = ref(false)
const leaveOpen = ref(false)

/** Tab order is fixed and the keys are the URL's, so a shared link is stable. */
const TAB_KEYS = ['overview', 'rooms', 'guests', 'deposit', 'notes', 'history']

const tabs = computed(() =>
  TAB_KEYS.map((key) => ({ key, label: t(`page.reservation.tab.${key}`) })),
)

const reservation = computed(() => detail.data?.reservation || null)
const rooms = computed(() => detail.data?.rooms || [])
const deposit = computed(() => detail.data?.deposit ?? null)
const editability = computed(() => detail.data?.editability || {})
const allowed = computed(() => detail.data?.allowed_transitions || [])
const historyEntries = computed(() => history.data?.entries || [])

/**
 * The two permission-gated sections, as presence rather than value.
 *
 * `hasField`, not truthiness: the server omits the whole key for a caller it will
 * not disclose to, and `null` from a present key would mean something different.
 */
const guestStanding = computed(() =>
  hasField(detail.data, 'guest_standing') ? detail.data.guest_standing : null,
)
const corporate = computed(() => (hasField(detail.data, 'corporate') ? detail.data.corporate : null))

const errorDetails = computed(() => normaliseError(detail.error))
const permissionDenied = computed(() => Boolean(detail.error) && errorDetails.value.kind === 'permission')

/** Counted from the lines the server sent; the total is the server's own field. */
const assignedRooms = computed(() => rooms.value.filter((line) => line.assigned_room).length)

/**
 * Whether the room lines hold different intervals.
 *
 * `refresh_header_dates` writes min(arrival)/max(departure) across the lines, so
 * once they disagree the header interval covers nights no room occupies. This is a
 * comparison of what the server sent, not arithmetic on dates.
 */
const linesDiffer = computed(
  () => new Set(rooms.value.map((line) => `${line.arrival_date}|${line.departure_date}`)).size > 1,
)

// --- tabs ------------------------------------------------------------------

const activeTab = computed(() => {
  const wanted = String(route.query.tab || '')

  return TAB_KEYS.includes(wanted) ? wanted : 'overview'
})

const tabElements = {}

function setTabRef(key, el) {
  tabElements[key] = el || null
}

function panelAttrs(key) {
  return {
    id: `reservation-panel-${key}`,
    role: 'tabpanel',
    'aria-labelledby': `reservation-tab-${key}`,
    tabindex: 0,
    hidden: activeTab.value !== key,
    class: activeTab.value === key ? 'p-5' : '',
  }
}

/** `replace`, not `push`: switching tabs is not a step in the agent's history. */
function selectTab(key) {
  if (!TAB_KEYS.includes(key) || key === activeTab.value) return

  router.replace({ query: { ...route.query, tab: key } })
}

/**
 * Arrow keys move between tabs, and the direction of "forward" follows the
 * document: in an Arabic session the tabs are laid out right to left, so
 * ArrowLeft is the next tab and ArrowRight the previous one.
 */
function onTabKeydown(event) {
  const forward = isRTL.value ? 'ArrowLeft' : 'ArrowRight'
  const backward = isRTL.value ? 'ArrowRight' : 'ArrowLeft'
  const index = TAB_KEYS.indexOf(activeTab.value)

  let next = null

  if (event.key === forward) next = (index + 1) % TAB_KEYS.length
  else if (event.key === backward) next = (index - 1 + TAB_KEYS.length) % TAB_KEYS.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = TAB_KEYS.length - 1
  else return

  event.preventDefault()
  selectTab(TAB_KEYS[next])
  tabElements[TAB_KEYS[next]]?.focus?.()
}

// --- the collected edit ----------------------------------------------------

const draft = reactive({})

const dirty = computed(() => Object.keys(draft).length > 0)

/** What the tabs bind to: the server's value unless the draft has changed it. */
const values = computed(() => {
  const merged = {}

  for (const field of DETAIL_EDIT_FIELDS) {
    merged[field] = field in draft ? draft[field] : (reservation.value?.[field] ?? '')
  }

  return merged
})

/**
 * A field edited back to what the server holds is not a change.
 *
 * Keeping it in the draft would send the server a no-op write and, worse, leave the
 * page claiming unsaved work that does not exist — after which the leave warning
 * becomes noise an agent learns to dismiss.
 */
function onEdit({ field, value }) {
  if (!DETAIL_EDIT_FIELDS.includes(field)) return

  const next = value ?? ''

  if (next === (reservation.value?.[field] ?? '')) delete draft[field]
  else draft[field] = next
}

function clearDraft() {
  for (const field of Object.keys(draft)) delete draft[field]
}

function discard() {
  clearDraft()
  actionError.value = ''
}

/** One call for every collected field, whichever tab it was typed on. */
async function save() {
  if (!dirty.value || busy.value) return

  const changes = { ...draft }

  busy.value = 'save'
  actionError.value = ''

  try {
    await updateDetails.submit({ reservation: route.params.id, changes })
    clearDraft()
    await load()

    const notesOnly = Object.keys(changes).every((field) => NOTE_EDIT_FIELDS.includes(field))

    toast.success(notesOnly ? t('page.reservation.notes.saved') : t('page.reservation.updated'))
  } catch (error) {
    const details = normaliseError(error)

    actionError.value = details.message
    toast.error(details.message)
  } finally {
    busy.value = ''
  }
}

// --- transitions -----------------------------------------------------------

/**
 * The header carries whole-booking verbs only.
 *
 * Room assignment is not one of them. It names a room *line*, and a booking with
 * three lines has three answers to it — so it belongs to Rooms & rates, which shows
 * a control on each card and emits the line it was pressed on. The dialog stays
 * here, because it is the page's and is shared with nothing else.
 */
const actions = computed(() => {
  const list = []

  if (allowed.value.includes('Checked In')) {
    list.push({
      key: 'check_in',
      label: t('page.reservation.check_in'),
      variant: 'solid',
      theme: 'gray',
      run: () => router.push({ name: 'CheckIn', params: { reservation: route.params.id } }),
    })
  }

  if (allowed.value.includes('Confirmed')) {
    list.push({
      key: 'confirm',
      label: t('page.reservation.confirm'),
      variant: 'solid',
      theme: 'gray',
      run: () => run('confirm', () => confirmResource.submit({ reservation: route.params.id })),
    })
  }

  if (allowed.value.includes('Guaranteed')) {
    list.push({
      key: 'guarantee',
      label: t('page.reservation.guarantee'),
      variant: 'subtle',
      theme: 'gray',
      run: () =>
        run('guarantee', () =>
          guaranteeRes.submit({ reservation: route.params.id, guarantee_type: 'Credit Card' }),
        ),
    })
  }

  if (allowed.value.includes('Cancelled')) {
    list.push({
      key: 'cancel',
      label: t('page.reservation.cancel'),
      variant: 'subtle',
      theme: 'red',
      run: () => {
        actionError.value = ''
        cancelOpen.value = true
      },
    })
  }

  // `NO_SHOW_ROLES` excludes Front Office Agent: a no-show is an end-of-day audit
  // judgement, and the server refuses the verb for that role every time.
  if (allowed.value.includes('No Show') && session.hasRole(NO_SHOW_ROLES)) {
    list.push({
      key: 'no_show',
      label: t('page.arrivals.action.no_show'),
      variant: 'subtle',
      theme: 'red',
      run: () => {
        actionError.value = ''
        noShowOpen.value = true
      },
    })
  }

  return list
})

function openAssign(line) {
  assignLine.value = line
  assignOpen.value = true
}

function onAssigned() {
  toast.success(t('page.reservation.assigned_room_saved'))
  load()
}

/** A transactional verb succeeded, so the whole aggregate is re-read. */
function onTransacted() {
  load()
}

async function run(key, fn) {
  busy.value = key
  actionError.value = ''

  try {
    await fn()
    await load()
    toast.success(t('page.reservation.updated'))
  } catch (error) {
    const details = normaliseError(error)

    actionError.value = details.message
    toast.error(details.message)
  } finally {
    busy.value = ''
  }
}

// --- loading ---------------------------------------------------------------

function load() {
  return detail.fetch({ reservation: route.params.id })
}

function loadHistory() {
  return history.fetch({ reservation: route.params.id })
}

watch(
  () => route.params.id,
  (id) => {
    // A draft belongs to the booking it was typed against and never travels.
    clearDraft()
    actionError.value = ''
    if (id) load()
  },
  { immediate: true },
)

// The log is fetched when its tab is opened, and refetched on every opening: a
// transition performed from the header adds a row an agent expects to see.
watch(
  [activeTab, () => route.params.id],
  ([tab, id]) => {
    if (tab === 'history' && id) loadHistory()
  },
  { immediate: true },
)

// --- leaving with an unsaved draft -----------------------------------------

let resolveLeave = null

onBeforeRouteLeave(() => {
  if (!dirty.value) return true

  leaveOpen.value = true

  return new Promise((resolve) => {
    resolveLeave = resolve
  })
})

function settleLeave(allowLeave) {
  leaveOpen.value = false

  const resolve = resolveLeave

  resolveLeave = null
  resolve?.(allowLeave)
}

function confirmLeave() {
  settleLeave(true)
}

function stayHere() {
  settleLeave(false)
}
</script>
