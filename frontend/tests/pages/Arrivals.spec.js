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

const { board, cancelRes, noShowRes } = vi.hoisted(() => ({
  board: { data: null, loading: false, error: null, fetch: vi.fn() },
  cancelRes: { data: null, loading: false, error: null, submit: vi.fn() },
  noShowRes: { data: null, loading: false, error: null, submit: vi.fn() },
}))

vi.mock('@/resources/frontOffice', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, arrivalsBoardResource: () => board }
})

/**
 * The two ending verbs post to the server, so their resources are stubbed. The
 * role constants come from the real module: `NO_SHOW_ROLES` mirrors the server
 * list, and a test that stubbed it would prove nothing about the role rule.
 */
vi.mock('@/resources/reservations', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, cancelReservationResource: () => cancelRes, noShowResource: () => noShowRes }
})

const { default: Arrivals } = await import('@/pages/Arrivals.vue')

/** One arrivals row, shaped exactly as `services.front_office` sends it. */
function row(overrides = {}) {
  return {
    key: 'RES-LINE-1',
    reservation: 'HPMS-RES-2026-00001',
    room_line: 'RES-LINE-1',
    reservation_status: 'Confirmed',
    // The server's own state machine, sent per row. Never re-derived in Vue.
    allowed_transitions: ['Guaranteed', 'Checked In', 'Cancelled', 'No Show'],
    // How many rooms the *reservation* holds. This board is one row per room
    // line, so a three-room booking sends three rows all carrying 3.
    total_rooms: 1,
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

/**
 * All buttons carrying this exact visible text, in either rendering.
 *
 * Scoped to the mounted tree, which is what makes the "drawer only" tests mean
 * something: the drawer and the dialogs teleport to `document.body` and are
 * therefore invisible to this helper by construction.
 */
function buttonsWithText(wrapper, text) {
  return wrapper.findAll('button').filter((button) => button.text().trim() === text)
}

async function openDrawer(wrapper) {
  await buttonsWithText(wrapper, 'Details')[0].trigger('click')
  await flush(wrapper)

  return document.body.querySelector('[data-drawer-panel]')
}

async function clickInDrawer(wrapper, text) {
  const button = Array.from(document.body.querySelectorAll('[data-drawer-panel] button')).find(
    (candidate) => candidate.textContent.trim() === text,
  )

  button.click()
  await flush(wrapper)
}

/** Click a button in the open dialog, which is outside the drawer panel. */
async function clickInDialog(wrapper, text) {
  const button = Array.from(document.body.querySelectorAll('button')).find(
    (candidate) =>
      candidate.textContent.trim() === text && !candidate.closest('[data-drawer-panel]'),
  )

  button.click()
  await flush(wrapper)
}

function dialogConfirm(text) {
  return Array.from(document.body.querySelectorAll('button')).find(
    (candidate) => candidate.textContent.trim() === text,
  )
}

/** Type into the dialog's reason field the way a keyboard does. */
async function typeReason(wrapper, value) {
  const textarea = document.body.querySelector('textarea')

  textarea.value = value
  textarea.dispatchEvent(new Event('input'))
  await flush(wrapper)

  return textarea
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Agent'])
  board.data = null
  board.loading = false
  board.error = null
  board.fetch.mockClear()
  cancelRes.submit.mockReset()
  noShowRes.submit.mockReset()
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

  it('distinguishes "not flagged" from "not disclosed to you"', async () => {
    // The server omits `is_blacklisted` entirely for a caller who is not cleared
    // for it, rather than sending `false` — so the cell has three states, and two
    // of them must not look alike. A cleared reader seeing the dash has been told
    // this guest is not flagged; an uncleared reader has been told nothing, and
    // borrowing the dash would hand them a clearance the server withheld.
    const disclosed = row({ is_blacklisted: false })
    const withheld = row({ key: 'RES-LINE-2', guest_name: 'Omar Nasser' })
    delete withheld.is_blacklisted

    board.data = boardData([disclosed, withheld])

    const wrapper = await mountOperational(Arrivals)
    const cells = wrapper.findAll('tbody tr').map((tr) => tr.findAll('td').at(-2).text())

    expect(cells[0]).toBe('—')
    expect(cells[1]).not.toBe('—')
    expect(wrapper.text()).not.toContain('Blacklisted')
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

describe('Arrivals folio link', () => {
  it('is offered only where the row actually carries a folio', async () => {
    // An arrival has no folio before check-in; a checked-in row may have one.
    board.data = boardData([row()])

    let wrapper = await mountOperational(Arrivals)
    expect(buttonsWithText(wrapper, 'Open folio')).toHaveLength(0)

    board.data = boardData([row({ is_checked_in: true, stay: 'HPMS-STAY-1', folio: 'HPMS-FOL-2026-00001' })])
    wrapper = await mountOperational(Arrivals)

    expect(buttonsWithText(wrapper, 'Open folio').length).toBeGreaterThan(0)
  })

  it('navigates to the folio it was given', async () => {
    board.data = boardData([row({ is_checked_in: true, folio: 'HPMS-FOL-2026-00001' })])
    const router = testRouter()

    const wrapper = await mountOperational(Arrivals, { router })
    await buttonsWithText(wrapper, 'Open folio')[0].trigger('click')
    await flush(wrapper)

    expect(router.currentRoute.value.name).toBe('Folio')
    expect(router.currentRoute.value.params.id).toBe('HPMS-FOL-2026-00001')
  })
})

/**
 * Cancel and no-show.
 *
 * The rule these tests exist to defend: both verbs act on the whole reservation
 * and `_propagate_status` stamps every room line, while this board is one row per
 * room line. Neither may be a row action, and the scope has to be on screen
 * before either can be reached.
 */
describe('Arrivals ending verbs are drawer-only', () => {
  beforeEach(() => {
    // A manager holds both roles, so both verbs are on offer and the "row action"
    // assertions below cannot pass merely because a role withheld them.
    stubSession(['Front Office Manager'])
  })

  it('puts neither verb in the row action list', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)

    expect(buttonsWithText(wrapper, 'Cancel reservation')).toHaveLength(0)
    expect(buttonsWithText(wrapper, 'Mark no-show')).toHaveLength(0)
  })

  it('offers both in the drawer', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    const panel = await openDrawer(wrapper)

    expect(panel.textContent).toContain('Cancel reservation')
    expect(panel.textContent).toContain('Mark no-show')
  })

  it('names the room count in the drawer for a multi-room reservation', async () => {
    board.data = boardData([row({ total_rooms: 3 })])

    const wrapper = await mountOperational(Arrivals)
    const panel = await openDrawer(wrapper)

    expect(panel.textContent).toContain('all 3 of its rooms')
    expect(panel.textContent).toContain('This cancels the whole reservation')
    expect(panel.textContent).toContain('marks the whole reservation as a no-show')
  })

  it('states the single-room scope when the reservation holds one room', async () => {
    board.data = boardData([row({ total_rooms: 1 })])

    const wrapper = await mountOperational(Arrivals)
    const panel = await openDrawer(wrapper)

    expect(panel.textContent).toContain('This cancels the reservation and its room.')
    expect(panel.textContent).not.toContain('whole reservation')
  })

  it('withholds both from a row that is already checked in', async () => {
    // A checked-in room line is a stay, and ending it is a checkout. The server
    // agrees: `Checked In` transitions only to `Checked Out`.
    board.data = boardData([
      row({ is_checked_in: true, stay: 'HPMS-STAY-1', reservation_status: 'Checked In', allowed_transitions: ['Checked Out'] }),
    ])

    const wrapper = await mountOperational(Arrivals)
    const panel = await openDrawer(wrapper)

    expect(panel.textContent).not.toContain('Cancel reservation')
    expect(panel.textContent).not.toContain('Mark no-show')
  })

  it('withholds both when the server offered neither transition', async () => {
    board.data = boardData([row({ allowed_transitions: ['Guaranteed', 'Checked In'] })])

    const wrapper = await mountOperational(Arrivals)
    const panel = await openDrawer(wrapper)

    // The state machine is the server's; an absent offer is not second-guessed.
    expect(panel.textContent).not.toContain('Cancel reservation')
    expect(panel.textContent).not.toContain('Mark no-show')
  })

  it('withholds both when the row does not say how many rooms are at stake', async () => {
    const { total_rooms: _dropped, ...withoutCount } = row()
    board.data = boardData([withoutCount])

    const wrapper = await mountOperational(Arrivals)
    const panel = await openDrawer(wrapper)

    // The count is never counted from the visible rows: a filtered board is a
    // subset, and understating the scope is the accident being prevented.
    expect(panel.textContent).not.toContain('Cancel reservation')
    expect(panel.textContent).not.toContain('Mark no-show')
  })

  it('offers neither as a disabled control — they are withheld or offered', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)

    const buttons = Array.from(document.body.querySelectorAll('[data-drawer-panel] button')).filter(
      (button) => ['Cancel reservation', 'Mark no-show'].includes(button.textContent.trim()),
    )

    expect(buttons).toHaveLength(2)
    // `allowed_transitions` is as old as the last board fetch, and the board is
    // never polled. A stale offer must reach the server and be refused there.
    for (const button of buttons) expect(button.disabled).toBe(false)
  })
})

