/**
 * Services & Operations (16.7.4).
 *
 * Three things are defended here.
 *
 * **Navigation is honest.** The Services group carries only entries that have a
 * real screen behind them. Laundry has no model at all — an unused folio charge
 * type and an unused warehouse purpose, referenced by no code — and Transport is
 * a Guest Request *category* with no pickup time, vehicle or destination field.
 * Neither gets a nav entry, because a link to a screen that cannot exist is the
 * placeholder the brief forbids.
 *
 * **The kitchen board discloses nothing it is not owed.** Every kitchen role
 * holds `Room Service Order.read` and none holds Guest or Guest Folio read at
 * any permlevel, so the server omits the guest and the folio for them. The page
 * must drop the column rather than draw a dash — a dash reads as "no guest on
 * this order", which for a room service order is never true.
 *
 * **Task creation exists and never decides the property.** The property comes
 * from the active context and the server proves the room belongs to it; a
 * property field on the form would be a permission decision taken in Vue.
 */
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { flush, mountOperational, resetStores, stubProperty, stubSession } from '../helpers'
import { session } from '@/stores/session'

const { board, createTask } = vi.hoisted(() => ({
  board: { data: null, loading: false, error: null, fetch: vi.fn() },
  createTask: { data: null, loading: false, error: null, submit: vi.fn() },
}))

vi.mock('@/resources/kitchen', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, orderBoardResource: () => board }
})

vi.mock('@/resources/housekeeping', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, createHousekeepingTaskResource: () => createTask }
})

const { visibleNavigationGroups, navigation } = await import('@/router/navigation')
const { default: Kitchen } = await import('@/pages/Kitchen.vue')
const { default: CreateHousekeepingTaskDialog } = await import(
  '@/components/CreateHousekeepingTaskDialog.vue'
)

/** One order, as the board sends it to a caller entitled to everything. */
function order(overrides = {}) {
  return {
    name: 'HPMS-RSO-2026-00001',
    order_status: 'Placed',
    order_type: 'Room Service',
    room: 'DOHA01-402',
    stay: 'HPMS-STY-00001',
    guest: 'HPMS-GST-00001',
    guest_name: 'Layla Haddad',
    folio: 'HPMS-FOL-00001',
    folio_charge_row: null,
    ordered_on: '2026-08-08 19:20:00',
    total_amount: 120,
    currency: 'QAR',
    line_count: 2,
    item_count: 3,
    ...overrides,
  }
}

function boardPayload(orders) {
  return {
    property: 'DOHA01',
    orders,
    summary: { open: orders.length, placed: orders.length, preparing: 0, ready: 0, open_value: 120 },
  }
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Kitchen User'])

  board.data = boardPayload([order()])
  board.loading = false
  board.error = null
  board.fetch = vi.fn()

  createTask.data = null
  createTask.loading = false
  createTask.error = null
  createTask.submit = vi.fn().mockResolvedValue({})
})

describe('Services navigation', () => {
  it('groups guest requests and kitchen under Services', () => {
    const services = navigation.filter((item) => item.group === 'services').map((i) => i.key)

    expect(services).toContain('guest_services')
    expect(services).toContain('kitchen')
  })

  it('leaves the room boards under Rooms', () => {
    const rooms = navigation.filter((item) => item.group === 'rooms').map((i) => i.key)

    expect(rooms).toEqual(expect.arrayContaining(['rooms', 'housekeeping', 'maintenance']))
  })

  it('adds no Laundry entry, because there is no laundry model', () => {
    expect(navigation.map((i) => i.key)).not.toContain('laundry')
  })

  it('adds no Transport entry, because transport is a request category', () => {
    expect(navigation.map((i) => i.key)).not.toContain('transport')
  })

  it('adds no Minibar entry, because minibar is an order type under Kitchen', () => {
    expect(navigation.map((i) => i.key)).not.toContain('minibar')
  })

  it('points every navigation entry at a route or an external href', () => {
    for (const item of navigation) {
      expect(Boolean(item.to) || Boolean(item.href)).toBe(true)
    }
  })

  it('shows the Services group to a kitchen user', () => {
    stubSession(['Kitchen User'])

    expect(visibleNavigationGroups(session).map((g) => g.key)).toContain('services')
  })

  it('hides the Services group from a role with neither screen', () => {
    stubSession(['Room Attendant'])

    expect(visibleNavigationGroups(session).map((g) => g.key)).not.toContain('services')
  })
})

describe('Kitchen board disclosure', () => {
  it('renders the guest column for a caller the server told about the guest', async () => {
    stubSession(['Front Office Manager'])

    const wrapper = await mountOperational(Kitchen)
    await flush(wrapper)

    expect(wrapper.text()).toContain('Layla Haddad')
  })

  it('drops the guest column entirely when the server withheld it', async () => {
    // The server omits the keys; it does not blank them.
    board.data = boardPayload([
      order({ guest: undefined, guest_name: undefined, folio: undefined }),
    ])
    delete board.data.orders[0].guest
    delete board.data.orders[0].guest_name
    delete board.data.orders[0].folio

    const wrapper = await mountOperational(Kitchen)
    await flush(wrapper)

    expect(wrapper.text()).not.toContain('Layla Haddad')
  })

  it('still shows the room, which is what a kitchen fulfils from', async () => {
    delete board.data.orders[0].guest_name
    delete board.data.orders[0].folio

    const wrapper = await mountOperational(Kitchen)
    await flush(wrapper)

    expect(wrapper.text()).toContain('DOHA01-402')
  })

  it('never renders a folio identifier it was not given', async () => {
    delete board.data.orders[0].folio
    delete board.data.orders[0].folio_charge_row

    const wrapper = await mountOperational(Kitchen)
    await flush(wrapper)

    expect(wrapper.text()).not.toContain('HPMS-FOL-00001')
  })
})

describe('Housekeeping task creation', () => {
  async function openDialog() {
    const wrapper = mount(CreateHousekeepingTaskDialog, {
      props: { modelValue: true },
      attachTo: document.body,
    })

    await flush(wrapper)

    return wrapper
  }

  /**
   * The dialog teleports to `body`, so the wrapper's own subtree is empty.
   * Asserting on `wrapper.text()` here would pass every `not.toContain` for the
   * wrong reason.
   */
  function dialogText() {
    return document.body.textContent || ''
  }

  it('offers no property field: the server owns that decision', async () => {
    await openDialog()

    // The premise first: the dialog really did render, so the absence below is
    // a decision and not an empty subtree.
    expect(dialogText()).toContain('Raise a cleaning task')
    expect(dialogText()).not.toContain('Property')
  })

  it('sends the active property with the room, and never lets the form pick one', async () => {
    const wrapper = await openDialog()

    wrapper.vm.form.room = 'DOHA01-402'
    await flush(wrapper)

    await wrapper.vm.submit()

    expect(createTask.submit).toHaveBeenCalledWith(
      expect.objectContaining({ property: 'DOHA01', room: 'DOHA01-402' }),
    )
  })

  it('refuses to submit without a room', async () => {
    const wrapper = await openDialog()

    await wrapper.vm.submit()

    expect(createTask.submit).not.toHaveBeenCalled()
  })

  it('surfaces the server refusal in the server’s own words', async () => {
    createTask.error = {
      status: 403,
      exc_type: 'PermissionDeniedError',
      messages: ['Room DOHA02-101 belongs to another property.'],
    }

    await openDialog()

    expect(dialogText()).toContain('belongs to another property')
  })
})
