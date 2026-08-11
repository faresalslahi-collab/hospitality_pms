/**
 * OperationalDataTable — the contract every board depends on.
 *
 * The assertions are deliberately about *intent*, not internals: the table is
 * given rows and state and must emit what the user asked for. The two tests
 * that matter most operationally are the last two — that the component renders
 * the rows in the order the server sent them (a board that re-sorts client side
 * lies about a paginated result), and that the narrow rendering still exposes
 * the row actions (a phone in a corridor is a real front-desk device).
 */
import { describe, expect, it } from 'vitest'
import { h } from 'vue'

import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import { t } from '@/utils/i18n'

import { mountOperational, setDirection, useArabic } from '../helpers'

/**
 * Neutral columns on purpose. This component must carry no hotel vocabulary,
 * so the fixture does not give it any to lean on.
 */
const COLUMNS = [
  { key: 'code', label: 'Code', sortable: true, primary: true, nowrap: true },
  { key: 'party', label: 'Party', secondary: true },
  { key: 'day', label: 'Day', type: 'date' },
  { key: 'balance', label: 'Balance', type: 'money', currencyField: 'currency' },
  { key: 'count', label: 'Count', type: 'number' },
  { key: 'state', label: 'State', type: 'badge', sortable: true },
  { key: 'note', label: 'Note', type: 'custom', hideBelow: 'lg' },
]

/** Given out of order on purpose: the server decided this order, not us. */
const ROWS = [
  {
    name: 'R-3',
    code: 'R-3',
    party: 'Third party',
    day: '2026-08-08',
    balance: 120.5,
    currency: 'QAR',
    count: 3,
    state: 'Open',
    note: 'third note',
  },
  {
    name: 'R-1',
    code: 'R-1',
    party: 'First party',
    day: '2026-08-09',
    balance: 0,
    currency: 'QAR',
    count: 1,
    state: 'Closed',
    note: 'first note',
  },
  {
    name: 'R-2',
    code: 'R-2',
    party: 'Second party',
    day: '2026-08-10',
    balance: null,
    currency: 'QAR',
    count: 2,
    state: 'Open',
    note: 'second note',
  },
]

const ACTIONS = [
  { key: 'open', label: 'Open record', icon: 'external-link' },
  { key: 'settle', label: 'Settle', available: (row) => row.state === 'Open' },
  { key: 'void', label: 'Void', disabled: () => true },
]

function mountTable(props = {}, options = {}) {
  return mountOperational(OperationalDataTable, {
    props: { columns: COLUMNS, rows: ROWS, ...props },
    ...options,
  })
}

/** The desktop table only; the card list repeats every value by design. */
function bodyRows(wrapper) {
  return wrapper.findAll('tbody tr')
}

function firstCellText(wrapper) {
  return bodyRows(wrapper).map((row) => row.findAll('td')[0].text())
}