describe('Arrivals no-show role', () => {
  it('is hidden from a Front Office Agent, whom the server refuses', async () => {
    stubSession(['Front Office Agent'])
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    const panel = await openDrawer(wrapper)

    // `NO_SHOW_ROLES` excludes Front Office Agent: a no-show is an end-of-day
    // audit judgement. Cancellation is a front-desk verb and stays on offer.
    expect(panel.textContent).not.toContain('Mark no-show')
    expect(panel.textContent).toContain('Cancel reservation')
  })

  it('is shown to a Front Office Manager', async () => {
    stubSession(['Front Office Manager'])
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    const panel = await openDrawer(wrapper)

    expect(panel.textContent).toContain('Mark no-show')
  })

  it('is shown to a Night Auditor, who is not a front-desk role at all', async () => {
    stubSession(['Night Auditor'])
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    const panel = await openDrawer(wrapper)

    expect(panel.textContent).toContain('Mark no-show')
    // Cancellation mirrors FRONT_DESK_ROLES, which a Night Auditor is not in.
    expect(panel.textContent).not.toContain('Cancel reservation')
  })
})

describe('Arrivals cancellation dialog', () => {
  beforeEach(() => {
    stubSession(['Front Office Manager'])
  })

  it('closes the drawer before opening, and repeats the scope there', async () => {
    board.data = boardData([row({ total_rooms: 3 })])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Cancel reservation')

    expect(document.body.querySelector('[data-drawer-panel]')).toBeNull()
    expect(document.body.textContent).toContain('Cancel this reservation')
    expect(document.body.textContent).toContain('all 3 of its rooms')
  })

  it('refuses to submit until a reason is given', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Cancel reservation')

    // `services.reservations.cancel` throws on a blank reason, so the dialog
    // never spends a round trip discovering that.
    expect(dialogConfirm('Cancel the reservation').disabled).toBe(true)

    await typeReason(wrapper, '   ')
    expect(dialogConfirm('Cancel the reservation').disabled).toBe(true)

    await typeReason(wrapper, 'Guest cancelled by phone')
    expect(dialogConfirm('Cancel the reservation').disabled).toBe(false)
  })

  it('sends the reservation and the trimmed reason, and reloads the board', async () => {
    cancelRes.submit.mockResolvedValue({ cancellation: { status: 'Cancelled', cancellation_charge: 0 } })
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Cancel reservation')
    await typeReason(wrapper, '  Guest cancelled by phone  ')

    board.fetch.mockClear()
    await clickInDialog(wrapper, 'Cancel the reservation')

    expect(cancelRes.submit).toHaveBeenCalledWith({
      reservation: 'HPMS-RES-2026-00001',
      reason: 'Guest cancelled by phone',
    })
    // No waive_charge is sent: it needs CANCEL_OVERRIDE_ROLES and the server's
    // default is the right answer for this build.
    expect(Object.keys(cancelRes.submit.mock.calls[0][0])).toEqual(['reservation', 'reason'])
    expect(board.fetch).toHaveBeenCalledWith({ property: 'DOHA01' })
  })

  it('reports the policy charge as policy, and never as a payment', async () => {
    cancelRes.submit.mockResolvedValue({ cancellation: { status: 'Cancelled', cancellation_charge: 250 } })
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Cancel reservation')
    await typeReason(wrapper, 'Guest cancelled by phone')
    await clickInDialog(wrapper, 'Cancel the reservation')

    const text = document.body.textContent

    expect(text).toContain('The reservation was cancelled.')
    expect(text).toContain('Cancellation charge')
    expect(text).toContain('250.00')

    // `cancel` writes `Reservation.cancellation_charge` and posts nothing: no
    // Folio Charge, no ledger entry. Nothing here may read as a receipt.
    expect(text).not.toMatch(/paid|payment|received|collected|refunded/i)
  })

  it('says nothing about a charge when the policy charged nothing', async () => {
    cancelRes.submit.mockResolvedValue({ cancellation: { status: 'Cancelled', cancellation_charge: 0 } })
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Cancel reservation')
    await typeReason(wrapper, 'Guest cancelled by phone')
    await clickInDialog(wrapper, 'Cancel the reservation')

    expect(document.body.textContent).toContain('The reservation was cancelled.')
    expect(document.body.textContent).not.toContain('Cancellation charge')
  })

  it('shows no charge before submitting: the row carries none and Vue prices nothing', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Cancel reservation')

    expect(document.body.textContent).not.toContain('Cancellation charge')
  })

  it("surfaces the server's refusal of a stale offer in the server's words", async () => {
    // The board is fetched once per load. By the time the row is acted on the
    // reservation may already be cancelled, and the server re-reads it under a
    // lock — so the offer fails cleanly rather than being pre-emptively disabled.
    cancelRes.submit.mockRejectedValue({
      status: 409,
      exc_type: 'InvalidStateTransitionError',
      message: 'Reservation HPMS-RES-2026-00001 cannot move from Cancelled to Cancelled.',
    })
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Cancel reservation')
    await typeReason(wrapper, 'Guest cancelled by phone')
    await clickInDialog(wrapper, 'Cancel the reservation')

    expect(document.body.textContent).toContain('cannot move from Cancelled to Cancelled')
    expect(document.body.textContent).not.toContain('The reservation was cancelled.')
  })
})

