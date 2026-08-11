/**
 * Departures board regression, after the migration onto OperationalDataTable.
 *
 * The rule this file exists to defend: the checkout verdict belongs to the
 * server. A blocked stay keeps its Check out action, its blockers are rendered as
 * the server worded them, and nothing on the page derives readiness from a
 * balance.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { flush, mountOperational, resetStores, stubProperty, stubSession, testRouter } from '../helpers'

const { board } = vi.hoisted(() => ({
  board: { data: null, loading: false, error: null, fetch: vi.fn() },
}))

vi.mock('@/resources/frontOffice', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, departuresBoardResource: () => board }
})

const { default: Departures } = await import('@/pages/Departures.vue')

/** One departures row, shaped as `services.front_office` sends it. */
function row(overrides = {}) {
  return {
    key: 'HPMS-STAY-2026-00001',
    stay: 'HPMS-STAY-2026-00001',
    stay_status: 'Due Out',
    reservation: 'HPMS-RES-2026-00001',
    guest: 'HPMS-GUEST-0001',
    guest_name: 'Layla Haddad',
    vip_status: '',
    room: 'DOHA01-101',
    room_number: '101',
    room_type: 'DLX',
    room_type_name: 'Deluxe',
    housekeeping_status: 'Occupied Dirty',
    arrival_date: '2026-08-06',
    departure_date: '2026-08-08',
    nights: 2,
    adults: 2,
    children: 0,
    folio: 'HPMS-FOL-2026-00001',
    folio_status: 'Open',
    balance: 0,
    related_folios: 0,
    related_balance: 0,
    currency: 'QAR',
    checked_out_on: '',
    is_checked_out: false,
    blockers: [],
    can_check_out: true,
    ...overrides,
  }
}

function boardData(rows, summary = {}) {
  return {
    property: 'DOHA01',
    business_date: '2026-08-08',
    currency: 'QAR',
    rows,
    summary: { total: rows.length, due_out: rows.length, outstanding_balance: 0, ...summary },
  }
}

function buttonsWithText(wrapper, text) {
  return wrapper.findAll('button').filter((button) => button.text().trim() === text)
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Agent'])
  board.data = null
  board.loading = false
  board.error = null
  board.fetch.mockClear()
})

describe('Departures board', () => {
  it('renders the day it was given', async () => {
    board.data = boardData([row(), row({ key: 'S2', stay: 'S2', guest_name: 'Omar Nasser', room_number: '102' })])

    const wrapper = await mountOperational(Departures)

    expect(wrapper.text()).toContain('Layla Haddad')
    expect(wrapper.text()).toContain('Omar Nasser')
    expect(wrapper.text()).toContain('101')
    expect(wrapper.text()).toContain('Due Out')
  })

  it('links a room to its stay and a folio to its folio', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Departures)
    const hrefs = wrapper.findAll('a').map((a) => a.attributes('href'))

    expect(hrefs).toContain('/stays/HPMS-STAY-2026-00001')
    expect(hrefs).toContain('/folios/HPMS-FOL-2026-00001')
  })

  it('reports loading, empty and failure the way every board does', async () => {
    board.loading = true
    let wrapper = await mountOperational(Departures)
    expect(wrapper.text()).toContain('Loading')

    board.loading = false
    board.data = boardData([])
    wrapper = await mountOperational(Departures)
    expect(wrapper.text()).toContain('No departures for this date.')

    board.data = null
    board.error = { status: 500 }
    wrapper = await mountOperational(Departures)
    expect(wrapper.text()).toContain('Something went wrong')
  })

  it('fetches on the property alone — never a client-supplied date', async () => {
    board.data = boardData([row()])

    await mountOperational(Departures)

    expect(board.fetch).toHaveBeenCalledWith({ property: 'DOHA01' })
    for (const [params] of board.fetch.mock.calls) {
      expect(Object.keys(params)).toEqual(['property'])
    }
  })

  it('refetches when the active property changes', async () => {
    board.data = boardData([row()])

    await mountOperational(Departures)
    board.fetch.mockClear()

    stubProperty({ name: 'DOHA02' })
    await flush()

    expect(board.fetch).toHaveBeenCalledWith({ property: 'DOHA02' })
  })
})

