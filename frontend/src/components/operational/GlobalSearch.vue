<!--
  Global operational search: one box that finds the record the desk is talking
  about (16.7.1 Front Desk Command Center).

  A reusable component, not a page. It is mounted once in the shell and is the
  fastest path from "Mr Haddad, room 412" to the screen that answers it.

  What it is not: it holds no business logic, no client-side filtering and no
  second endpoint. `search.operational_search` is the only source of results, and
  they are rendered in the order the server returned them within a fixed
  operational grouping — who the guest is, what they booked, what they are living
  in, which room, which folio. Nothing here re-ranks, re-scores or merges.

  PRIVACY BOUNDARY. Every row is projected onto exactly the seven fields the
  frozen contract carries (see `toOption`), and the template reads only that
  projection. A field the server did not promise — a blacklist reason, an
  identification number, an alert body, an accounting internal — has nowhere to
  land even if a future payload includes it. This is structural, not a review
  habit, and its spec proves it.

  The stale-response rule is the other thing that is load-bearing: a typeahead
  fires overlapping requests, and the classic defect is the slow answer to an
  abandoned query landing on top of the fast answer to the current one. Every
  request carries a token; only the newest token may touch the panel.

  Direction is never assumed: logical utilities only, so an Arabic session
  mirrors with no second stylesheet.
-->
<template>
  <div ref="root" class="relative w-full" data-global-search>
    <label :for="inputId" class="sr-only">{{ t('ui.search.label') }}</label>

    <div class="relative">
      <FeatherIcon
        name="search"
        class="pointer-events-none absolute inset-y-0 start-2 my-auto size-4 text-ink-gray-4"
        aria-hidden="true"
      />

      <!--
        A plain input rather than a form control wrapper: combobox semantics
        (role, aria-expanded, aria-controls, aria-activedescendant) have to sit on
        the element itself, and the active option is announced from here.
      -->
      <input
        :id="inputId"
        ref="input"
        type="text"
        role="combobox"
        autocomplete="off"
        spellcheck="false"
        class="w-full rounded border border-outline-gray-2 bg-surface-white py-1.5 pe-3 ps-8 text-start text-p-sm text-ink-gray-9 placeholder:text-ink-gray-4 focus:border-outline-gray-3 focus:outline-none"
        :placeholder="t('ui.search.placeholder')"
        :aria-label="t('ui.search.label')"
        :aria-expanded="open ? 'true' : 'false'"
        :aria-controls="listboxId"
        :aria-activedescendant="activeDescendant || undefined"
        :aria-describedby="hintId"
        :value="query"
        data-search-input
        @input="onInput"
        @focus="onFocus"
        @keydown="onKeydown"
      />
    </div>

    <!--
      Announced, not just drawn. Kept outside the panel so the count is still
      spoken when the panel closes, and `role="status"` so it never interrupts.
    -->
    <p class="sr-only" role="status" aria-live="polite" data-search-live>{{ liveMessage }}</p>

    <div
      v-if="open"
      class="absolute inset-x-0 top-full z-30 mt-1 max-h-96 overflow-y-auto rounded border border-outline-gray-1 bg-surface-white shadow-lg"
      data-search-panel
    >
      <div class="flex items-start justify-between gap-2 border-b border-outline-gray-1 px-3 py-2">
        <p :id="hintId" class="text-start text-xs text-ink-gray-5" data-search-hint>
          {{ hintText }}
        </p>

        <Button
          size="sm"
          variant="ghost"
          :aria-label="t('common.close')"
          :title="t('common.close')"
          data-search-close
          @click="closeAndRestoreFocus"
        >
          <template #icon><FeatherIcon name="x" class="size-4" aria-hidden="true" /></template>
        </Button>
      </div>

      <ErrorState v-if="error" :error="error" />

      <!-- Only when there is nothing on screen yet: see the busy branch below. -->
      <LoadingState v-else-if="loading && !hasResults" :title="t('ui.search.searching')" message="" />

      <EmptyState
        v-else-if="searched && !hasResults"
        :message="t('ui.search.no_results', { query: shownQuery })"
      />

      <!--
        Results already on screen are never blanked by the next keystroke's
        request. The panel dims and reports itself busy instead, because a
        half-read room number should not vanish mid-sentence.
      -->
      <div v-else-if="hasResults" :aria-busy="busy ? 'true' : 'false'" :class="busy ? 'opacity-60' : ''">
        <ul :id="listboxId" role="listbox" :aria-label="t('ui.search.label')" class="py-1">
          <li
            v-for="group in groups"
            :key="group.type"
            role="group"
            :aria-labelledby="groupHeadingId(group.type)"
          >
            <p
              :id="groupHeadingId(group.type)"
              class="px-3 py-1 text-start text-xs uppercase tracking-wide text-ink-gray-5"
              data-search-group
            >
              {{ group.label }}
            </p>

            <div
              v-for="option in group.options"
              :id="optionId(option)"
              :key="option.key"
              role="option"
              :aria-selected="option === activeOption ? 'true' : 'false'"
              class="flex cursor-pointer items-start justify-between gap-2 px-3 py-2"
              :class="option === activeOption ? 'bg-surface-gray-3' : 'hover:bg-surface-gray-2'"
              data-search-option
              @click="openResult(option)"
              @mousemove="activeIndex = flatOptions.indexOf(option)"
            >
              <span class="min-w-0 text-start">
                <span class="block truncate text-p-sm font-medium text-ink-gray-9">
                  {{ option.primary }}
                </span>
                <span v-if="option.secondary" class="block truncate text-p-sm text-ink-gray-6">
                  {{ option.secondary }}
                </span>
                <span v-if="option.summary" class="block truncate text-xs text-ink-gray-5">
                  {{ option.summary }}
                </span>
              </span>

              <!--
                Both chips are words. Which kind of record this is, and what state
                it is in, are never carried by colour alone.
              -->
              <span class="flex shrink-0 flex-wrap items-center justify-end gap-1">
                <Badge variant="subtle" theme="gray" :label="group.label" />
                <Badge v-if="option.status" variant="subtle" theme="blue" :label="option.status" />
              </span>
            </div>
          </li>
        </ul>

        <p
          v-if="truncated"
          class="border-t border-outline-gray-1 px-3 py-2 text-start text-xs text-ink-gray-6"
          data-search-truncated
        >
          {{ t('ui.search.truncated') }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon } from 'frappe-ui'
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRouter } from 'vue-router'