describe('Arrivals no-show dialog', () => {
  beforeEach(() => {
    stubSession(['Front Office Manager'])
  })

  it('states the scope and that the charge is the property policy', async () => {
    board.data = boardData([row({ total_rooms: 3 })])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Mark no-show')

    expect(document.body.querySelector('[data-drawer-panel]')).toBeNull()
    expect(document.body.textContent).toContain('Mark this reservation as a no-show')
    expect(document.body.textContent).toContain('all 3 of its rooms')
    expect(document.body.textContent).toContain("The server decides any no-show charge")
  })

  it('submits without a reason, which the server accepts', async () => {
    noShowRes.submit.mockResolvedValue({ no_show: { status: 'No Show', no_show_charge: 0 } })
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Mark no-show')

    // `mark_no_show` accepts `reason=None` and records its own wording.
    expect(dialogConfirm('Mark as no-show').disabled).toBe(false)

    board.fetch.mockClear()
    await clickInDialog(wrapper, 'Mark as no-show')

    expect(noShowRes.submit).toHaveBeenCalledWith({
      reservation: 'HPMS-RES-2026-00001',
      reason: undefined,
    })
    expect(board.fetch).toHaveBeenCalledWith({ property: 'DOHA01' })
  })

  it('reports the no-show charge as policy, and never as a payment', async () => {
    noShowRes.submit.mockResolvedValue({ no_show: { status: 'No Show', no_show_charge: 400 } })
    board.data = boardData([row()])

    const wrapper = await mountOperational(Arrivals)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Mark no-show')
    await clickInDialog(wrapper, 'Mark as no-show')

    const text = document.body.textContent

    expect(text).toContain('The reservation was marked as a no-show.')
    expect(text).toContain('No-show charge')
    expect(text).toContain('400.00')
    // `mark_no_show` computes the figure and posts nothing.
    expect(text).not.toMatch(/paid|payment|received|collected|refunded/i)
  })
})
