/**
 * In-house board regression, on the enriched endpoint (16.7.1).
 *
 * `api.stays.in_house` is now served by `front_office.get_in_house_board`, so the
 * row carries a balance, a currency, an alert count and grade, an identification
 * flag and the checkout service's own verdict. This file is about consuming that
 * honestly, and most of it is still about restraint:
 *
 * - the balance is labelled with the row's currency, never the property's;
 * - `can_check_out` is rendered on a Due Out row and withheld from an In House one,
 *   because it is true for most of the house on any morning;
 * - an alert is a count and a grade, never a body;
 * - `is_blacklisted` absent means "not disclosed", so no negative is rendered;
 * - `id_verified` is an exception display, never a column of ticks.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { flush, mountOperational, resetStores, stubProperty, stubSession, testRouter } from '../helpers'

const { board } = vi.hoisted(() => ({
  board: { data: null, loading: false, error: null, fetch: vi.fn() },
}))

vi.mock('@/resources/stays', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, inHouseResource: () => board }
})

/**
 * ChangeRoomDialog asks the availability service for assignable rooms the moment
 * it opens. No test may reach the network, so the lookup is stubbed here — the
 * dialog's own behaviour is not what these tests are about.
 */
vi.mock('@/resources/availability', async (importOriginal) => {
  const actual = await importOriginal()

  return {
    ...actual,
    assignableRoomsResource: () => ({ data: [], loading: false, error: null, fetch: vi.fn() }),
  }
})

const { default: InHouse } = await import('@/pages/InHouse.vue')

/**
 * One in-house row, as `front_office.get_in_house_board` sends it.
 *
 * `is_blacklisted` is deliberately NOT in the default row: the key is
 * permission-gated and is absent for a caller who is not cleared to see it, which
 * is the common case and the one the privacy tests below are about.
 */
function row(overrides = {}) {
  return {
    key: 'HPMS-STAY-2026-00001',
    name: 'HPMS-STAY-2026-00001',
    stay: 'HPMS-STAY-2026-00001',
    stay_status: 'In House',
    reservation: 'HPMS-RES-2026-00001',
    property: 'DOHA01',
    guest: 'HPMS-GUEST-0001',
    guest_name: 'Layla Haddad',
    vip_status: '',
    alert_count: 0,
    alert_severity: '',
    id_verified: true,
    room: 'DOHA01-101',
    room_number: '101',
    room_type: 'DLX',
    room_type_name: 'Deluxe',
    housekeeping_status: 'Occupied Clean',
    arrival_date: '2026-08-06',
    departure_date: '2026-08-10',
    nights: 4,
    adults: 2,
    children: 1,
    room_rate: 400,
    folio: 'HPMS-FOL-2026-00001',
    folio_status: 'Open',
    balance: 0,
    related_folios: 0,
    related_balance: 0,
    currency: 'QAR',
    blockers: [],
    can_check_out: true,
    ...overrides,
  }
}

function boardData(stays, summary = {}) {
  return {
    property: 'DOHA01',
    business_date: '2026-08-08',
    currency: 'QAR',
    stays,
    summary: {
      total: stays.length,
      in_house: stays.filter((s) => s.stay_status === 'In House').length,
      due_out: stays.filter((s) => s.stay_status === 'Due Out').length,
      adults: 2,
      children: 1,
      vip: 0,
      with_alerts: 0,
      ready_to_check_out: stays.filter((s) => s.can_check_out).length,
      blocked: 0,
      balance_pending: 0,
      outstanding_balance: 0,
      ...summary,
    },
  }
}

function buttonsWithText(wrapper, text) {
  return wrapper.findAll('button').filter((button) => button.text().trim() === text)
}

/** The rows only: a tile label is a different statement from a row's claim. */
function bodyText(wrapper) {
  return wrapper.find('tbody').text()
}

async function openDrawer(wrapper) {
  await buttonsWithText(wrapper, 'Details')[0].trigger('click')
  await flush(wrapper)

  return document.body.querySelector('[data-drawer-panel]')
}

