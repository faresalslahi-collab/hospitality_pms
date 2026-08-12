<!--
  Guest 360: the operational guest workspace.

  Evolved in place from the flat profile this route used to render, and
  deliberately still `GuestProfile` at `/guests/:id`. GlobalSearch, the guest
  list, the reservation Guests tab, the in-house drawer and both guest form pages
  all navigate here by route name; a parallel `/guests/:id/360` would have
  orphaned every one of them and left two guest screens to keep in step.

  **Absence is the whole contract.** The server sends one aggregate in which any
  block the caller is not entitled to is a *missing key*, never a blanked one —
  `identifications`, `standing.is_blacklisted`, `standing.blacklist_reason`,
  `stay_statistics` and `current_stay` all behave this way. So every test here is
  `hasField`, never truthiness: `[]` would say "no passport on file" to a
  reservation agent who simply may not see it, and `0` would say "never stayed"
  to someone who may not read Stay. `disclosure` reports what the caller's roles
  allow — never what the record holds — which is what lets a tab be hidden rather
  than shown empty, and lets the difference be stated honestly.

  Four requests, not eleven: the aggregate on open, then one page of each history
  when its tab is first selected. The tabs cannot disagree about which moment
  they are showing, and a lifetime of bookings is never fetched to paint a header.

  There is no Documents tab. Frappe authorises a file download against the
  document it hangs off, at permlevel 0, so a passport scan attached to a Guest
  is readable by every holder of plain Guest read — the permlevel-1 gate on
  `identifications` cannot reach it. Recorded as DEFERRED — DOCUMENT SECURITY
  DESIGN; it needs a `Guest Document` DocType with its own permissions, not a tab.

  There is no History tab either: the events an operator expects in one
  (check-in, checkout) are not logged anywhere in the product, and the audit
  DocTypes that do exist are unreadable by Front Office Agent, who is this
  screen's primary user. A tab that is empty for the person it was built for is
  worse than an absent one.
-->
<template>
  <div>
    <LoadingState v-if="detail.loading && !detail.data" />

    <!-- A permission failure is not a fault this user can retry out of. -->
    <PermissionDenied v-else-if="permissionDenied" :message="errorDetails.message" />
    <ErrorState v-else-if="detail.error" :error="detail.error" :on-retry="load" />

    <template v-else-if="workspace">
      <GuestWorkspaceHeader
        :guest-name="guest.guest_name || route.params.id"
        :guest-id="route.params.id"
        :standing="standing"
        :alert-count="alerts.length"
        :statistics="statistics"
        :current-stay="currentStay"
        :may-read-stay="disclosure.stay"
        :actions="actions"
        :busy="busy"
        @action="runAction"
      />

      <div class="border-b border-outline-gray-1">
        <div
          class="flex gap-1 overflow-x-auto px-5"
          role="tablist"
          :aria-label="t('page.guest_profile.tab.profile')"
          @keydown="onTabKeydown"
        >
          <button
            v-for="(tab, index) in tabs"
            :id="`guest-tab-${tab.key}`"
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
            :aria-controls="`guest-panel-${tab.key}`"
            :tabindex="activeTab === tab.key ? 0 : -1"
            @click="selectTab(tab.key)"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>

      <section v-for="tab in tabs" :key="tab.key" v-bind="panelAttrs(tab.key)">
        <ProfileTab
          v-if="activeTab === 'profile'"
          :guest="guest"
          :care="workspace.care"
          :standing="standing"
        />

        <IdentityTab
          v-else-if="activeTab === 'identity'"
          :identifications="workspace.identifications || []"
          :disclosed="hasField(workspace, 'identifications')"
        />

        <PreferencesTab
          v-else-if="activeTab === 'preferences'"
          :preferences="workspace.preferences || []"
        />

        <AlertsTab v-else-if="activeTab === 'alerts'" :alerts="alerts" />

        <ReservationsTab
          v-else-if="activeTab === 'reservations'"
          :reservations="reservations.data?.reservations || []"
          :loading="reservations.loading"
          :error="reservations.error"
          :page="pages.reservations"
          :page-length="PAGE_LENGTH"
          @page-change="onPage('reservations', $event)"
          @retry="loadHistory('reservations')"
        />

        <StaysTab
          v-else-if="activeTab === 'stays'"
          :stays="stays.data?.stays || []"
          :loading="stays.loading"
          :error="stays.error"
          :page="pages.stays"
          :page-length="PAGE_LENGTH"
          @page-change="onPage('stays', $event)"
          @retry="loadHistory('stays')"
        />

        <FoliosTab
          v-else-if="activeTab === 'folios'"
          :folios="folios.data?.folios || []"
          :loading="folios.loading"
          :error="folios.error"
          :page="pages.folios"
          :page-length="PAGE_LENGTH"
          @page-change="onPage('folios', $event)"
          @retry="loadHistory('folios')"
        />
      </section>

      <MergeGuestDialog
        v-if="disclosure.merge"
        v-model="mergeOpen"
        :target="route.params.id"
        :target-name="guest.guest_name || ''"
        :saving="busy === 'merge'"
        :error-message="mergeError"
        @merge="onMerge"
      />
    </template>
  </div>
