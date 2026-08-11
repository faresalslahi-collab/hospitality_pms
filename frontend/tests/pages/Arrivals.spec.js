/**
 * Arrivals board regression, after the migration onto OperationalDataTable.
 *
 * These are parity tests before they are anything else: the board must still
 * render the day, still report loading, empty and failure the same way, still
 * refetch on the property alone, and still refuse to say anything about a guest
 * alert beyond the fact that one exists.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { flush, mountOperational, resetStores, stubProperty, stubSession, testRouter } from '../helpers'

const { board } = vi.hoisted(() => ({
  board: { data: null, loading: false, error: null, fetch: vi.fn() },
}))

vi.mock('@/resources/frontOffice', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, arrivalsBoardResource: () => board }
})

const { default: Arrivals } = await import('@/pages/Arrivals.vue')

/** One arrivals row, shaped exactly as `services.front_office` sends it. */
function row(overrides = {}) {
  return {
    key: 'RES-LINE-1',
    reservation: 'HPMS-RES-2026-00001',
    room_line: 'RES-LINE-1',
    reservation_status: 'Confirmed',
    reservation_type: 'Individual',
    booking_source: 'Direct',
    guest: 'HPMS-GUEST-0001',
    guest_name: 'Layla Haddad',
    guest_mobile: '+97400000000',
    vip_status: '',
    is_blacklisted: false,
    arrival_date: '2026-08-08',
    departure_date: '2026-08-10',
    arrival_time: '18:00:00',
    nights: 2,
    adults: 2,
    children: 1,
    room_type: 'DLX',
    room_type_name: 'Deluxe',
    assigned_room: null,
    room_number: null,
    room_ready: false,
    room_assignable: false,
    occupancy_status: null,
    housekeeping_status: null,
    guarantee_type: 'Credit Card',
    deposit_required: 250,
    deposit_received: 0,
    deposit_outstanding: 250,
    room_rate: 400,
    currency: 'QAR',
    special_requests: 'High floor',
    is_checked_in: false,
    stay: null,
    ...overrides,
  }
}

function boardData(rows, summary = {}) {
  return {
    property: 'DOHA01',
    business_date: '2026-08-08',
    currency: 'QAR',
    rows,
    summary: { total: rows.length, pending: rows.length, ...summary },
  }
}

/** All buttons carrying this exact visible text, in either rendering. */
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

describe('Arrivals board', () => {
  it('renders the day it was given', async () => {
    board.data = boardData([row(), row({ key: 'RES-LINE-2', guest_name: 'Omar Nasser', room_number: '101', assigned_room: 'DOHA01-101', housekeeping_status: 'Vacant Clean', room_ready: true })])

    const wrapper = await mountOperational(Arrivals)

    expect(wrapper.text()).toContain('Layla Haddad')
    expect(wrapper.text()).toContain('Omar Nasser')
    expect(wrapper.text()).toContain('HPMS-RES-2026-00001')
    expect(wrapper.text()).toContain('Deluxe')
    // A room line with no room says so rather than showing an empty cell.
    expect(wrapper.text()).toContain('Not assigned')
    expect(wrapper.text()).toContain('Vacant Clean')
    expect(wrapper.text()).toContain('Confirmed')
  })

  it('links a reservation to its own screen', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    const link = wrapper.findAll('a').find((a) => a.text() === 'HPMS-RES-2026-00001')

    expect(link.attributes('href')).toBe('/reservations/HPMS-RES-2026-00001')
  })

  it('shows the ETA beside the arrival date, without seconds', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)

    expect(wrapper.text()).toContain('18:00')
    expect(wrapper.text()).not.toContain('18:00:00')
  })

  it('reports loading before the first response', async () => {
    board.loading = true

    const wrapper = await mountOperational(Arrivals)

    expect(wrapper.text()).toContain('Loading')
  })

  it('reports an empty day with the board wording', async () => {
    board.data = boardData([])

    const wrapper = await mountOperational(Arrivals)

    expect(wrapper.text()).toContain('No arrivals for this date.')
  })

  it('distinguishes an empty day from an empty filter', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await wrapper.find('input').setValue('nobody by this name')
    await flush(wrapper)

    expect(wrapper.text()).toContain('No arrivals match this filter.')
    expect(wrapper.text()).not.toContain('No arrivals for this date.')
  })

  it('narrows the board by search without refetching it', async () => {
    board.data = boardData([row(), row({ key: 'RES-LINE-2', guest_name: 'Omar Nasser' })])

    const wrapper = await mountOperational(Arrivals)
    const fetchesBefore = board.fetch.mock.calls.length

    await wrapper.find('input').setValue('Omar')
    await flush(wrapper)

    expect(wrapper.text()).toContain('Omar Nasser')
    expect(wrapper.text()).not.toContain('Layla Haddad')
    expect(board.fetch.mock.calls.length).toBe(fetchesBefore)
  })

  it('reports a failure in place, with a retry that refetches', async () => {
    board.error = { status: 500, message: 'Internal Server Error' }

    const wrapper = await mountOperational(Arrivals)

    expect(wrapper.text()).toContain('Something went wrong')

    const retry = buttonsWithText(wrapper, 'Retry')
    expect(retry.length).toBeGreaterThan(0)

    board.fetch.mockClear()
    await retry[0].trigger('click')

    expect(board.fetch).toHaveBeenCalledWith({ property: 'DOHA01' })
  })

  it('reports a permission failure without offering a retry', async () => {
    board.error = { status: 403, exc_type: 'PermissionError', message: 'Not allowed' }

    const wrapper = await mountOperational(Arrivals)

    expect(wrapper.text()).toContain('Not permitted')
    expect(buttonsWithText(wrapper, 'Retry')).toHaveLength(0)
  })

  it('fetches on the property alone — never a client-supplied date', async () => {
    board.data = boardData([row()])

    await mountOperational(Arrivals)

    expect(board.fetch).toHaveBeenCalledWith({ property: 'DOHA01' })

    for (const [params] of board.fetch.mock.calls) {
      expect(params).not.toHaveProperty('on_date')
      expect(Object.keys(params)).toEqual(['property'])
    }
  })

  it('refetches when the active property changes', async () => {
    board.data = boardData([row()])

    await mountOperational(Arrivals)
    board.fetch.mockClear()

    stubProperty({ name: 'DOHA02', property_name: 'Doha Corniche' })
    await flush()

    expect(board.fetch).toHaveBeenCalledWith({ property: 'DOHA02' })
  })
})