import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import {
  SEARCH_DEBOUNCE_MS,
  SEARCH_LIMIT,
  SEARCH_MIN_LENGTH,
  operationalSearchResource,
} from '@/resources/search'
import { property } from '@/stores/property'
import { t } from '@/utils/i18n'

const props = defineProps({
  /**
   * Debounce window in milliseconds. A prop rather than a hard-coded delay so a
   * test can drive the timing instead of sleeping for a quarter of a second.
   */
  debounceMs: { type: Number, default: SEARCH_DEBOUNCE_MS },
  /** Per-entity cap asked of the server; it clamps to its own maximum. */
  limit: { type: Number, default: SEARCH_LIMIT },
})

/**
 * The five searchable types, in fixed front desk order: who the guest is, what
 * they booked, what they are living in, which room, which folio. The same order
 * the service returns, restated here so the grouping cannot drift from it.
 */
const ENTITY_ORDER = ['Guest', 'Reservation', 'Stay', 'Hotel Room', 'Guest Folio']

const GROUP_LABEL_KEY = {
  Guest: 'ui.search.group.guest',
  Reservation: 'ui.search.group.reservation',
  Stay: 'ui.search.group.stay',
  'Hotel Room': 'ui.search.group.room',
  'Guest Folio': 'ui.search.group.folio',
}

/**
 * Where each kind of record lives.
 *
 * This map is deliberately the frontend's: the endpoint returns no route,
 * because Vue route names are not the server's business.
 *
 * `Hotel Room` goes to the rack with no parameter. `pages/RoomRack.vue` loads
 * the whole rack for the active property and holds the opened room in local
 * state — it reads neither a route param nor a query — so there is nothing to
 * pass it. Inventing `?room=` here would look like deep-linking and do nothing.
 * Raised for 16.7.4.
 */