</template>

<script setup>
import { toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AlertsTab from '@/components/guest/AlertsTab.vue'
import FoliosTab from '@/components/guest/FoliosTab.vue'
import GuestWorkspaceHeader from '@/components/guest/GuestWorkspaceHeader.vue'
import IdentityTab from '@/components/guest/IdentityTab.vue'
import MergeGuestDialog from '@/components/guest/MergeGuestDialog.vue'
import PreferencesTab from '@/components/guest/PreferencesTab.vue'
import ProfileTab from '@/components/guest/ProfileTab.vue'
import ReservationsTab from '@/components/guest/ReservationsTab.vue'
import StaysTab from '@/components/guest/StaysTab.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import PermissionDenied from '@/components/states/PermissionDenied.vue'
import {
  getGuestWorkspaceResource,
  guestFoliosResource,
  guestReservationsResource,
  guestStaysResource,
  hasField,
  mergeGuestsResource,
} from '@/resources/guests'
import { normaliseError } from '@/utils/errors'
import { isRTL, t } from '@/utils/i18n'

/** Matches the server's own default page. The server owns the ceiling. */
const PAGE_LENGTH = 20

const route = useRoute()
const router = useRouter()

const detail = getGuestWorkspaceResource()
const reservations = guestReservationsResource()
const stays = guestStaysResource()
const folios = guestFoliosResource()
const merge = mergeGuestsResource()

const tabButtons = ref([])
const busy = ref('')
const mergeOpen = ref(false)
const mergeError = ref('')

const pages = reactive({ reservations: 1, stays: 1, folios: 1 })

const workspace = computed(() => detail.data || null)
const guest = computed(() => workspace.value?.guest || {})
const standing = computed(() => workspace.value?.standing || {})
const alerts = computed(() => workspace.value?.alerts || [])
const disclosure = computed(() => workspace.value?.disclosure || {})

/** Absent when the caller may not read Stay — not zero. */
const statistics = computed(() =>
  hasField(workspace.value, 'stay_statistics') ? workspace.value.stay_statistics : null,
)

const currentStay = computed(() =>
  hasField(workspace.value, 'current_stay') ? workspace.value.current_stay : null,
)

const errorDetails = computed(() => normaliseError(detail.error))
const permissionDenied = computed(
  () => Boolean(detail.error) && errorDetails.value.kind === 'permission',
)

/**
 * Tabs the caller may actually use.
 *
 * A tab whose source DocType is undisclosed is not rendered disabled or empty —
 * it is absent, exactly as the field groups are, so the screen never invites
 * someone to click through to a refusal.
 */
const TAB_SOURCE = {
  profile: null,
  identity: null,
  preferences: null,
  alerts: null,
  reservations: 'reservation',
  stays: 'stay',
  folios: 'folio',
}

const HISTORY_TABS = {
  reservations: { resource: () => reservations, key: 'reservations' },
  stays: { resource: () => stays, key: 'stays' },
  folios: { resource: () => folios, key: 'folios' },
}

const tabKeys = computed(() =>
  Object.keys(TAB_SOURCE).filter((key) => {
    const source = TAB_SOURCE[key]

    return !source || disclosure.value[source]
  }),
)

const tabs = computed(() =>
  tabKeys.value.map((key) => ({ key, label: t(`page.guest_profile.tab.${key}`) })),
)

const activeTab = computed(() => {
  const wanted = String(route.query.tab || '')

  return tabKeys.value.includes(wanted) ? wanted : 'profile'
})

function panelAttrs(key) {
  return {
    id: `guest-panel-${key}`,
    role: 'tabpanel',
    'aria-labelledby': `guest-tab-${key}`,
    tabindex: 0,
    hidden: activeTab.value !== key,
    class: activeTab.value === key ? 'p-5' : '',
  }
}

/** `replace`, not `push`: switching tabs is not a step in the agent's history. */
function selectTab(key) {
  if (!tabKeys.value.includes(key) || key === activeTab.value) return

  router.replace({ query: { ...route.query, tab: key } })
}

function onTabKeydown(event) {
  const forward = isRTL.value ? 'ArrowLeft' : 'ArrowRight'
  const backward = isRTL.value ? 'ArrowRight' : 'ArrowLeft'

  if (![forward, backward, 'Home', 'End'].includes(event.key)) return

  event.preventDefault()

  const keys = tabKeys.value
  const current = keys.indexOf(activeTab.value)

  let next = current

  if (event.key === forward) next = (current + 1) % keys.length
  else if (event.key === backward) next = (current - 1 + keys.length) % keys.length
  else if (event.key === 'Home') next = 0
  else next = keys.length - 1

  selectTab(keys[next])
  tabButtons.value[next]?.focus()
}

function load() {
  return detail.fetch({ guest: route.params.id })
}

function loadHistory(which, page = pages[which]) {
  const entry = HISTORY_TABS[which]

  if (!entry) return undefined

  return entry
    .resource()
    .fetch({
      guest: route.params.id,
      limit: PAGE_LENGTH,
      start: (page - 1) * PAGE_LENGTH,
    })
    .catch(() => {
      // Reported through the table's own error slot, which distinguishes a
      // refusal from a fault. Swallowed here so an unhandled rejection does not
      // reach the console for a state the screen already renders.
    })
}

function onPage(which, page) {
  pages[which] = page
  loadHistory(which, page)
}

/**
 * Quick actions, built from what the server disclosed.
 *
 * Every one of them hands off to a route or dialog that already exists and owns
 * its own rules; none of them is a generic write from this screen.
 */
const actions = computed(() => {
  const id = route.params.id
  const list = [
    {
      key: 'reservation',
      label: t('page.guest_profile.new_reservation'),
      variant: 'solid',
      theme: 'gray',
    },
    { key: 'walk_in', label: t('page.guest_profile.walk_in') },
  ]

  if (currentStay.value?.name) {
    list.push({ key: 'stay', label: t('page.guest_profile.open_stay') })

    if (disclosure.value.folio && currentStay.value.folio) {
      list.push({ key: 'folio', label: t('page.guest_profile.open_folio') })
    }
  }

  list.push({ key: 'edit', label: t('page.guest_profile.edit_guest') })

  if (disclosure.value.merge) {
    list.push({ key: 'merge', label: t('page.guest_profile.merge_guest'), theme: 'red' })
  }

  return list.map((action) => ({ ...action, id }))
})

function runAction(key) {
  const id = route.params.id

  if (key === 'reservation') return router.push({ name: 'ReservationNew', query: { guest: id } })
  if (key === 'walk_in') return router.push({ name: 'WalkIn', query: { guest: id } })
  if (key === 'edit') return router.push({ name: 'GuestEdit', params: { id } })
  if (key === 'stay') return router.push({ name: 'Stay', params: { id: currentStay.value.name } })
  if (key === 'folio') return router.push({ name: 'Folio', params: { id: currentStay.value.folio } })

  if (key === 'merge') {
    mergeError.value = ''
    mergeOpen.value = true
  }

  return undefined
}

async function onMerge({ source, reason }) {
  busy.value = 'merge'
  mergeError.value = ''

  try {
    await merge.submit({ source, target: route.params.id, reason })
    mergeOpen.value = false
    await load()
    resetHistories()
    toast.success(t('page.guest_profile.merged'))
  } catch (error) {
    mergeError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

/** A merge repoints history onto this guest, so every page is stale after one. */
function resetHistories() {
  pages.reservations = 1
  pages.stays = 1
  pages.folios = 1

  Object.keys(HISTORY_TABS).forEach((which) => {
    if (HISTORY_TABS[which].resource().data) loadHistory(which, 1)
  })
}

watch(() => route.params.id, load, { immediate: true })

// Each history is fetched when its tab is first opened, and refetched when the
// guest changes underneath it.
watch(
  [activeTab, () => route.params.id],
  ([tab]) => {
    if (HISTORY_TABS[tab]) loadHistory(tab, pages[tab])
  },
  { immediate: true },
)
</script>