describe('Arrivals row actions', () => {
  it('navigates to check-in for a row that has not arrived', async () => {
    board.data = boardData([row()])
    const router = testRouter()

    const wrapper = await mountOperational(Arrivals, { router })
    await buttonsWithText(wrapper, 'Check in')[0].trigger('click')
    await flush(wrapper)

    expect(router.currentRoute.value.name).toBe('CheckIn')
    expect(router.currentRoute.value.params.reservation).toBe('HPMS-RES-2026-00001')
  })

  it('withholds check-in from a row that is already in house', async () => {
    board.data = boardData([row({ is_checked_in: true, stay: 'HPMS-STAY-1' })])

    const wrapper = await mountOperational(Arrivals)

    expect(buttonsWithText(wrapper, 'Check in')).toHaveLength(0)
  })

  it('offers room assignment to a front desk role, on an unassigned row', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)

    expect(buttonsWithText(wrapper, 'Assign room').length).toBeGreaterThan(0)
  })

  it('hides room assignment from a role the server would refuse', async () => {
    stubSession(['Room Attendant'])
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)

    expect(buttonsWithText(wrapper, 'Assign room')).toHaveLength(0)
  })

  it('hides room assignment once a room is assigned', async () => {
    board.data = boardData([row({ assigned_room: 'DOHA01-101', room_number: '101' })])

    const wrapper = await mountOperational(Arrivals)

    expect(buttonsWithText(wrapper, 'Assign room')).toHaveLength(0)
  })

  it('opens the contextual drawer with the row summary', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await buttonsWithText(wrapper, 'Details')[0].trigger('click')
    await flush(wrapper)

    const panel = document.body.querySelector('[data-drawer-panel]')

    expect(panel).not.toBeNull()
    expect(panel.textContent).toContain('Layla Haddad')
    expect(panel.textContent).toContain('Credit Card')
    expect(panel.textContent).toContain('High floor')
  })
})

describe('Arrivals alert disclosure', () => {
  it('says an alert exists for a blacklisted guest', async () => {
    board.data = boardData([row({ is_blacklisted: true })])

    const wrapper = await mountOperational(Arrivals)

    expect(wrapper.text()).toContain('Blacklisted')
  })

  it('shows no alert indication for a guest with no flag', async () => {
    board.data = boardData([row({ is_blacklisted: false })])

    const wrapper = await mountOperational(Arrivals)

    expect(wrapper.text()).not.toContain('Blacklisted')
    // And no affirmative all-clear either: this board never asks the alert
    // register, so it is in no position to certify that a guest is clean.
    expect(wrapper.text()).not.toContain('No alerts')
  })

  it('never renders a blacklist reason, even when one is smuggled onto the row', async () => {
    const reason = 'Card chargeback, incident 2025-114'
    board.data = boardData([row({ is_blacklisted: true, blacklist_reason: reason })])

    const wrapper = await mountOperational(Arrivals)

    expect(wrapper.html()).not.toContain(reason)
    expect(wrapper.html()).not.toContain('chargeback')
  })
})

describe('Arrivals money', () => {
  it('flags an outstanding deposit as a qualified amount, not a bare column figure', async () => {
    board.data = boardData([row({ deposit_outstanding: 250 })])

    const wrapper = await mountOperational(Arrivals)

    // Qualified: the amount is accompanied by wording that says what it is, so a
    // per-booking figure repeated across a booking's room lines cannot read as a
    // column of separate debts.
    expect(wrapper.text()).toContain('Deposit due')
    expect(wrapper.text()).toMatch(/250/)
  })

  it('shows no deposit figure when nothing is outstanding', async () => {
    board.data = boardData([row({ deposit_required: 250, deposit_received: 250, deposit_outstanding: 0 })])

    const wrapper = await mountOperational(Arrivals)

    expect(wrapper.text()).not.toContain('Deposit due')
  })
})