const ROUTE_FOR_TYPE = {
  Guest: (id) => ({ name: 'GuestProfile', params: { id } }),
  Reservation: (id) => ({ name: 'Reservation', params: { id } }),
  Stay: (id) => ({ name: 'Stay', params: { id } }),
  'Guest Folio': (id) => ({ name: 'Folio', params: { id } }),
  'Hotel Room': () => ({ name: 'RoomRack' }),
}

const router = useRouter()
const resource = operationalSearchResource()

const baseId = useId()
const inputId = `${baseId}-input`
const listboxId = `${baseId}-listbox`
const hintId = `${baseId}-hint`

const root = ref(null)
const input = ref(null)

const query = ref('')
const open = ref(false)

/**
 * Panel state is the component's own, never the resource's.
 *
 * `resource.data`, `resource.loading` and `resource.error` belong to whichever
 * call touched them last, which for overlapping typeahead requests is not
 * necessarily the current one. Reading them is the stale-result bug.
 */
const results = ref([])
const truncated = ref(false)
const loading = ref(false)
const error = ref(null)
/** The query the rows on screen actually answer — not what is in the box now. */
const shownQuery = ref('')
const searched = ref(false)

const activeIndex = ref(0)

const belowMinimum = computed(() => query.value.trim().length < SEARCH_MIN_LENGTH)

/**
 * One row, projected onto the contract and nothing else.
 *
 * The seven fields below are the whole of what the panel can render. Anything
 * else the payload happens to carry is dropped here, once, rather than being
 * guarded at each of the places it could otherwise be printed.
 */
function toOption(row) {
  return {
    key: `${row.type}:${row.id}`,
    type: row.type,
    id: row.id,
    primary: row.primary_label || row.id,
    secondary: row.secondary_label || '',
    status: row.status || '',
    summary: row.safe_summary || '',
  }
}

const options = computed(() =>
  (results.value || [])
    // A type this build has no heading and no route for is not rendered: it
    // would be an unlabelled row that goes nowhere.
    .filter((row) => row && row.id && ENTITY_ORDER.includes(row.type))
    .map(toOption),
)

const groups = computed(() =>
  ENTITY_ORDER.map((type) => ({
    type,
    label: t(GROUP_LABEL_KEY[type]),
    options: options.value.filter((option) => option.type === type),
  })).filter((group) => group.options.length > 0),
)

/** Visual order, flattened — what the arrow keys walk. */
const flatOptions = computed(() => groups.value.flatMap((group) => group.options))

const hasResults = computed(() => flatOptions.value.length > 0)
const busy = computed(() => loading.value && hasResults.value)

const activeOption = computed(() => flatOptions.value[activeIndex.value] || null)

function optionId(option) {
  return `${baseId}-option-${option.key.replace(/[^A-Za-z0-9_-]+/g, '-')}`
}

function groupHeadingId(type) {
  return `${baseId}-group-${type.replace(/[^A-Za-z0-9_-]+/g, '-')}`
}

const activeDescendant = computed(() => (activeOption.value ? optionId(activeOption.value) : ''))

/** Below the minimum the panel explains itself; otherwise it explains the keys. */
const hintText = computed(() =>
  belowMinimum.value
    ? t('ui.search.min_length', { count: SEARCH_MIN_LENGTH })
    : t('ui.search.keyboard_hint'),
)

const liveMessage = computed(() => {
  if (!open.value) return ''
  if (belowMinimum.value) return t('ui.search.min_length', { count: SEARCH_MIN_LENGTH })
  if (error.value) return t('state.error_title')
  if (loading.value && !hasResults.value) return t('ui.search.searching')
  if (hasResults.value) return t('ui.search.results_label', { count: flatOptions.value.length })
  if (searched.value) return t('ui.search.no_results', { query: shownQuery.value })

  return ''
})

// --- requests --------------------------------------------------------------

let timer = null

/**
 * Request tokens.
 *
 * `issued` only ever increases; `newest` is the token of the request whose
 * answer the panel is willing to accept. Anything else — a slower response for a
 * query the user has already moved on from, or one in flight when the query
 * dropped below the minimum — is dropped on arrival.
 */
let issued = 0
let newest = 0

function clearTimer() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

