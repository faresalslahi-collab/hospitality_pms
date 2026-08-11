<!--
  The one table every operational board renders through (16.7.0 UI kit).

  It knows nothing about hotels. It receives rows, state and column
  descriptions, and it emits intent: which page, which sort, which search,
  which action on which row. The page owns every request, every permission
  decision and every default date — this component never fetches, never sorts,
  never paginates and never filters. What it is given is what it renders, in
  the order it is given, which is what makes a server-sorted board honest.

  Two renderings of the same rows live here on purpose: the semantic table for
  a desk screen, and a card list for a phone in a corridor. A second component
  would drift from the first, and the row actions are exactly the thing that
  must not go missing on the narrow one.

  Direction is never assumed. Every inset, margin and alignment is a logical
  property, so an Arabic session mirrors without a second stylesheet.
-->
<template>
  <div class="space-y-3">
    <div v-if="searchable || $slots.toolbar" class="flex flex-wrap items-end gap-3">
      <div v-if="searchable" class="w-full sm:w-64">
        <FormControl
          type="text"
          size="sm"
          :label="resolvedSearchLabel"
          :placeholder="t('common.search')"
          :model-value="search"
          @update:model-value="onSearch"
        />
      </div>

      <!-- Filter widgets belong to the page: it knows what the values mean. -->
      <slot name="toolbar" :filters="filters" :set-filters="emitFilterChange" />

      <LoadingIndicator v-if="busy" class="size-4 text-ink-gray-5" />
    </div>

    <slot v-if="error" name="error" :error="error" :details="errorDetails">
      <!-- A permission failure is not a fault the user can retry out of. -->
      <PermissionDenied v-if="errorDetails.kind === 'permission'" :message="errorDetails.message" />
      <ErrorState v-else :error="error" />
    </slot>

    <slot v-else-if="loading && !hasRows" name="loading">
      <LoadingState />
    </slot>

    <slot v-else-if="!hasRows" name="empty">
      <EmptyState :message="emptyMessage" />
    </slot>

    <!--
      Rows already on screen are never blanked by a refetch. The board stays
      readable and announces itself busy instead, because a front desk reading
      a name mid-sentence should not lose it to a poll.
    -->
    <div v-else :aria-busy="busy ? 'true' : 'false'">
      <div
        class="hidden overflow-x-auto rounded border border-outline-gray-1 md:block"
        :class="busy ? 'opacity-60' : ''"
      >
        <table class="w-full min-w-max text-p-sm" :aria-label="ariaLabel || undefined">
          <thead
            class="bg-surface-gray-1 text-xs uppercase tracking-wide text-ink-gray-5"
            :class="stickyHeader ? 'sticky top-0 z-10' : ''"
          >
            <tr>
              <th
                v-for="column in columns"
                :key="column.key"
                scope="col"
                :class="[cellPadding, alignClass(column), hideBelowClass(column)]"
                :aria-sort="ariaSort(column)"
              >
                <button
                  v-if="column.sortable"
                  type="button"
                  class="inline-flex items-center gap-1 uppercase tracking-wide hover:text-ink-gray-7"
                  :aria-label="sortActionLabel(column)"
                  @click="toggleSort(column)"
                >
                  <span>{{ column.label }}</span>
                  <FeatherIcon :name="sortIcon(column)" class="size-3" aria-hidden="true" />
                  <span v-if="isSorted(column)" class="sr-only">{{ sortedStateLabel }}</span>
                </button>
                <span v-else>{{ column.label }}</span>
              </th>
              <th v-if="hasActions" scope="col" :class="[cellPadding, 'text-end']">
                {{ t('common.actions') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, index) in rows"
              :key="keyFor(row, index)"
              class="border-t border-outline-gray-1"
              :class="clickableRows ? 'cursor-pointer hover:bg-surface-gray-1' : ''"
              :tabindex="clickableRows ? 0 : undefined"
              @click="onRowClick(row)"
              @keydown.enter.self="onRowClick(row)"
              @keydown.space.self.prevent="onRowClick(row)"
            >
              <td
                v-for="column in columns"
                :key="column.key"
                :class="[cellPadding, alignClass(column), hideBelowClass(column), nowrapClass(column)]"
              >
                <slot :name="`cell:${column.key}`" :row="row" :column="column" :value="valueOf(row, column)">
                  <MoneyDisplay
                    v-if="column.type === 'money'"
                    :value="valueOf(row, column)"
                    :currency="currencyOf(row, column)"
                    :precision="precisionOf(column)"
                  />
                  <Badge
                    v-else-if="column.type === 'badge' && hasValue(row, column)"
                    variant="subtle"
                    :theme="badgeTheme(row, column)"
                    :label="String(valueOf(row, column))"
                  />
                  <span v-else>{{ display(row, column) }}</span>
                </slot>
              </td>
              <td v-if="hasActions" :class="[cellPadding, 'text-end']" @click.stop>
                <div
                  class="flex items-center justify-end gap-2"
                  role="group"
                  :aria-label="t('ui.table.row_actions', { row: rowLabel(row, index) })"
                >
                  <slot name="actions" :row="row">
                    <Button
                      v-for="action in actionsFor(row)"
                      :key="action.key"
                      size="sm"
                      :theme="action.theme || 'gray'"
                      :variant="action.variant || 'subtle'"
                      :label="action.label"
                      :icon-left="action.icon || undefined"
                      :disabled="isDisabled(action, row)"
                      @click="emitRowAction(action, row)"
                    />
                  </slot>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!--
        Narrow rendering. Same rows, same order, same actions — a card instead
        of a scroll, because a horizontally scrolled table on a phone hides the
        action column, which is the only part of the board that does anything.
      -->
      <ul
        class="space-y-2 md:hidden"
        :class="busy ? 'opacity-60' : ''"
        role="list"
        :aria-label="ariaLabel || undefined"
      >
        <li
          v-for="(row, index) in rows"
          :key="keyFor(row, index)"
          class="rounded border border-outline-gray-1 p-3"
        >
          <div class="min-w-0">
            <button
              v-if="clickableRows"
              type="button"
              class="text-start text-p-sm font-medium text-ink-gray-9"
              @click="onRowClick(row)"
            >
              {{ rowLabel(row, index) }}
            </button>
            <p v-else class="text-start text-p-sm font-medium text-ink-gray-9">
              {{ rowLabel(row, index) }}
            </p>
            <p v-if="secondaryColumn" class="text-start text-p-sm text-ink-gray-6">
              {{ display(row, secondaryColumn) }}
            </p>
          </div>

          <dl class="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
            <div v-for="column in cardColumns" :key="column.key" class="min-w-0">
              <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ column.label }}</dt>
              <dd class="text-start text-p-sm text-ink-gray-8">
                <slot :name="`cell:${column.key}`" :row="row" :column="column" :value="valueOf(row, column)">
                  <MoneyDisplay
                    v-if="column.type === 'money'"
                    :value="valueOf(row, column)"
                    :currency="currencyOf(row, column)"
                    :precision="precisionOf(column)"
                  />
                  <Badge
                    v-else-if="column.type === 'badge' && hasValue(row, column)"
                    variant="subtle"
                    :theme="badgeTheme(row, column)"
                    :label="String(valueOf(row, column))"
                  />
                  <span v-else>{{ display(row, column) }}</span>
                </slot>
              </dd>
            </div>
          </dl>

          <div
            v-if="hasActions"
            class="mt-3 flex flex-wrap items-center gap-2"
            role="group"
            :aria-label="t('ui.table.row_actions', { row: rowLabel(row, index) })"
          >
            <slot name="actions" :row="row">
              <Button
                v-for="action in actionsFor(row)"
                :key="action.key"
                size="sm"
                :theme="action.theme || 'gray'"
                :variant="action.variant || 'subtle'"
                :label="action.label"
                :icon-left="action.icon || undefined"
                :disabled="isDisabled(action, row)"
                @click="emitRowAction(action, row)"
              />
            </slot>
          </div>
        </li>
      </ul>

      <div
        v-if="paginated"
        class="flex flex-wrap items-center justify-between gap-2 pt-3 text-p-sm text-ink-gray-6"
      >
        <div class="space-y-0.5">
          <p>{{ statusText }}</p>
          <p v-if="rangeText">{{ rangeText }}</p>
        </div>

        <!--
          `label` is what a screen reader hears ("Previous page"); the slot is
          what the eye reads ("Previous"). frappe-ui's Button maps `label` onto
          aria-label, so the two stay in one place instead of drifting apart.
        -->
        <div class="flex items-center gap-2">
          <Button
            size="sm"
            variant="subtle"
            :disabled="!canPrevious"
            :label="t('ui.table.previous_page')"
            @click="goTo(page - 1)"
          >
            {{ t('common.previous') }}
          </Button>
          <Button
            size="sm"
            variant="subtle"
            :disabled="!canNext"
            :label="t('ui.table.next_page')"
            @click="goTo(page + 1)"
          >
            {{ t('common.next') }}
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Badge, Button, FeatherIcon, FormControl, LoadingIndicator } from 'frappe-ui'
import { computed, watch } from 'vue'