describe('Departures checkout verdict', () => {
  it('reads a clean exit from the server, not from the balance', async () => {
    board.data = boardData([row({ can_check_out: true, balance: 0 })])

    const wrapper = await mountOperational(Departures)

    expect(wrapper.text()).toContain('Ready to check out')
  })

  it('renders the server blockers verbatim on a blocked stay', async () => {
    const blocker = 'Folio HPMS-FOL-2026-00001 has an outstanding balance of QAR 420.00.'
    board.data = boardData([row({ can_check_out: false, blockers: [blocker], balance: 420 })])

    const wrapper = await mountOperational(Departures)

    expect(wrapper.text()).toContain('Blocked')
    expect(wrapper.text()).toContain(blocker)
  })

  it('keeps the checkout action available on a blocked stay, and does not disable it', async () => {
    board.data = boardData([row({ can_check_out: false, blockers: ['Folio has an outstanding balance.'] })])

    const wrapper = await mountOperational(Departures)
    const checkout = buttonsWithText(wrapper, 'Check out')

    // The blocked rows are exactly the ones a supervisor must be able to open:
    // the checkout screen is where the blocker gets resolved.
    expect(checkout.length).toBeGreaterThan(0)
    expect(checkout[0].attributes('disabled')).toBeUndefined()
  })

  it('never claims a settled balance means the guest may leave', async () => {
    board.data = boardData([row({ balance: 0, can_check_out: false, blockers: ['Stay is not due out.'] })])

    const wrapper = await mountOperational(Departures)

    // Scoped to the rows: "Ready to check out" is also a summary-tile label, and
    // the tile counts what the server said, which is a different statement.
    const body = wrapper.find('tbody').text()

    expect(body).toContain('Blocked')
    expect(body).toContain('Stay is not due out.')
    expect(body).not.toContain('Ready to check out')
  })

  it('withholds the checkout action from a stay that has already left', async () => {
    board.data = boardData([row({ is_checked_out: true, stay_status: 'Checked Out' })])

    const wrapper = await mountOperational(Departures)

    expect(buttonsWithText(wrapper, 'Check out')).toHaveLength(0)
    expect(wrapper.text()).toContain('Checked out')
  })
})

describe('Departures balance presentation', () => {
  it('shows a settled folio as an amount, not as a permission to depart', async () => {
    board.data = boardData([row({ balance: 0 })])

    const wrapper = await mountOperational(Departures)

    expect(wrapper.text()).toMatch(/0\.00/)
  })

  it('shows an amount owed', async () => {
    board.data = boardData([row({ balance: 420.5 })])

    const wrapper = await mountOperational(Departures)

    expect(wrapper.text()).toMatch(/420\.50/)
  })

  it('counts split folios rather than summing them into the balance', async () => {
    board.data = boardData([row({ balance: 100, related_folios: 2, related_balance: 300 })])

    const wrapper = await mountOperational(Departures)

    expect(wrapper.text()).toContain('2 split folio(s)')
    // 400 would be the merged figure; the two settle separately.
    expect(wrapper.text()).not.toMatch(/400\.00/)
  })
})

describe('Departures row actions', () => {
  it('navigates to checkout', async () => {
    board.data = boardData([row()])
    const router = testRouter()

    const wrapper = await mountOperational(Departures, { router })
    await buttonsWithText(wrapper, 'Check out')[0].trigger('click')
    await flush(wrapper)

    expect(router.currentRoute.value.name).toBe('Checkout')
    expect(router.currentRoute.value.params.stay).toBe('HPMS-STAY-2026-00001')
  })

  it('withholds the folio action from a stay with no folio', async () => {
    board.data = boardData([row({ folio: null })])

    const wrapper = await mountOperational(Departures)

    expect(buttonsWithText(wrapper, 'Open folio')).toHaveLength(0)
  })

  it('offers extend in the drawer to a stay-operation role', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Departures)
    await buttonsWithText(wrapper, 'Details')[0].trigger('click')
    await flush(wrapper)

    const panel = document.body.querySelector('[data-drawer-panel]')

    expect(panel.textContent).toContain('Extend stay')
    expect(panel.textContent).toContain('Layla Haddad')
  })

  it('hides extend from a role the server would refuse', async () => {
    stubSession(['Room Attendant'])
    board.data = boardData([row()])

    const wrapper = await mountOperational(Departures)
    await buttonsWithText(wrapper, 'Details')[0].trigger('click')
    await flush(wrapper)

    const panel = document.body.querySelector('[data-drawer-panel]')

    expect(panel.textContent).not.toContain('Extend stay')
  })

  it('hides extend from a stay that has already departed', async () => {
    board.data = boardData([row({ is_checked_out: true, stay_status: 'Checked Out' })])

    const wrapper = await mountOperational(Departures)
    await buttonsWithText(wrapper, 'Details')[0].trigger('click')
    await flush(wrapper)

    const panel = document.body.querySelector('[data-drawer-panel]')

    expect(panel.textContent).not.toContain('Extend stay')
  })

  it('shows the blockers in the drawer for a blocked stay', async () => {
    const blocker = 'Folio has an outstanding balance of QAR 420.00.'
    board.data = boardData([row({ can_check_out: false, blockers: [blocker] })])

    const wrapper = await mountOperational(Departures)
    await buttonsWithText(wrapper, 'Details')[0].trigger('click')
    await flush(wrapper)

    const panel = document.body.querySelector('[data-drawer-panel]')

    expect(panel.textContent).toContain('Blocked by')
    expect(panel.textContent).toContain(blocker)
  })
})