/** Click a button inside the open drawer panel by its visible text. */
async function clickInDrawer(wrapper, text) {
  const button = Array.from(document.body.querySelectorAll('[data-drawer-panel] button')).find(
    (candidate) => candidate.textContent.trim() === text,
  )

  button.click()
  await flush(wrapper)
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

describe('In-house board', () => {
  it('renders the rows it was given', async () => {
    board.data = boardData([
      row(),
      row({ name: 'S2', room: 'DOHA01-102', room_number: '102', guest_name: 'Omar Nasser', stay_status: 'Due Out' }),
    ])

    const wrapper = await mountOperational(InHouse)

    expect(wrapper.text()).toContain('Layla Haddad')
    expect(wrapper.text()).toContain('Omar Nasser')
    expect(wrapper.text()).toContain('In House')
    expect(wrapper.text()).toContain('Due Out')
  })

  it('shows the door number, not the room docname, when the row carries one', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    const link = wrapper.findAll('a').find((a) => a.text() === '101')

    expect(link.attributes('href')).toBe('/stays/HPMS-STAY-2026-00001')
  })

  it('falls back to the room docname when no door number arrived', async () => {
    board.data = boardData([row({ room_number: null })])

    const wrapper = await mountOperational(InHouse)

    expect(wrapper.findAll('a').some((a) => a.text() === 'DOHA01-101')).toBe(true)
  })

  it('reports loading, empty and failure the way every board does', async () => {
    board.loading = true
    let wrapper = await mountOperational(InHouse)
    expect(wrapper.text()).toContain('Loading')

    board.loading = false
    board.data = boardData([])
    wrapper = await mountOperational(InHouse)
    expect(wrapper.text()).toContain('No guests are in house right now.')

    board.data = null
    board.error = { status: 500 }
    wrapper = await mountOperational(InHouse)
    expect(wrapper.text()).toContain('Something went wrong')
  })

  it('fetches on the property alone, and refetches when it changes', async () => {
    board.data = boardData([row()])

    await mountOperational(InHouse)
    expect(board.fetch).toHaveBeenCalledWith({ property: 'DOHA01' })
    for (const [params] of board.fetch.mock.calls) {
      expect(Object.keys(params)).toEqual(['property'])
    }

    board.fetch.mockClear()
    stubProperty({ name: 'DOHA02' })
    await flush()

    expect(board.fetch).toHaveBeenCalledWith({ property: 'DOHA02' })
  })

  it('narrows by search without refetching', async () => {
    board.data = boardData([row(), row({ name: 'S2', guest_name: 'Omar Nasser', room_number: '102' })])

    const wrapper = await mountOperational(InHouse)
    board.fetch.mockClear()

    await wrapper.find('input').setValue('Omar')
    await flush(wrapper)

    expect(wrapper.text()).toContain('Omar Nasser')
    expect(wrapper.text()).not.toContain('Layla Haddad')
    expect(board.fetch).not.toHaveBeenCalled()
  })
})

describe('In-house money', () => {
  it("labels the balance with the row's own currency, never the property's", async () => {
    // The property is QAR (see stubProperty); this stay is billed in USD. The old
    // board assumed the property currency, which would have mislabelled it.
    board.data = boardData([row({ balance: 420.5, currency: 'USD' })])

    const wrapper = await mountOperational(InHouse)

    expect(bodyText(wrapper)).toMatch(/420\.50/)
    // `formatCurrency` renders USD with its own symbol; QAR renders as the code,
    // which is what the old property-currency assumption would have produced here.
    expect(bodyText(wrapper)).toMatch(/US\$/)
    expect(bodyText(wrapper)).not.toMatch(/QAR/)
  })

  it('renders a settled balance as a balance, not as permission to depart', async () => {
    board.data = boardData([row({ balance: 0 })])

    const wrapper = await mountOperational(InHouse)

    expect(bodyText(wrapper)).toMatch(/0\.00/)
    expect(bodyText(wrapper)).not.toContain('Ready to check out')
  })

  it('counts split folios rather than summing them into the balance', async () => {
    // The rate is deliberately not 400 here: 400 is the merged figure this test
    // watches for, and the rate column would otherwise supply it innocently.
    board.data = boardData([row({ balance: 100, related_folios: 2, related_balance: 300, room_rate: 380 })])

    const wrapper = await mountOperational(InHouse)

    expect(bodyText(wrapper)).toContain('2 split folio(s)')
    // 400 would be the merged figure; the two settle separately.
    expect(bodyText(wrapper)).not.toMatch(/400\.00/)
  })
})