import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import PermissionDenied from '@/components/states/PermissionDenied.vue'
import { normaliseError } from '@/utils/errors'
import { formatDate, formatNumber } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** Column descriptions, already translated by the page. */
  columns: { type: Array, required: true },
  /** Rendered exactly as given. Never sorted, sliced or filtered here. */
  rows: { type: Array, required: true },
  rowKey: { type: String, default: 'name' },
  loading: { type: Boolean, default: false },
  /** Raw error; normalised here so every board reports failure identically. */
  error: { type: [Object, String], default: null },
  emptyMessage: { type: String, default: undefined },

  // Server-side page state. The page fetches; this only reports intent.
  page: { type: Number, default: 1 },
  pageLength: { type: Number, default: 0 },
  total: { type: Number, default: null },

  // Server-side sort state.
  sortBy: { type: String, default: '' },
  sortOrder: { type: String, default: 'asc' },

  searchable: { type: Boolean, default: false },
  search: { type: String, default: '' },
  searchLabel: { type: String, default: '' },

  /**
   * Opaque filter values owned by the page. This component never reads or
   * interprets them; it only carries them back out when the toolbar changes.
   */
  filters: { type: Object, default: () => ({}) },

  actions: { type: Array, default: () => [] },

  dense: { type: Boolean, default: false },
  stickyHeader: { type: Boolean, default: false },
  ariaLabel: { type: String, default: '' },
  clickableRows: { type: Boolean, default: false },
})

