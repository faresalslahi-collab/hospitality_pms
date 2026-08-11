/**
 * In-house board regression, after the migration onto OperationalDataTable.
 *
 * The point of this file is as much about what the board must NOT show as what it
 * must. `stays.in_house` returns thirteen fields; a balance, an alert flag and a
 * checkout verdict are not among them, and a board that invented any of the three
 * would be telling the desk something no service ever said.
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

/** One in-house row — exactly the thirteen fields `get_in_house` selects. */
function row(overrides = {}) {
  return {
    name: 'HPMS-STAY-2026-00001',
    guest: 'HPMS-GUEST-0001',
    guest_name: 'Layla Haddad',
    room: 'DOHA01-101',
    room_type: 'DLX',
    arrival_date: '2026-08-06',
    departure_date: '2026-08-10',
    nights: 4,
    adults: 2,
    children: 1,
    stay_status: 'In House',
    folio: 'HPMS-FOL-2026-00001',
    room_rate: 400,
    ...overrides,
  }
}

function boardData(stays, summary = {}) {
  return {
    property: 'DOHA01',
    stays,
    summary: {
      in_house: stays.filter((s) => s.stay_status === 'In House').length,
      due_out: stays.filter((s) => s.stay_status === 'Due Out').length,
      adults: 2,
      children: 1,
      ...summary,
    },
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

describe('In-house board', () => {
  it('renders the rows it was given', async () => {
    board.data = boardData([row(), row({ name: 'S2', room: 'DOHA01-102', guest_name: 'Omar Nasser', stay_status: 'Due Out' })])

    const wrapper = await mountOperational(InHouse)

    expect(wrapper.text()).toContain('Layla Haddad')
    expect(wrapper.text()).toContain('Omar Nasser')
    expect(wrapper.text()).toContain('DOHA01-101')
    expect(wrapper.text()).toContain('In House')
    expect(wrapper.text()).toContain('Due Out')
  })

  it('links the room cell to the stay', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    const link = wrapper.findAll('a').find((a) => a.text() === 'DOHA01-101')

    expect(link.attributes('href')).toBe('/stays/HPMS-STAY-2026-00001')
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
    board.data = boardData([row(), row({ name: 'S2', guest_name: 'Omar Nasser', room: 'DOHA01-102' })])

    const wrapper = await mountOperational(InHouse)
    board.fetch.mockClear()

    await wrapper.find('input').setValue('Omar')
    await flush(wrapper)

    expect(wrapper.text()).toContain('Omar Nasser')
    expect(wrapper.text()).not.toContain('Layla Haddad')
    expect(board.fetch).not.toHaveBeenCalled()
  })
})

describe('In-house shows only what the endpoint sent', () => {
  it('invents no balance', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    const text = wrapper.text()

    expect(text).not.toContain('Balance')
    expect(text).not.toContain('Balance due')
    expect(text).not.toContain('Settled')
    expect(text).not.toContain('Credit')
  })

  it('invents no checkout readiness', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    const text = wrapper.text()

    // The row carries no `can_check_out` and no `blockers`, so any verdict here
    // would be a guess about whether a guest may leave.
    expect(text).not.toContain('Ready to check out')
    expect(text).not.toContain('Blocked')
    expect(text).not.toContain('Checkout blocked')
  })

  it('invents no alert state, in either direction', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    const text = wrapper.text()

    expect(text).not.toContain('Alerts')
    expect(text).not.toContain('No alerts')
    expect(text).not.toContain('Blacklisted')
    expect(text).not.toContain('VIP')
  })

  it('shows the rate in the property currency, which is where it comes from', async () => {
    board.data = boardData([row({ room_rate: 400 })])

    const wrapper = await mountOperational(InHouse)

    expect(wrapper.text()).toMatch(/400\.00/)
    expect(wrapper.text()).toMatch(/QAR/)
  })
})

describe('In-house quick actions', () => {
  it('navigates to checkout', async () => {
    board.data = boardData([row()])
    const router = testRouter()

    const wrapper = await mountOperational(InHouse, { router })
    await buttonsWithText(wrapper, 'Checkout')[0].trigger('click')
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
    await buttonsWithText(wrapper, 'Details')[0].trigger('click')
    await flush(wrapper)

    const panel = document.body.querySelector('[data-drawer-panel]')

    expect(panel.textContent).toContain('Move room')
    expect(panel.textContent).toContain('Extend stay')
    expect(panel.textContent).toContain('Shorten stay')
    expect(panel.textContent).toContain('Guest profile')
    expect(panel.textContent).toContain('Open stay')
  })

  it('hides the stay operations from a role the server would refuse', async () => {
    stubSession(['Room Attendant'])
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    await buttonsWithText(wrapper, 'Details')[0].trigger('click')
    await flush(wrapper)

    const panel = document.body.querySelector('[data-drawer-panel]')

    expect(panel.textContent).not.toContain('Move room')
    expect(panel.textContent).not.toContain('Extend stay')
    expect(panel.textContent).not.toContain('Shorten stay')
    // Navigation is not gated: the destination authorises its own request.
    expect(panel.textContent).toContain('Open stay')
  })

  it('closes the drawer before a dialog opens, so no dialog is stacked in it', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    await buttonsWithText(wrapper, 'Details')[0].trigger('click')
    await flush(wrapper)

    expect(document.body.querySelector('[data-drawer-panel]')).not.toBeNull()

    const move = Array.from(document.body.querySelectorAll('[data-drawer-panel] button')).find(
      (button) => button.textContent.trim() === 'Move room',
    )
    move.click()
    await flush(wrapper)

    expect(document.body.querySelector('[data-drawer-panel]')).toBeNull()
  })

  it('shows the stay summary in the drawer', async () => {
    board.data = boardData([row()])

    const wrapper = await mountOperational(InHouse)
    await buttonsWithText(wrapper, 'Details')[0].trigger('click')
    await flush(wrapper)

    const panel = document.body.querySelector('[data-drawer-panel]')

    expect(panel.textContent).toContain('Layla Haddad')
    expect(panel.textContent).toContain('HPMS-STAY-2026-00001')
    expect(panel.textContent).toContain('DLX')
  })
})