describe('In-house checkout readiness', () => {
  it('states the readiness of a stay that is leaving today', async () => {
    board.data = boardData([row({ stay_status: 'Due Out', can_check_out: true })])

    const wrapper = await mountOperational(InHouse)

    expect(bodyText(wrapper)).toContain('Ready to check out')
  })

  it('states the refusal, in the server words, on a blocked Due Out stay', async () => {
    const blocker = 'Folio HPMS-FOL-2026-00001 has an outstanding balance of QAR 420.00.'
    board.data = boardData([
      row({ stay_status: 'Due Out', can_check_out: false, blockers: [blocker], balance: 420 }),
    ])

    const wrapper = await mountOperational(InHouse)
    const panel = await openDrawer(wrapper)

    expect(bodyText(wrapper)).toContain('Cannot check out')
    expect(panel.textContent).toContain('Blocked by')
    expect(panel.textContent).toContain(blocker)
  })

  it('makes no readiness claim on an In House row, even though the server sent one', async () => {
    // `can_check_out` genuinely arrives now and is true for most of the house on
    // any morning. A badge on a mid-stay row would read "the hotel is ready to
    // leave", so the claim is confined to the rows that are actually leaving.
    board.data = boardData([
      row({ stay_status: 'In House', can_check_out: true }),
      row({ name: 'S2', room_number: '102', stay_status: 'Due Out', can_check_out: true }),
    ])

    const wrapper = await mountOperational(InHouse)
    const rows = wrapper.findAll('tbody tr')

    const inHouseRow = rows.find((candidate) => candidate.text().includes('101'))
    const dueOutRow = rows.find((candidate) => candidate.text().includes('102'))

    expect(inHouseRow.text()).not.toContain('Ready to check out')
    expect(inHouseRow.text()).not.toContain('Cannot check out')
    // Allowed, and expected, on the row that is leaving.
    expect(dueOutRow.text()).toContain('Ready to check out')
  })
})

describe('In-house attention column', () => {
  it('renders the alert count and its grade', async () => {
    board.data = boardData([row({ alert_count: 2, alert_severity: 'Critical' })])

    const wrapper = await mountOperational(InHouse)

    expect(bodyText(wrapper)).toContain('2 alerts')
    expect(bodyText(wrapper)).toContain('High')
  })

  it('maps every server grade onto the badge vocabulary', async () => {
    board.data = boardData([
      row({ alert_count: 1, alert_severity: 'Warning' }),
      row({ name: 'S2', room_number: '102', alert_count: 1, alert_severity: 'Info' }),
    ])

    const wrapper = await mountOperational(InHouse)

    expect(bodyText(wrapper)).toContain('Medium')
    expect(bodyText(wrapper)).toContain('Low')
  })

  it('never renders an alert body, even when one is smuggled onto the row', async () => {
    const detail = 'Threatened staff on 2025-11-04, incident 114'
    board.data = boardData([
      row({ alert_count: 1, alert_severity: 'Critical', alerts: [{ description: detail }], alert_reason: detail }),
    ])

    const wrapper = await mountOperational(InHouse)

    expect(wrapper.html()).not.toContain(detail)
    expect(wrapper.html()).not.toContain('incident 114')
  })

  it('renders no alert state at all for a row the server flagged nothing on', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)

    // The column heading is the heading; the row makes no claim, in either
    // direction. This board never certifies a guest as clear.
    expect(bodyText(wrapper)).not.toContain('No alerts')
    expect(bodyText(wrapper)).not.toContain('Blacklisted')
  })

  it('says an alert exists for a guest disclosed as blacklisted', async () => {
    board.data = boardData([row({ is_blacklisted: true })])

    const wrapper = await mountOperational(InHouse)

    expect(bodyText(wrapper)).toContain('Blacklisted')
  })

  it('renders no negative claim when the blacklist key was withheld', async () => {
    // Absence is "not disclosed to you", never "not blacklisted". An uncleared
    // caller must not be shown a clearance the server never gave.
    const withheld = row()
    expect('is_blacklisted' in withheld).toBe(false)

    board.data = boardData([withheld])

    const wrapper = await mountOperational(InHouse)

    expect(bodyText(wrapper)).not.toContain('Blacklisted')
    expect(bodyText(wrapper)).not.toContain('Not blacklisted')
    expect(bodyText(wrapper)).not.toContain('No alerts')
  })

  it('renders no blacklist claim when the key is present and false', async () => {
    board.data = boardData([row({ is_blacklisted: false })])

    const wrapper = await mountOperational(InHouse)

    expect(bodyText(wrapper)).not.toContain('Blacklisted')
  })

  it('never renders a blacklist reason, even when one is smuggled onto the row', async () => {
    const reason = 'Card chargeback, incident 2025-114'
    board.data = boardData([row({ is_blacklisted: true, blacklist_reason: reason })])

    const wrapper = await mountOperational(InHouse)

    expect(wrapper.html()).not.toContain(reason)
    expect(wrapper.html()).not.toContain('chargeback')
  })

  it('chips an unverified identification, and says nothing when it is verified', async () => {
    board.data = boardData([row({ id_verified: false })])

    let wrapper = await mountOperational(InHouse)
    expect(bodyText(wrapper)).toContain('ID not verified')

    board.data = boardData([row({ id_verified: true })])
    wrapper = await mountOperational(InHouse)

    // No column of green ticks: a verified document is the normal case and says
    // nothing an operator has to act on.
    expect(bodyText(wrapper)).not.toContain('ID not verified')
    expect(bodyText(wrapper)).not.toContain('Verified')
  })
})