const emit = defineEmits([
  'page-change',
  'sort-change',
  'filter-change',
  'search-change',
  'row-action',
  'row-click',
])

/** Logical alignment only; `left`/`right` would break the Arabic session. */
const ALIGN_CLASS = {
  start: 'text-start',
  end: 'text-end',
  center: 'text-center',
}

/**
 * Breakpoint classes as literal strings so Tailwind's scanner can see them.
 * Only the desktop table hides columns: the card list has room for all of them.
 */
const HIDE_BELOW_CLASS = {
  sm: 'hidden sm:table-cell',
  md: 'hidden md:table-cell',
  lg: 'hidden lg:table-cell',
  xl: 'hidden xl:table-cell',
  '2xl': 'hidden 2xl:table-cell',
}

const NUMERIC_TYPES = new Set(['money', 'number'])

const hasRows = computed(() => props.rows.length > 0)
const busy = computed(() => props.loading && hasRows.value)
const errorDetails = computed(() => normaliseError(props.error))
const cellPadding = computed(() => (props.dense ? 'px-2 py-1' : 'p-2'))
const resolvedSearchLabel = computed(() => props.searchLabel || t('ui.table.search_label'))

const hasActions = computed(() => props.actions.length > 0)

const primaryColumn = computed(() => props.columns.find((column) => column.primary) || props.columns[0])
const secondaryColumn = computed(() => props.columns.find((column) => column.secondary) || null)

/** Everything the card heading does not already say. */
const cardColumns = computed(() =>
  props.columns.filter((column) => column !== primaryColumn.value && column !== secondaryColumn.value),
)

// --- cells -----------------------------------------------------------------

function valueOf(row, column) {
  return row?.[column.field || column.key]
}

function hasValue(row, column) {
  const value = valueOf(row, column)

  return value !== null && value !== undefined && value !== ''
}

function precisionOf(column) {
  if (typeof column.precision === 'number') return column.precision

  return column.type === 'number' ? 0 : 2
}

/**
 * The currency always travels with the amount. This component holds no
 * default: an amount whose row carries no currency is shown as a plain number
 * rather than being labelled with a currency nobody sent.
 */
function currencyOf(row, column) {
  return row?.[column.currencyField || 'currency'] ?? null
}

/** Presentation only, supplied by the page: a string, or a function of the row. */
function badgeTheme(row, column) {
  const theme = typeof column.theme === 'function' ? column.theme(row, valueOf(row, column)) : column.theme

  return theme || 'gray'
}

/** Text for the cell types this component renders itself. */
function display(row, column) {
  if (!column) return ''
  if (!hasValue(row, column)) return '—'

  const value = valueOf(row, column)

  if (column.type === 'date') return formatDate(value)
  if (column.type === 'number') return formatNumber(value, precisionOf(column))

  return String(value)
}

function alignClass(column) {
  const align = column.align || (NUMERIC_TYPES.has(column.type) ? 'end' : 'start')

  return ALIGN_CLASS[align] || ALIGN_CLASS.start
}

function hideBelowClass(column) {
  return (column.hideBelow && HIDE_BELOW_CLASS[column.hideBelow]) || ''
}

function nowrapClass(column) {
  return column.nowrap ? 'whitespace-nowrap' : ''
}