describe('OperationalDataTable', () => {
  it('renders a semantic header and one row per record', async () => {
    const wrapper = await mountTable()

    const headers = wrapper.findAll('thead th')
    expect(headers).toHaveLength(COLUMNS.length)
    expect(headers.map((th) => th.text())).toEqual(COLUMNS.map((column) => column.label))
    expect(headers.every((th) => th.attributes('scope') === 'col')).toBe(true)

    expect(bodyRows(wrapper)).toHaveLength(ROWS.length)
    expect(wrapper.find('table').attributes('aria-label')).toBeUndefined()

    // Money, date and number cells are formatted, never raw.
    const cells = bodyRows(wrapper)[0].findAll('td')
    expect(cells[2].text()).toBe('08 Aug 2026')
    expect(cells[3].text()).toContain('120.50')
    expect(cells[5].text()).toBe('Open')
  })

  it('adds an actions column only when actions are supplied', async () => {
    const wrapper = await mountTable({ actions: ACTIONS, ariaLabel: 'Records' })

    const headers = wrapper.findAll('thead th')
    expect(headers).toHaveLength(COLUMNS.length + 1)
    expect(headers.at(-1).text()).toBe(t('common.actions'))
    expect(wrapper.find('table').attributes('aria-label')).toBe('Records')
  })

  it('shows the shared loading state while there are no rows', async () => {
    const wrapper = await mountTable({ rows: [], loading: true })

    expect(wrapper.text()).toContain(t('state.loading_title'))
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('keeps existing rows visible and marks the region busy while refetching', async () => {
    const wrapper = await mountTable({ loading: true })

    expect(bodyRows(wrapper)).toHaveLength(ROWS.length)
    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(true)
  })

  it('shows the shared empty state, with an optional page message', async () => {
    const wrapper = await mountTable({ rows: [] })
    expect(wrapper.text()).toContain(t('state.empty_title'))
    expect(wrapper.text()).toContain(t('state.empty_message'))
    expect(wrapper.find('table').exists()).toBe(false)

    const custom = await mountTable({ rows: [], emptyMessage: 'Nothing for this day' })
    expect(custom.text()).toContain('Nothing for this day')
  })

  it('shows the shared error state, and never offers retry for a permission failure', async () => {
    const server = await mountTable({ rows: [], error: { status: 500, message: 'Boom' } })
    expect(server.text()).toContain(t('state.error_title'))
    expect(server.text()).toContain('Boom')
    expect(server.find('table').exists()).toBe(false)

    const denied = await mountTable({
      rows: [],
      error: { status: 403, message: 'Not allowed for this property' },
    })
    expect(denied.text()).toContain(t('state.denied_title'))
    expect(denied.text()).not.toContain(t('common.retry'))
  })

  it('emits page-change from the pagination controls and disables the ends', async () => {
    const wrapper = await mountTable({ page: 2, pageLength: 3, total: 9 })

    expect(wrapper.text()).toContain(t('ui.table.page_status', { page: 2, pages: 3 }))
    expect(wrapper.text()).toContain(t('common.showing_of', { shown: '4–6', total: 9 }))

    await wrapper.find(`[aria-label="${t('ui.table.previous_page')}"]`).trigger('click')
    await wrapper.find(`[aria-label="${t('ui.table.next_page')}"]`).trigger('click')

    expect(wrapper.emitted('page-change')).toEqual([[1], [3]])

    const first = await mountTable({ page: 1, pageLength: 3, total: 9 })
    expect(first.find(`[aria-label="${t('ui.table.previous_page')}"]`).attributes('disabled')).toBeDefined()

    const last = await mountTable({ page: 3, pageLength: 3, total: 9 })
    expect(last.find(`[aria-label="${t('ui.table.next_page')}"]`).attributes('disabled')).toBeDefined()

    const unpaged = await mountTable()
    expect(unpaged.find(`[aria-label="${t('ui.table.next_page')}"]`).exists()).toBe(false)
  })

  it('emits sort-change ascending, then flips the order on the sorted column', async () => {
    const wrapper = await mountTable()

    const header = wrapper.findAll('thead th')[0]
    expect(header.attributes('aria-sort')).toBe('none')

    await header.find('button').trigger('click')
    expect(wrapper.emitted('sort-change')).toEqual([[{ sortBy: 'code', sortOrder: 'asc' }]])

    // The page hands the new sort state back; only then does the order flip.
    const sorted = await mountTable({ sortBy: 'code', sortOrder: 'asc' })
    const sortedHeader = sorted.findAll('thead th')[0]
    expect(sortedHeader.attributes('aria-sort')).toBe('ascending')
    expect(sortedHeader.text()).toContain(t('ui.table.sorted_ascending'))

    await sortedHeader.find('button').trigger('click')
    expect(sorted.emitted('sort-change')).toEqual([[{ sortBy: 'code', sortOrder: 'desc' }]])

    // A different column always starts ascending.
    const other = sorted.findAll('thead th')[5]
    expect(other.attributes('aria-sort')).toBe('none')
    await other.find('button').trigger('click')
    expect(sorted.emitted('sort-change')).toEqual([
      [{ sortBy: 'code', sortOrder: 'desc' }],
      [{ sortBy: 'state', sortOrder: 'asc' }],
    ])

    // Non-sortable headers carry no control and no aria-sort.
    const plain = wrapper.findAll('thead th')[1]
    expect(plain.find('button').exists()).toBe(false)
    expect(plain.attributes('aria-sort')).toBeUndefined()
  })

  it('emits search-change from the search control', async () => {
    const wrapper = await mountTable({ searchable: true })

    const input = wrapper.find('input')
    expect(wrapper.text()).toContain(t('ui.table.search_label'))

    // Exactly once, though the underlying control reports input *and* change:
    // a duplicated term would send the page fetching twice for one keystroke.
    await input.setValue('mansour')
    expect(wrapper.emitted('search-change')).toEqual([['mansour']])

    await input.setValue('')
    expect(wrapper.emitted('search-change')).toEqual([['mansour'], ['']])
  })

  it('emits filter-change from the toolbar helper, without interpreting the values', async () => {
    const wrapper = await mountTable(
      { filters: { state: 'all', desk: 'front' } },
      {
        slots: {
          toolbar: (scope) =>
            h(
              'button',
              { type: 'button', 'data-test': 'toolbar-filter', onClick: () => scope.setFilters({ state: 'open' }) },
              'filter',
            ),
        },
      },
    )

    await wrapper.find('[data-test="toolbar-filter"]').trigger('click')
    expect(wrapper.emitted('filter-change')).toEqual([[{ state: 'open', desk: 'front' }]])

    // The same helper is exposed for pages that own their own toolbar layout.
    wrapper.vm.emitFilterChange({ desk: 'night' })
    expect(wrapper.emitted('filter-change').at(-1)).toEqual([{ state: 'all', desk: 'night' }])
  })

  it('emits row-action with the action key and the untouched row', async () => {
    const wrapper = await mountTable({ actions: ACTIONS })

    const row = bodyRows(wrapper)[0]
    await row.find('[aria-label="Open record"]').trigger('click')

    expect(wrapper.emitted('row-action')).toEqual([[{ action: 'open', row: ROWS[0] }]])

    // `available` is presentation only: the closed row simply has no Settle.
    expect(row.find('[aria-label="Settle"]').exists()).toBe(true)
    expect(bodyRows(wrapper)[1].find('[aria-label="Settle"]').exists()).toBe(false)

    // A disabled action is focusable but emits nothing.
    const voidButton = row.find('[aria-label="Void"]')
    expect(voidButton.attributes('disabled')).toBeDefined()

    // The action group is labelled by the row it belongs to.
    expect(row.find('[role="group"]').attributes('aria-label')).toBe(
      t('ui.table.row_actions', { row: 'R-3' }),
    )
  })

  it('emits row-click only when the rows are clickable', async () => {
    const inert = await mountTable()
    await bodyRows(inert)[0].trigger('click')
    expect(inert.emitted('row-click')).toBeUndefined()

    const clickable = await mountTable({ clickableRows: true })
    await bodyRows(clickable)[1].trigger('click')
    expect(clickable.emitted('row-click')).toEqual([[ROWS[1]]])

    // Keyboard parity: a clickable row is reachable and operable without a mouse.
    const target = bodyRows(clickable)[0]
    expect(target.attributes('tabindex')).toBe('0')
    await target.trigger('keydown', { key: 'Enter' })
    expect(clickable.emitted('row-click')).toEqual([[ROWS[1]], [ROWS[0]]])
  })

  it('renders a custom cell slot in both renderings', async () => {
    const wrapper = await mountTable(
      {},
      {
        slots: {
          'cell:note': (scope) => h('span', { class: 'custom-note' }, `note:${scope.value}`),
        },
      },
    )

    const rendered = wrapper.findAll('.custom-note')
    // Once in the table, once in the card list, for every row.
    expect(rendered).toHaveLength(ROWS.length * 2)
    expect(rendered[0].text()).toBe('note:third note')
  })

  it('uses logical properties only, and still renders money and actions in RTL', async () => {
    useArabic()
    setDirection('rtl')

    const wrapper = await mountTable({ actions: ACTIONS, searchable: true, page: 1, pageLength: 3, total: 9 })
    const html = wrapper.html()

    for (const physical of [/text-left/, /text-right/, /\bml-/, /\bmr-/, /\bpl-/, /\bpr-/, /\bleft-/, /\bright-/]) {
      expect(html, `rendered markup must not use ${physical}`).not.toMatch(physical)
    }

    expect(html).toContain('text-start')
    expect(html).toContain('text-end')

    // Arabic labels arrive from the catalogue, not from a hard-coded literal.
    expect(wrapper.text()).toContain(t('common.actions'))
    expect(wrapper.find(`[aria-label="${t('ui.table.next_page')}"]`).exists()).toBe(true)

    // Money still formats (Arabic digits and currency placement come from Intl).
    const money = bodyRows(wrapper)[0].findAll('td')[3]
    expect(money.text()).not.toBe('')
    expect(money.text()).not.toBe('—')

    expect(bodyRows(wrapper)[0].find('[aria-label="Open record"]').exists()).toBe(true)
  })

  it('renders a narrow card list that keeps the row actions reachable', async () => {
    const wrapper = await mountTable({ actions: ACTIONS })

    // One component, two renderings, chosen by breakpoint rather than by JS.
    const table = wrapper.find('div.md\\:block')
    expect(table.classes()).toContain('hidden')
    expect(table.find('table').exists()).toBe(true)

    const cards = wrapper.find('ul.md\\:hidden')
    expect(cards.exists()).toBe(true)

    const items = cards.findAll('li')
    expect(items).toHaveLength(ROWS.length)

    // Primary and secondary columns become the card heading.
    expect(items[0].text()).toContain('R-3')
    expect(items[0].text()).toContain('Third party')

    // Remaining columns are label/value pairs, not a squashed table.
    expect(items[0].findAll('dt').map((dt) => dt.text())).toEqual(['Day', 'Balance', 'Count', 'State', 'Note'])

    // The actions are the point: they must survive the narrow rendering.
    const group = items[0].find('[role="group"]')
    expect(group.attributes('aria-label')).toBe(t('ui.table.row_actions', { row: 'R-3' }))
    await group.find('[aria-label="Open record"]').trigger('click')
    expect(wrapper.emitted('row-action')).toEqual([[{ action: 'open', row: ROWS[0] }]])
  })

  it('renders exactly the rows it was given, in the order it was given', async () => {
    const wrapper = await mountTable({ sortBy: 'code', sortOrder: 'asc', page: 1, pageLength: 2, total: 9 })

    // Sorted-ascending state is claimed, and the component still does not reorder.
    expect(firstCellText(wrapper)).toEqual(['R-3', 'R-1', 'R-2'])
    expect(bodyRows(wrapper)).toHaveLength(ROWS.length)

    // Nor does it slice to pageLength, nor mutate the array it was handed.
    expect(ROWS.map((row) => row.code)).toEqual(['R-3', 'R-1', 'R-2'])

    const searched = await mountTable({ searchable: true, search: 'R-1' })
    expect(firstCellText(searched)).toEqual(['R-3', 'R-1', 'R-2'])
  })
})