function clearResults() {
  results.value = []
  truncated.value = false
  error.value = null
  loading.value = false
  searched.value = false
  shownQuery.value = ''
  activeIndex.value = 0
}

/** Debounced: a keystroke schedules a request, it does not send one. */
function schedule() {
  clearTimer()

  const term = query.value.trim()

  if (term.length < SEARCH_MIN_LENGTH) {
    // Whatever is in flight answers a longer query than the box now holds, so
    // it is invalidated rather than allowed to land under the hint.
    newest = ++issued
    clearResults()

    return
  }

  timer = setTimeout(() => {
    timer = null
    run(term)
  }, props.debounceMs)
}

async function run(term) {
  const token = ++issued

  newest = token
  loading.value = true
  error.value = null

  try {
    const data = await resource.fetch({
      query: term,
      // The server authorises the property; this only says which one is on screen.
      property: property.activeName.value,
      limit: props.limit,
    })

    if (token !== newest) return

    results.value = Array.isArray(data?.results) ? data.results : []
    truncated.value = Boolean(data?.truncated)
    // The echoed query, so the empty state names what was actually asked.
    shownQuery.value = typeof data?.query === 'string' && data.query ? data.query : term
    searched.value = true
    activeIndex.value = 0
  } catch (caught) {
    if (token !== newest) return

    error.value = caught
    results.value = []
    truncated.value = false
    shownQuery.value = term
    searched.value = true
  } finally {
    // A superseded request must not turn the spinner off under the one that
    // replaced it.
    if (token === newest) loading.value = false
  }
}

/**
 * Whether the user dismissed the panel with Escape.
 *
 * Escape returns focus to the input, and focus is also what opens the panel — so
 * without this the panel would reopen the instant it was dismissed. Typing or
 * asking for the list again clears it.
 */
let dismissed = false

function onFocus() {
  if (!dismissed) open.value = true
}

function onInput(event) {
  query.value = event.target.value ?? ''
  dismissed = false
  open.value = true
  schedule()
}

// --- keyboard and focus ----------------------------------------------------

function move(step) {
  const total = flatOptions.value.length

  if (!total) return

  // Wraps, so a user holding ArrowDown never dead-ends at the last row.
  activeIndex.value = (activeIndex.value + step + total) % total
}

function close() {
  clearTimer()
  open.value = false
}

function closeAndRestoreFocus() {
  close()
  input.value?.focus()
}

function openResult(option) {
  if (!option) return

  const target = ROUTE_FOR_TYPE[option.type]?.(option.id)

  if (!target) return

  close()
  router.push(target)
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    dismissed = true
    closeAndRestoreFocus()

    return
  }

  // Tab is left alone deliberately: focus should leave the box the way it would
  // anywhere else. The panel closes behind it rather than floating over the page.
  if (event.key === 'Tab') {
    close()

    return
  }

  if (event.key === 'ArrowDown') {
    event.preventDefault()
    dismissed = false
    open.value = true
    move(1)

    return
  }

  if (event.key === 'ArrowUp') {
    event.preventDefault()
    dismissed = false
    open.value = true
    move(-1)

    return
  }

  if (event.key === 'Enter') {
    if (!activeOption.value) return

    event.preventDefault()
    openResult(activeOption.value)
  }
}

/**
 * A click anywhere else closes the panel.
 *
 * On the document rather than the input's `blur`, because blur fires before the
 * click that caused it: closing on blur would unmount the row under the pointer
 * and the user's click would land on the page behind.
 */
function onDocumentPointerDown(event) {
  if (!open.value) return
  if (root.value?.contains(event.target)) return

  open.value = false
}

onMounted(() => document.addEventListener('pointerdown', onDocumentPointerDown))

onBeforeUnmount(() => {
  clearTimer()
  document.removeEventListener('pointerdown', onDocumentPointerDown)
})

/**
 * Switching property re-asks the question. The rows on screen were scoped to the
 * property that was active when they were fetched, and the server would answer
 * differently now, so they are not left standing under a new property's name.
 */
watch(
  () => property.activeName.value,
  () => {
    if (query.value.trim().length >= SEARCH_MIN_LENGTH) schedule()
    else clearResults()
  },
)
</script>