describe('In-house quick actions', () => {
  it('navigates to checkout', async () => {
    board.data = boardData([row()])
    const router = testRouter()

    const wrapper = await mountOperational(InHouse, { router })
    await buttonsWithText(wrapper, 'Check out')[0].trigger('click')
    await flush(wrapper)

    expect(router.currentRoute.value.name).toBe('Checkout')
    expect(router.currentRoute.value.params.stay).toBe('HPMS-STAY-2026-00001')
  })

  it('navigates to the folio when the stay has one', async () => {
    board.data = boardData([row()])
    const router = testRouter()

    const wrapper = await mountOperational(InHouse, { router })
    await buttonsWithText(wrapper, 'Open folio')[0].trigger('click')
    await flush(wrapper)

    expect(router.currentRoute.value.name).toBe('Folio')
    expect(router.currentRoute.value.params.id).toBe('HPMS-FOL-2026-00001')
  })

  it('withholds the folio action when the stay has none', async () => {
    board.data = boardData([row({ folio: null })])

    const wrapper = await mountOperational(InHouse)

    expect(buttonsWithText(wrapper, 'Open folio')).toHaveLength(0)
  })

  it('offers the stay operations in the drawer to a stay-operation role', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    const panel = await openDrawer(wrapper)

    expect(panel.textContent).toContain('Move room')
    expect(panel.textContent).toContain('Extend stay')
    expect(panel.textContent).toContain('Shorten stay')
    expect(panel.textContent).toContain('Create request')
    expect(panel.textContent).toContain('Guest profile')
    expect(panel.textContent).toContain('Open stay')
  })

  it('hides the stay operations from a role the server would refuse', async () => {
    stubSession(['Room Attendant'])
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    const panel = await openDrawer(wrapper)

    expect(panel.textContent).not.toContain('Move room')
    expect(panel.textContent).not.toContain('Extend stay')
    expect(panel.textContent).not.toContain('Shorten stay')
    expect(panel.textContent).not.toContain('Create request')
    // Navigation is not gated: the destination authorises its own request.
    expect(panel.textContent).toContain('Open stay')
  })

  it('closes the drawer before a dialog opens, so no dialog is stacked in it', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    await openDrawer(wrapper)

    expect(document.body.querySelector('[data-drawer-panel]')).not.toBeNull()

    await clickInDrawer(wrapper, 'Move room')

    expect(document.body.querySelector('[data-drawer-panel]')).toBeNull()
  })

  it('closes the drawer before the request dialog opens too', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Create request')

    expect(document.body.querySelector('[data-drawer-panel]')).toBeNull()
    expect(document.body.textContent).toContain('Raise a request or complaint')
  })

  it('prefills the request with the row room, guest, reservation and stay', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    await openDrawer(wrapper)
    await clickInDrawer(wrapper, 'Create request')

    const values = Array.from(document.body.querySelectorAll('input')).map((input) => input.value)

    // `room` is a Link to Hotel Room, so it is the docname the server can resolve,
    // not the door number the desk reads.
    expect(values).toContain('DOHA01-101')
    expect(values).toContain('HPMS-GUEST-0001')
    expect(values).toContain('HPMS-RES-2026-00001')
    expect(values).toContain('HPMS-STAY-2026-00001')
  })

  it('shows the stay summary and its balance in the drawer', async () => {
    board.data = boardData([row({ balance: 250 })])

    const wrapper = await mountOperational(InHouse)
    const panel = await openDrawer(wrapper)

    expect(panel.textContent).toContain('Layla Haddad')
    expect(panel.textContent).toContain('HPMS-STAY-2026-00001')
    expect(panel.textContent).toContain('HPMS-RES-2026-00001')
    expect(panel.textContent).toContain('Deluxe')
    expect(panel.textContent).toContain('250.00')
    expect(panel.textContent).toContain('Balance due')
  })
})