function keyFor(row, index) {
  return row?.[props.rowKey] ?? index
}

/** What a screen reader hears for the row: its own heading, not "row 4". */
function rowLabel(row, index) {
  const label = primaryColumn.value ? display(row, primaryColumn.value) : ''

  return label && label !== '—' ? label : String(keyFor(row, index))
}

// --- sorting ---------------------------------------------------------------

/** The field the server sorts on, which is not always the column key. */
function sortKeyOf(column) {
  return column.field || column.key
}

function isSorted(column) {
  return Boolean(props.sortBy) && props.sortBy === sortKeyOf(column)
}

const sortedStateLabel = computed(() =>
  props.sortOrder === 'desc' ? t('ui.table.sorted_descending') : t('ui.table.sorted_ascending'),
)

function ariaSort(column) {
  if (!column.sortable) return undefined
  if (!isSorted(column)) return 'none'

  return props.sortOrder === 'desc' ? 'descending' : 'ascending'
}

/** Describes what the click will do, not what is already true. */
function sortActionLabel(column) {
  const next = isSorted(column) && props.sortOrder === 'asc' ? 'descending' : 'ascending'

  return next === 'descending'
    ? t('ui.table.sort_descending', { column: column.label })
    : t('ui.table.sort_ascending', { column: column.label })
}

function sortIcon(column) {
  if (!isSorted(column)) return 'minus'

  return props.sortOrder === 'desc' ? 'chevron-down' : 'chevron-up'
}

/** Emits intent. The rows on screen do not move until the page sends new ones. */
function toggleSort(column) {
  const sortBy = sortKeyOf(column)
  const sortOrder = isSorted(column) && props.sortOrder === 'asc' ? 'desc' : 'asc'

  emit('sort-change', { sortBy, sortOrder })
}

// --- pagination ------------------------------------------------------------

const paginated = computed(() => props.pageLength > 0)

const pages = computed(() => {
  if (!paginated.value || props.total === null || props.total === undefined) return null

  return Math.max(1, Math.ceil(props.total / props.pageLength))
})

const firstIndex = computed(() => (props.page - 1) * props.pageLength + 1)
const lastIndex = computed(() => firstIndex.value + props.rows.length - 1)

const canPrevious = computed(() => props.page > 1)

/**
 * With a known total, the last row of the last page ends the board. Without
 * one, a short page is the only evidence there is nothing more to ask for.
 */
const canNext = computed(() => {
  if (!paginated.value) return false
  if (pages.value !== null) return props.page < pages.value

  return props.rows.length >= props.pageLength
})

const statusText = computed(() =>
  pages.value !== null
    ? t('ui.table.page_status', { page: props.page, pages: pages.value })
    : t('ui.table.row_count', { count: props.rows.length }),
)

const rangeText = computed(() => {
  if (pages.value === null) return ''

  return t('common.showing_of', { shown: `${firstIndex.value}–${lastIndex.value}`, total: props.total })
})

function goTo(next) {
  if (next < 1) return
  if (pages.value !== null && next > pages.value) return

  emit('page-change', next)
}

// --- actions, search, filters ---------------------------------------------

/** Presentation-level visibility only; the server still authorises the action. */
function actionsFor(row) {
  return props.actions.filter((action) => (typeof action.available === 'function' ? action.available(row) : true))
}

function isDisabled(action, row) {
  return typeof action.disabled === 'function' ? Boolean(action.disabled(row)) : Boolean(action.disabled)
}

function emitRowAction(action, row) {
  if (isDisabled(action, row)) return

  emit('row-action', { action: action.key, row })
}

function onRowClick(row) {
  if (!props.clickableRows) return

  emit('row-click', row)
}

/**
 * One keystroke, one intent.
 *
 * frappe-ui's text input reports both `input` and `change`, which would send
 * the same term to the server twice. The last term emitted is remembered so a
 * repeat is dropped, and it re-syncs whenever the page pushes a new term in
 * (clearing a filter, restoring a saved view) so the next keystroke still
 * reaches the page.
 */
let lastSearch = props.search

watch(
  () => props.search,
  (value) => {
    lastSearch = value ?? ''
  },
)

function onSearch(value) {
  const next = value ?? ''

  if (next === lastSearch) return

  lastSearch = next
  emit('search-change', next)
}

/**
 * Carries a toolbar change back to the page, merged onto the filters it gave
 * us. The values stay opaque: this component never asks what they mean.
 */
function emitFilterChange(patch) {
  emit('filter-change', { ...props.filters, ...(patch || {}) })
}

defineExpose({ emitFilterChange })
</script>
