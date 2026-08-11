/**
 * Rooms & rates — the tab a multi-room booking is run from.
 *
 * These tests defend two things above everything else.
 *
 * **That the screen does not lie about a room.** Four of the payload's fields are
 * dangerously close to a fact they are not: `room_rate` is an average including every
 * supplement and equals no actual night; `assigned_room` is a docname and therefore a
 * room *code*, not the number on the door; `Reservation Room.reservation_status` is a
 * copy of the header status stamped identically onto every line, so it cannot say
 * which room is in house; and once a Stay exists the guest is in `stay_room`, which a
 * room move leaves different from `assigned_room`. Each has a test here, and each
 * test would pass just as well against a wrong implementation but for the negative
 * assertion beside it — that the code is not shown as a number, that no readiness
 * word appears for a payload that disclosed no room, that no badge at all appears for
 * a line with no stay.
 *
 * **That the lines are independent.** A three-room booking is three operational
 * rooms, and the test that matters most is the one that edits the middle one: the
 * payload must name that line, the other two cards' controls must be untouched, and
 * no verb anywhere may act on more than the line it sits on.
 *
 * Nothing leaves the process: every resource is a stub keyed by the API method the
 * component asks for, so a wrong method name fails here rather than in production.
 */
import { Badge } from 'frappe-ui'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'

import { flush, mountOperational, resetStores, stubProperty, stubSession, useArabic } from '../helpers'

/**
 * One stub per whitelisted method the tab and its dialog reach for. Keyed by method
 * name, so `apiResource('reservations.add_room_lines')` — a typo — would hand the
 * component the fallback and fail loudly instead of silently passing.
 */
const { resources, fallback } = vi.hoisted(() => {
  const make = () => ({ data: null, loading: false, error: null, fetch: vi.fn(), submit: vi.fn() })

  return {
    resources: {
      'reservations.change_line_interval': make(),
      'reservations.add_room_line': make(),
      'reservations.remove_room_line': make(),
      'reservations.change_line_room_type': make(),
      'reservations.set_line_rate_plan': make(),
      'availability.search': make(),
      'rates.applicable_rate_plans': make(),
    },
    fallback: make(),
  }
})

vi.mock('@/resources', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, apiResource: (method) => resources[method] || fallback }
})

const changeInterval = resources['reservations.change_line_interval']
const addRoom = resources['reservations.add_room_line']
const removeRoom = resources['reservations.remove_room_line']
const changeRoomType = resources['reservations.change_line_room_type']
const setRatePlan = resources['reservations.set_line_rate_plan']
const search = resources['availability.search']
const ratePlans = resources['rates.applicable_rate_plans']

const { default: RoomsRatesTab } = await import('@/components/reservation/RoomsRatesTab.vue')

const RES = 'HPMS-RES-2026-00001'

/** The reservation's own fields, as `get_workspace` sends them. */
function reservation(overrides = {}) {
  return {
    name: RES,
    property: 'DOHA01',
    reservation_status: 'Confirmed',
    // The header interval is min(arrival)/max(departure) across the lines.
    arrival_date: '2026-08-08',
    departure_date: '2026-08-12',
    nights: 4,
    total_rooms: 2,
    total_amount: 2000,
    currency: 'QAR',
    ...overrides,
  }
}

/**
 * One room line, shaped as `_room_lines` sends it.
 *
 * The Hotel Room and Stay enrichments are deliberately *absent* by default: that is
 * what a caller without those DocTypes receives, and it is the case a screen is most
 * likely to render a claim it was never given.
 */
function line(overrides = {}) {
  return {
    name: 'RES-LINE-1',
    idx: 1,
    room_type: 'DLX',
    rooms: 1,
    arrival_date: '2026-08-08',
    departure_date: '2026-08-10',
    nights: 2,
    adults: 2,
    children: 1,
    extra_beds: 0,
    rate_plan: 'BAR',
    assigned_room: null,
    // total/nights including every supplement: equal to neither night below.
    room_rate: 340,
    total_amount: 680,
    reservation_status: 'Confirmed',
    special_requests: '',
    rate_lines: [
      { rate_date: '2026-08-08', rate: 300, extra_adult_charge: 20, extra_child_charge: 0, extra_bed_charge: 0, net_rate: 320 },
      { rate_date: '2026-08-09', rate: 340, extra_adult_charge: 0, extra_child_charge: 15, extra_bed_charge: 5, net_rate: 360 },
    ],
    ...overrides,
  }
}

/** `editability` for a booking that holds inventory — the common live case. */
function holding(overrides = {}) {
  return {
    status: 'Confirmed',
    is_draft_like: false,
    is_holding: true,
    is_terminal: false,
    may_edit_details: true,
    may_change_dates: true,
    may_add_or_remove_rooms: false,
    may_change_room_type: false,
    may_change_rate_plan: false,
    may_assign_room: true,
    may_edit_deposit: false,
    ...overrides,
  }
}

/** `editability` while the booking is still a working draft. */
function draft(overrides = {}) {
  return holding({
    status: 'Tentative',
    is_draft_like: true,
    is_holding: false,
    may_add_or_remove_rooms: true,
    may_change_room_type: true,
    may_change_rate_plan: true,
    ...overrides,
  })
}

function mountTab({ rooms = [line()], editability = holding(), booking = reservation() } = {}) {
  return mountOperational(RoomsRatesTab, {
    props: { reservation: booking, rooms, editability },
  })
}

/** The line cards, and only those: the breakdown table renders `li` of its own. */
function cards(wrapper) {
  const list = wrapper.find('ul[aria-label="Rooms and rates"]')

  return list.exists() ? list.findAll(':scope > li') : []
}

function cardFor(wrapper, label) {
  return cards(wrapper).find((card) => card.text().includes(label))
}

function buttonsWithText(root, text) {
  return root.findAll('button').filter((button) => button.text().trim() === text)
}

/** A dialog is teleported out of the tree; reka-ui stamps its title on the overlay. */
function dialog(title) {
  return document.querySelector(`[data-dialog="${title}"]`)
}

function dialogText(title) {
  return dialog(title)?.textContent || ''
}

function dialogButton(title, text) {
  return Array.from(dialog(title).querySelectorAll('button')).find(
    (button) => button.textContent.trim() === text,
  )
}

/** A button inside a dialog whose label runs over two lines (a room type card). */
function dialogButtonContaining(title, text) {
  return Array.from(dialog(title).querySelectorAll('button')).find((button) =>
    button.textContent.includes(text),
  )
}

function dialogInputs(title, selector = 'input') {
  return Array.from(dialog(title).querySelectorAll(selector))
}

async function setValue(element, value) {
  element.value = value
  element.dispatchEvent(new Event('input', { bubbles: true }))
  await flush()
}

/** The availability service's answer, keyed by room type as it sends it. */
function availability(types) {
  return { room_types: types }
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Manager'])

  for (const resource of [...Object.values(resources), fallback]) {
    resource.data = null
    resource.loading = false
    resource.error = null
    resource.fetch.mockClear()
    resource.submit.mockReset()
    resource.submit.mockResolvedValue({})
  }
})

describe('Rooms & rates lines', () => {
  it('renders one card per room line, each with its own interval, nights and money', async () => {
    const wrapper = await mountTab({
      rooms: [
        line({ room_type_name: 'Executive King' }),
        line({
          name: 'RES-LINE-2',
          idx: 2,
          arrival_date: '2026-08-09',
          departure_date: '2026-08-12',
          nights: 3,
          adults: 1,
          children: 0,
          rate_plan: 'CORP',
          room_rate: 400,
          total_amount: 1200,
        }),
      ],
    })

    expect(cards(wrapper)).toHaveLength(2)

    const first = cardFor(wrapper, 'Room 1').text()

    expect(first).toContain('Executive King')
    expect(first).toContain('08 Aug 2026')
    expect(first).toContain('10 Aug 2026')
    expect(first).toContain('2 adult(s), 1 child(ren)')
    expect(first).toContain('BAR')
    expect(first).toContain('Average nightly rate')
    expect(first).toMatch(/340\.00/)
    expect(first).toContain('Total per room')
    expect(first).toMatch(/680\.00/)

    // The second line's own facts, which are not the first's and not the header's.
    const second = cardFor(wrapper, 'Room 2').text()

    expect(second).toContain('12 Aug 2026')
    expect(second).toContain('1 adult(s), 0 child(ren)')
    expect(second).toContain('CORP')
    expect(second).toMatch(/1,200\.00/)
    // The header span (08 Aug – 12 Aug, 4 nights) is nowhere on a card.
    expect(first).not.toContain('12 Aug 2026')
  })

  it('labels the per-night figure as an average and never as "the rate"', async () => {
    const wrapper = await mountTab()
    const labels = cardFor(wrapper, 'Room 1')
      .findAll('dt')
      .map((label) => label.text())

    // `room_rate` is total/nights *with* every supplement, so on this line — 320 and
    // 360 — it equals neither night. Called an average, or it is a quotable lie.
    expect(labels).toContain('Average nightly rate')
    expect(labels).not.toContain('Rate')
  })

  it('shows no rate comparison, and no second rate of any kind', async () => {
    const wrapper = await mountTab()

    // Two amounts per collapsed card: the average and the line total. A third would
    // be a "booked versus today" figure, which for a corporate booking is the
    // contract discount — `get_rate_breakdown` never consults the negotiated rate.
    expect(cardFor(wrapper, 'Room 1').findAllComponents(MoneyDisplay)).toHaveLength(2)

    const text = wrapper.text()

    expect(text).not.toContain('Current rate')
    expect(text).not.toContain('Today')
  })

  it('renders every amount through MoneyDisplay, never as concatenated text', async () => {
    const wrapper = await mountTab()
    const amounts = wrapper.findAllComponents(MoneyDisplay)

    expect(amounts.length).toBeGreaterThan(0)
    // The currency travels with the amount rather than being glued to it, and the
    // figure is formatted by Intl inside the component.
    expect(amounts.every((money) => money.props('currency') === 'QAR')).toBe(true)
    expect(amounts.some((money) => /680\.00/.test(money.text()))).toBe(true)
  })

  it('states the server reason when nothing on the booking may change', async () => {
    const wrapper = await mountTab({
      editability: holding({
        status: 'Cancelled',
        is_holding: false,
        is_terminal: true,
        may_change_dates: false,
        may_assign_room: false,
      }),
    })

    expect(wrapper.text()).toContain('This cannot be changed while the booking is Cancelled.')
    expect(wrapper.findAll('[role="group"]')).toHaveLength(0)
  })
})

describe('Rooms & rates nightly breakdown', () => {
  it('opens the real per-night figures beside the average', async () => {
    const wrapper = await mountTab()
    const card = cardFor(wrapper, 'Room 1')
    const toggle = buttonsWithText(card, 'Nightly breakdown')[0]

    expect(toggle.attributes('aria-expanded')).toBe('false')
    // Collapsed: the average is on screen and the nights behind it are not.
    expect(card.text()).not.toMatch(/300\.00/)
    expect(card.text()).not.toMatch(/360\.00/)

    await toggle.trigger('click')
    await flush(wrapper)

    const opened = cardFor(wrapper, 'Room 1')

    expect(buttonsWithText(opened, 'Nightly breakdown')[0].attributes('aria-expanded')).toBe('true')

    const text = opened.text()

    expect(text).toContain('08 Aug 2026')
    expect(text).toContain('09 Aug 2026')
    // The stored rate and the night's own net, so the average above is readable.
    expect(text).toMatch(/300\.00/)
    expect(text).toMatch(/320\.00/)
    expect(text).toMatch(/360\.00/)
  })

  it('names the three supplements that make the average an average', async () => {
    const wrapper = await mountTab()

    await buttonsWithText(cardFor(wrapper, 'Room 1'), 'Nightly breakdown')[0].trigger('click')
    await flush(wrapper)

    const opened = cardFor(wrapper, 'Room 1')
    const headers = opened.findAll('thead th').map((header) => header.text())

    expect(headers).toEqual(['Night', 'Rate', 'Extra adult', 'Extra child', 'Extra bed', 'Amount'])

    // The gap between 300 and 320 is stated rather than merely not denied.
    const text = opened.text()

    expect(text).toMatch(/20\.00/)
    expect(text).toMatch(/15\.00/)
    expect(text).toMatch(/5\.00/)
    // Six columns, each through MoneyDisplay for the five that are money.
    expect(opened.findAll('tbody tr')).toHaveLength(2)
  })

  it('names the room type and the rate plan when disclosed, and shows the code when not', async () => {
    // Three separate clearances — Hotel Room, Room Type, Rate Plan — so a line can
    // arrive with any combination of the names. Presence decides, never truthiness:
    // the line's own `room_type` and `rate_plan` columns are always there, and they
    // are docnames, so they may not stand in for a name that was not disclosed.
    const wrapper = await mountTab({
      rooms: [
        line({ room_type_name: 'Executive King', rate_plan_name: 'Best Available Rate' }),
        line({ name: 'RES-LINE-2', idx: 2 }),
      ],
    })

    const named = cardFor(wrapper, 'Room 1').text()

    expect(named).toContain('Executive King')
    expect(named).toContain('Best Available Rate')
    expect(named).not.toContain('BAR')

    // A caller who may not read Rate Plan still sees the line's own column.
    const coded = cardFor(wrapper, 'Room 2').text()

    expect(coded).toContain('DLX')
    expect(coded).toContain('BAR')
  })

  it('states a line extra-bed count, and says nothing when there is none', async () => {
    const wrapper = await mountTab({
      rooms: [line({ extra_beds: 1 }), line({ name: 'RES-LINE-2', idx: 2, extra_beds: 0 })],
    })

    const first = cardFor(wrapper, 'Room 1')

    expect(first.findAll('dt').map((label) => label.text())).toContain('Extra beds')
    expect(cardFor(wrapper, 'Room 2').findAll('dt').map((label) => label.text())).not.toContain('Extra beds')
  })

  it('expands one line only, never the booking', async () => {
    const wrapper = await mountTab({ rooms: [line(), line({ name: 'RES-LINE-2', idx: 2 })] })

    await buttonsWithText(cardFor(wrapper, 'Room 2'), 'Nightly breakdown')[0].trigger('click')
    await flush(wrapper)

    expect(buttonsWithText(cardFor(wrapper, 'Room 2'), 'Nightly breakdown')[0].attributes('aria-expanded')).toBe(
      'true',
    )
    expect(buttonsWithText(cardFor(wrapper, 'Room 1'), 'Nightly breakdown')[0].attributes('aria-expanded')).toBe(
      'false',
    )
  })
})

describe('Rooms & rates room identity', () => {
  it('shows the door number, and never the docname as a number', async () => {
    const wrapper = await mountTab({
      rooms: [
        line({
          assigned_room: 'DOHA01-405',
          room_number: '405',
          room_ready: true,
          room_assignable: true,
          housekeeping_status: 'Clean',
          occupancy_status: 'Vacant',
        }),
      ],
    })

    const text = cardFor(wrapper, 'Room 1').text()

    expect(text).toContain('405')
    expect(text).toContain('Room ready')
    expect(text).toContain('Clean')
    expect(text).toContain('Vacant')
    // `assigned_room` is a Hotel Room name — a code — and is not what an agent says.
    expect(wrapper.html()).not.toContain('DOHA01-405')
  })

  it('shows the code plainly, with no readiness claim, when Hotel Room was withheld', async () => {
    const wrapper = await mountTab({ rooms: [line({ assigned_room: 'DOHA01-405' })] })
    const card = cardFor(wrapper, 'Room 1')

    expect(card.text()).toContain('DOHA01-405')
    expect(card.findAll('dt').map((label) => label.text())).toContain('Assigned room')

    // The enrichment keys are absent for an uncleared caller. "Ready" and "not ready"
    // are both claims this payload never made.
    for (const claim of ['Room ready', 'Room not ready', 'Not ready', 'Clean', 'Vacant']) {
      expect(card.text()).not.toContain(claim)
    }
  })

  it('says a line has no room rather than inventing one', async () => {
    const wrapper = await mountTab()

    expect(cardFor(wrapper, 'Room 1').text()).toContain('Not assigned')
  })

  it('prefers the stay room once a line has a stay', async () => {
    // `stays.change_room` moves the Stay and the folio and never writes back to the
    // reservation line, so after a move `assigned_room` names the room the guest left
    // — and `room_number`, which is looked up from it, names that room's door.
    const wrapper = await mountTab({
      rooms: [
        line({
          assigned_room: 'DOHA01-405',
          room_number: '405',
          room_ready: true,
          stay: 'HPMS-STAY-0001',
          stay_status: 'In House',
          stay_room: 'DOHA01-712',
        }),
      ],
    })

    const card = cardFor(wrapper, 'Room 1')

    expect(card.text()).toContain('DOHA01-712')
    expect(wrapper.html()).not.toContain('405')
    // Housekeeping's opinion of a room the guest is not in is not a fact about them.
    expect(card.text()).not.toContain('Room ready')
  })

  it('uses the door number when the stay is still in the room that was assigned', async () => {
    const wrapper = await mountTab({
      rooms: [
        line({
          assigned_room: 'DOHA01-405',
          room_number: '405',
          stay: 'HPMS-STAY-0001',
          stay_status: 'In House',
          stay_room: 'DOHA01-405',
        }),
      ],
    })

    expect(cardFor(wrapper, 'Room 1').text()).toContain('405')
    expect(wrapper.html()).not.toContain('DOHA01-405')
  })
})

describe('Rooms & rates per-line status', () => {
  it('badges the stay status when the line has a stay', async () => {
    const wrapper = await mountTab({
      rooms: [line({ stay: 'HPMS-STAY-0001', stay_status: 'In House', stay_room: 'DOHA01-405' })],
    })

    const badges = wrapper.findAllComponents(Badge)

    expect(badges).toHaveLength(1)
    expect(badges[0].text()).toBe('In House')
  })

  it('renders no badge at all for a line with no stay', async () => {
    const wrapper = await mountTab()

    // Not "no stay", not a dash and not the header's status: a line whose stay was
    // not disclosed — or does not exist — has no per-line state to state.
    expect(wrapper.findAllComponents(Badge)).toHaveLength(0)
  })

  it('never surfaces the room line reservation_status', async () => {
    // `_propagate_status` stamps it from the header onto every line, so it is
    // identical on all three of these and cannot say which room is in house.
    const wrapper = await mountTab({
      booking: reservation({ reservation_status: 'Checked In' }),
      rooms: [
        line({ reservation_status: 'Checked In' }),
        line({ name: 'RES-LINE-2', idx: 2, reservation_status: 'Checked In' }),
        line({ name: 'RES-LINE-3', idx: 3, reservation_status: 'Checked In' }),
      ],
    })

    expect(wrapper.text()).not.toContain('Checked In')
    expect(wrapper.findAllComponents(Badge)).toHaveLength(0)
  })
})

describe('Rooms & rates assignment', () => {
  it('offers assignment per line, and emits the line it was pressed on', async () => {
    const wrapper = await mountTab({
      rooms: [line({ assigned_room: 'DOHA01-405', room_number: '405' }), line({ name: 'RES-LINE-2', idx: 2 })],
    })

    // The line that holds a room is offered a change; the one that does not, a choice.
    expect(buttonsWithText(cardFor(wrapper, 'Room 1'), 'Change room')).toHaveLength(1)
    expect(buttonsWithText(cardFor(wrapper, 'Room 2'), 'Assign a room')).toHaveLength(1)

    await buttonsWithText(cardFor(wrapper, 'Room 2'), 'Assign a room')[0].trigger('click')

    // The shell owns the hardened dialog; this tab hands it one line and no other.
    expect(wrapper.emitted('assign')).toHaveLength(1)
    expect(wrapper.emitted('assign')[0][0].name).toBe('RES-LINE-2')
  })

  it('takes assignment from editability, not from the status', async () => {
    const wrapper = await mountTab({ editability: holding({ may_assign_room: false }) })

    expect(buttonsWithText(wrapper, 'Assign a room')).toHaveLength(0)
  })

  it('never offers assignment on a line with a live stay, and links to the stay instead', async () => {
    const wrapper = await mountTab({
      rooms: [line({ stay: 'HPMS-STAY-0001', stay_status: 'In House', stay_room: 'DOHA01-405' })],
    })

    // The guest is in a room. The verb is Change Room on the Stay, which moves the
    // folio too, and it is not reimplemented here.
    expect(buttonsWithText(wrapper, 'Assign a room')).toHaveLength(0)
    expect(buttonsWithText(wrapper, 'Change room')).toHaveLength(0)
    expect(buttonsWithText(wrapper, 'Change dates')).toHaveLength(0)

    const link = wrapper.findAll('a').find((anchor) => anchor.text() === 'Open stay')

    expect(link.attributes('href')).toBe('/stays/HPMS-STAY-0001')
  })

  it('hides assignment from a role the server would refuse', async () => {
    stubSession(['Room Attendant'])

    const wrapper = await mountTab()

    expect(buttonsWithText(wrapper, 'Assign a room')).toHaveLength(0)
  })
})

describe('Rooms & rates line editing gates', () => {
  it('offers add, remove and room type only while the booking is a working draft', async () => {
    const held = await mountTab({ rooms: [line(), line({ name: 'RES-LINE-2', idx: 2 })] })

    // Past draft the controller answers "cancel and rebook", so the buttons are not
    // shown and then failed — they are not shown.
    expect(buttonsWithText(held, 'Add a room')).toHaveLength(0)
    expect(buttonsWithText(held, 'Remove room')).toHaveLength(0)
    expect(buttonsWithText(held, 'Change room type')).toHaveLength(0)

    const editable = await mountTab({
      rooms: [line(), line({ name: 'RES-LINE-2', idx: 2 })],
      editability: draft(),
    })

    expect(buttonsWithText(editable, 'Add a room')).toHaveLength(1)
    expect(buttonsWithText(editable, 'Remove room')).toHaveLength(2)
    expect(buttonsWithText(editable, 'Change room type')).toHaveLength(2)
  })

  it('never offers to remove the last room line', async () => {
    const wrapper = await mountTab({ rooms: [line()], editability: draft() })

    // The service keeps a reservation to at least one room and says to cancel it
    // instead, so there is nothing to press.
    expect(buttonsWithText(wrapper, 'Remove room')).toHaveLength(0)
    expect(buttonsWithText(wrapper, 'Add a room')).toHaveLength(1)
  })

  it('offers the rate plan picker only with its own flag', async () => {
    const wrapper = await mountTab({ editability: draft() })
    const card = cardFor(wrapper, 'Room 1')

    expect(card.findAll('dt').map((label) => label.text())).toContain('Rate plan')
    expect(card.text()).toContain('BAR')
    expect(buttonsWithText(wrapper, 'Change rate plan')).toHaveLength(1)

    // Same booking, same role: only the server's flag moved.
    const held = await mountTab({ editability: draft({ may_change_rate_plan: false }) })

    expect(buttonsWithText(held, 'Change rate plan')).toHaveLength(0)
    expect(cardFor(held, 'Room 1').text()).toContain('BAR')
  })
})

describe('Rooms & rates rate plan', () => {
  const TITLE = 'Change rate plan'

  beforeEach(() => {
    ratePlans.data = [
      { name: 'BAR', rate_plan_name: 'Best Available Rate', rate_type: 'Public', display_order: 1 },
      { name: 'CORP-QE', rate_plan_name: 'Qatar Energy Contract', rate_type: 'Negotiated', display_order: 2 },
    ]
  })

  async function openPlan(wrapper, label) {
    await buttonsWithText(cardFor(wrapper, label), 'Change rate plan')[0].trigger('click')
    await flush(wrapper)
  }

  it('asks for the plans that price this room type on this line arrival', async () => {
    const wrapper = await mountTab({
      rooms: [line(), line({ name: 'RES-LINE-2', idx: 2, room_type: 'STE', arrival_date: '2026-09-01' })],
      editability: draft(),
    })

    await openPlan(wrapper, 'Room 2')

    // The night being priced, not today and not the business date: a plan that
    // expires before this stay begins must not be offered for it.
    expect(ratePlans.fetch).toHaveBeenCalledWith({
      property: 'DOHA01',
      room_type: 'STE',
      on_date: '2026-09-01',
    })

    const text = dialogText(TITLE)

    expect(text).toContain('Only plans the server will price for this room type on these dates are offered.')
    // The plan's name, never its docname.
    expect(text).toContain('Best Available Rate')
    expect(text).toContain('Qatar Energy Contract')
    expect(text).not.toContain('CORP-QE')
  })

  it('sends the chosen plan for that line, and no rate of any kind', async () => {
    const wrapper = await mountTab({
      rooms: [line(), line({ name: 'RES-LINE-2', idx: 2 })],
      editability: draft(),
    })

    await openPlan(wrapper, 'Room 2')

    dialogButtonContaining(TITLE, 'Qatar Energy Contract').click()
    await flush(wrapper)

    dialogButton(TITLE, TITLE).click()
    await flush(wrapper)

    expect(setRatePlan.submit).toHaveBeenCalledTimes(1)
    expect(setRatePlan.submit).toHaveBeenCalledWith({
      reservation: RES,
      room_line: 'RES-LINE-2',
      rate_plan: 'CORP-QE',
    })
    // The plan is the whole of the choice; `price_reservation` decides what it costs.
    expect(Object.keys(setRatePlan.submit.mock.calls[0][0])).toEqual([
      'reservation',
      'room_line',
      'rate_plan',
    ])
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('shows no money in the picker at all', async () => {
    const wrapper = await mountTab({ editability: draft() })

    await openPlan(wrapper, 'Room 1')

    // A plan is not a price. Nothing here may look like the rate it will produce.
    expect(dialogText(TITLE)).not.toMatch(/\d+\.\d{2}/)
    expect(dialogText(TITLE)).not.toContain('QAR')
  })

  it('says no plan covers the line rather than offering an empty picker', async () => {
    ratePlans.data = []

    const wrapper = await mountTab({ editability: draft() })

    await openPlan(wrapper, 'Room 1')

    expect(dialogText(TITLE)).toContain('No rate plan covers this room type on these dates.')
    expect(dialogButton(TITLE, TITLE).disabled).toBe(true)
  })

  it('surfaces a refusal verbatim', async () => {
    setRatePlan.submit.mockRejectedValue({
      status: 417,
      exc_type: 'InvalidStateTransitionError',
      message: 'Rate plan cannot be changed while reservation HPMS-RES-2026-00001 is Confirmed.',
    })

    const wrapper = await mountTab({ editability: draft() })

    await openPlan(wrapper, 'Room 1')

    dialogButtonContaining(TITLE, 'Best Available Rate').click()
    await flush(wrapper)

    dialogButton(TITLE, TITLE).click()
    await flush(wrapper)

    expect(dialogText(TITLE)).toContain('cannot be changed while reservation')
    expect(wrapper.emitted('changed')).toBeUndefined()
  })

  it('is not offered on a line with a live stay', async () => {
    const wrapper = await mountTab({
      rooms: [line({ stay: 'HPMS-STAY-0001', stay_status: 'In House', stay_room: 'DOHA01-405' })],
      editability: draft(),
    })

    expect(buttonsWithText(wrapper, 'Change rate plan')).toHaveLength(0)
  })
})

describe('Rooms & rates date change', () => {
  const TITLE = "Change this room's dates"

  async function openDates(wrapper, label) {
    await buttonsWithText(cardFor(wrapper, label), 'Change dates')[0].trigger('click')
    await flush(wrapper)
  }

  it('opens for one line, naming it and its current interval', async () => {
    const wrapper = await mountTab({
      rooms: [
        line(),
        line({ name: 'RES-LINE-2', idx: 2, arrival_date: '2026-08-09', departure_date: '2026-08-12', nights: 3 }),
      ],
    })

    await openDates(wrapper, 'Room 2')

    const text = dialogText(TITLE)

    expect(text).toContain('Room 2')
    expect(text).toContain('09 Aug 2026')
    expect(text).toContain('12 Aug 2026')
    expect(text).toContain('3 night(s)')
    // Availability is asked for what is actually being added, and the quoted rate is
    // carried across rather than recomputed.
    expect(text).toContain('Availability is checked for the added nights only')
    expect(text).toContain('The rate the guest was quoted is kept')
  })

  it('makes the equal-nights constraint plain for a booking that holds inventory', async () => {
    const wrapper = await mountTab()

    await openDates(wrapper, 'Room 1')

    // A held booking may be shifted, not lengthened: there is no repricing for the
    // nights that would be added, and a preserved price over a different interval
    // would misstate the money. The constraint, its count and the remedy are all on
    // screen beside the inputs — and none of it is enforced here.
    expect(dialogText(TITLE)).toContain('it must keep 2 night(s)')
    expect(dialogText(TITLE)).toContain('Cancel and rebook to change the length')
    expect(dialogText(TITLE)).toContain('The rate the guest was quoted is kept')
  })

  it('states the constraint only for a booking that holds inventory', async () => {
    // A draft is re-priced on the next save, so it keeps full freedom and must not be
    // told it is fixed to its current length.
    const wrapper = await mountTab({ editability: draft() })

    await openDates(wrapper, 'Room 1')

    expect(dialogText(TITLE)).not.toContain('it must keep')
    expect(dialogText(TITLE)).not.toContain('A held booking is not repriced')
  })

  it('sends only the line it was opened on', async () => {
    const wrapper = await mountTab({
      rooms: [
        line(),
        line({ name: 'RES-LINE-2', idx: 2, arrival_date: '2026-08-09', departure_date: '2026-08-12', nights: 3 }),
        line({ name: 'RES-LINE-3', idx: 3 }),
      ],
    })

    await openDates(wrapper, 'Room 2')

    const [arrival, departure] = dialogInputs(TITLE, 'input[type="date"]')

    // The inputs opened on the line's own interval, not the booking's span.
    expect(arrival.value).toBe('2026-08-09')
    expect(departure.value).toBe('2026-08-12')

    await setValue(arrival, '2026-08-11')
    await setValue(departure, '2026-08-14')

    dialogButton(TITLE, 'Change dates').click()
    await flush(wrapper)

    expect(changeInterval.submit).toHaveBeenCalledTimes(1)
    expect(changeInterval.submit).toHaveBeenCalledWith({
      reservation: RES,
      room_line: 'RES-LINE-2',
      arrival: '2026-08-11',
      departure: '2026-08-14',
    })
    // A successful line operation re-reads the whole aggregate; the tab patches
    // nothing itself.
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('carries a reason when one is given', async () => {
    const wrapper = await mountTab()

    await openDates(wrapper, 'Room 1')
    await setValue(dialogInputs(TITLE, 'textarea')[0], 'Guest flight moved')

    dialogButton(TITLE, 'Change dates').click()
    await flush(wrapper)

    expect(changeInterval.submit.mock.calls[0][0].reason).toBe('Guest flight moved')
  })

  it('surfaces the server refusal verbatim and keeps the dialog open', async () => {
    const refusal =
      'Reservation HPMS-RES-2026-00001 is Confirmed, so room line RES-LINE-1 can be moved but not ' +
      're-priced: 2 night(s) cannot become 3. Cancel and rebook before arrival, or extend or shorten ' +
      'the stay once the guest is in the room.'

    changeInterval.submit.mockRejectedValue({
      status: 409,
      exc_type: 'InvalidStateTransitionError',
      message: refusal,
    })

    const wrapper = await mountTab()

    await openDates(wrapper, 'Room 1')
    await setValue(dialogInputs(TITLE, 'input[type="date"]')[1], '2026-08-11')

    dialogButton(TITLE, 'Change dates').click()
    await flush(wrapper)

    // The service's own sentence: it names the booking, the status, the night count
    // and the remedy. Nothing here validates the rule, so nothing here can garble it.
    expect(dialogText(TITLE)).toContain('2 night(s) cannot become 3')
    expect(dialogText(TITLE)).toContain('Cancel and rebook before arrival')
    expect(dialog(TITLE)).not.toBeNull()
    expect(wrapper.emitted('changed')).toBeUndefined()
  })
})

describe('Rooms & rates room type change', () => {
  const TITLE = 'Change room type'

  beforeEach(() => {
    search.data = availability({
      DLX: { room_type_name: 'Deluxe', min_available: 4, bookable: true },
      STE: { room_type_name: 'Suite', min_available: 2, bookable: true },
      VIL: { room_type_name: 'Villa', min_available: 0, bookable: false },
    })
  })

  it('asks availability for that line interval and party, and excludes its own type', async () => {
    const wrapper = await mountTab({ editability: draft() })

    await buttonsWithText(cardFor(wrapper, 'Room 1'), 'Change room type')[0].trigger('click')
    await flush(wrapper)

    expect(search.fetch).toHaveBeenCalledWith({
      property: 'DOHA01',
      arrival: '2026-08-08',
      departure: '2026-08-10',
      adults: 2,
      children: 1,
    })

    const text = dialogText(TITLE)

    expect(text).toContain('Suite')
    expect(text).toContain('2 available all nights')
    // The server's own verdict, kept beside the type rather than hiding it.
    expect(text).toContain('Villa')
    expect(text).toContain('Not bookable for these dates.')
    // Its current type: the service refuses "already a Deluxe".
    expect(text).not.toContain('Deluxe')
  })

  it('warns that the change releases the room assigned to the line', async () => {
    const wrapper = await mountTab({
      rooms: [
        line({ assigned_room: 'DOHA01-405', room_number: '405' }),
        line({ name: 'RES-LINE-2', idx: 2 }),
      ],
      editability: draft(),
    })

    await buttonsWithText(cardFor(wrapper, 'Room 1'), 'Change room type')[0].trigger('click')
    await flush(wrapper)

    // A physical room belongs to one type, so the service drops the assignment. An
    // agent who pre-assigned a VIP's usual room must not lose it silently.
    expect(dialogText(TITLE)).toContain(
      'Changing the room type releases the room assigned to this line. Choose a room again afterwards.',
    )

    // Nothing is released on a line that holds no room, so nothing is claimed.
    dialogButton(TITLE, 'Cancel').click()
    await flush(wrapper)

    await buttonsWithText(cardFor(wrapper, 'Room 2'), 'Change room type')[0].trigger('click')
    await flush(wrapper)

    expect(dialogText(TITLE)).not.toContain('releases the room assigned')
  })

  it('sends the chosen type for that line only', async () => {
    const wrapper = await mountTab({
      rooms: [line(), line({ name: 'RES-LINE-2', idx: 2 })],
      editability: draft(),
    })

    await buttonsWithText(cardFor(wrapper, 'Room 2'), 'Change room type')[0].trigger('click')
    await flush(wrapper)

    dialogButtonContaining(TITLE, 'Suite').click()
    await flush(wrapper)

    dialogButton(TITLE, 'Change room type').click()
    await flush(wrapper)

    expect(changeRoomType.submit).toHaveBeenCalledTimes(1)
    expect(changeRoomType.submit).toHaveBeenCalledWith({
      reservation: RES,
      room_line: 'RES-LINE-2',
      room_type: 'STE',
    })
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('surfaces a refusal verbatim', async () => {
    changeRoomType.submit.mockRejectedValue({
      status: 417,
      exc_type: 'AvailabilityError',
      message: 'Room type STE has no availability for 08 Aug 2026.',
    })

    const wrapper = await mountTab({ editability: draft() })

    await buttonsWithText(cardFor(wrapper, 'Room 1'), 'Change room type')[0].trigger('click')
    await flush(wrapper)

    dialogButtonContaining(TITLE, 'Suite').click()
    await flush(wrapper)

    dialogButton(TITLE, 'Change room type').click()
    await flush(wrapper)

    expect(dialogText(TITLE)).toContain('has no availability for 08 Aug 2026')
    expect(wrapper.emitted('changed')).toBeUndefined()
  })
})

describe('Rooms & rates add and remove', () => {
  it('adds one room, on the booking interval, with no rate of its own', async () => {
    search.data = availability({ STE: { room_type_name: 'Suite', min_available: 2, bookable: true } })

    const wrapper = await mountTab({ editability: draft() })

    await buttonsWithText(wrapper, 'Add a room')[0].trigger('click')
    await flush(wrapper)

    // Defaults are the booking's own dates, as the server sent them. Nothing here
    // derives a date.
    expect(search.fetch).toHaveBeenCalledWith({
      property: 'DOHA01',
      arrival: '2026-08-08',
      departure: '2026-08-12',
      adults: 1,
      children: 0,
    })

    dialogButtonContaining('Add a room', 'Suite').click()
    await flush(wrapper)

    dialogButton('Add a room', 'Add a room').click()
    await flush(wrapper)

    expect(addRoom.submit).toHaveBeenCalledWith({
      reservation: RES,
      room_type: 'STE',
      arrival: '2026-08-08',
      departure: '2026-08-12',
      adults: 1,
      children: 0,
    })
    // No rate and no plan: the rate service prices what is added.
    expect(Object.keys(addRoom.submit.mock.calls[0][0])).not.toContain('room_rate')
    expect(Object.keys(addRoom.submit.mock.calls[0][0])).not.toContain('rate_plan')
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('removes the line it was opened on, after stating what goes with it', async () => {
    const wrapper = await mountTab({
      rooms: [line(), line({ name: 'RES-LINE-2', idx: 2 }), line({ name: 'RES-LINE-3', idx: 3, total_amount: 900 })],
      editability: draft(),
    })

    await buttonsWithText(cardFor(wrapper, 'Room 3'), 'Remove room')[0].trigger('click')
    await flush(wrapper)

    const text = dialogText('Remove room')

    expect(text).toContain('Room 3')
    expect(text).toMatch(/900\.00/)

    dialogButton('Remove room', 'Remove room').click()
    await flush(wrapper)

    expect(removeRoom.submit).toHaveBeenCalledTimes(1)
    expect(removeRoom.submit).toHaveBeenCalledWith({ reservation: RES, room_line: 'RES-LINE-3' })
  })

  it('surfaces a refusal to remove verbatim', async () => {
    removeRoom.submit.mockRejectedValue({
      status: 417,
      exc_type: 'HospitalityPMSError',
      message: 'A reservation must keep at least one room line. Cancel the reservation instead.',
    })

    const wrapper = await mountTab({
      rooms: [line(), line({ name: 'RES-LINE-2', idx: 2 })],
      editability: draft(),
    })

    await buttonsWithText(cardFor(wrapper, 'Room 2'), 'Remove room')[0].trigger('click')
    await flush(wrapper)

    dialogButton('Remove room', 'Remove room').click()
    await flush(wrapper)

    expect(dialogText('Remove room')).toContain('must keep at least one room line')
  })
})

describe('Rooms & rates multi-room independence', () => {
  it('gives every line its own labelled control group', async () => {
    const wrapper = await mountTab({
      rooms: [line(), line({ name: 'RES-LINE-2', idx: 2 }), line({ name: 'RES-LINE-3', idx: 3 })],
      editability: draft(),
    })

    const groups = wrapper.findAll('[role="group"]')

    expect(groups).toHaveLength(3)
    expect(groups.map((group) => group.attributes('aria-label'))).toEqual([
      'Actions for Room 1',
      'Actions for Room 2',
      'Actions for Room 3',
    ])
  })

  it('offers no verb that acts on more than one line', async () => {
    const wrapper = await mountTab({
      rooms: [line(), line({ name: 'RES-LINE-2', idx: 2 }), line({ name: 'RES-LINE-3', idx: 3 })],
      editability: draft(),
    })

    const labels = wrapper.findAll('button').map((button) => button.text().trim())

    // No bulk assignment, and no per-line cancellation: cancelling is a whole-booking
    // transition (`_propagate_status` stamps every line) and lives in the header.
    expect(labels).not.toContain('Assign all')
    expect(labels).not.toContain('Cancel booking')
    expect(labels).not.toContain('Cancel this room')
    // One add button for the booking, one of each verb per line.
    expect(labels.filter((label) => label === 'Add a room')).toHaveLength(1)
    expect(labels.filter((label) => label === 'Change dates')).toHaveLength(3)
  })

  it('editing the middle line of three touches only that line', async () => {
    const wrapper = await mountTab({
      rooms: [
        line(),
        line({ name: 'RES-LINE-2', idx: 2, arrival_date: '2026-08-09', departure_date: '2026-08-12', nights: 3 }),
        line({ name: 'RES-LINE-3', idx: 3 }),
      ],
      editability: draft(),
    })

    await buttonsWithText(cardFor(wrapper, 'Room 2'), 'Change dates')[0].trigger('click')
    await flush(wrapper)

    await setValue(dialogInputs("Change this room's dates", 'input[type="date"]')[0], '2026-08-10')

    dialogButton("Change this room's dates", 'Change dates').click()
    await flush(wrapper)

    expect(changeInterval.submit).toHaveBeenCalledTimes(1)
    expect(changeInterval.submit.mock.calls[0][0].room_line).toBe('RES-LINE-2')

    // The other two lines were not sent anywhere, and nothing else was submitted.
    for (const resource of [addRoom, removeRoom, changeRoomType]) {
      expect(resource.submit).not.toHaveBeenCalled()
    }

    // Their cards still read as they did: the first line's interval is untouched.
    expect(cardFor(wrapper, 'Room 1').text()).toContain('10 Aug 2026')
    expect(cardFor(wrapper, 'Room 3').text()).toContain('08 Aug 2026')
  })
})

describe('Rooms & rates in Arabic', () => {
  it('renders mirrored, with the catalogue Arabic and every key resolved', async () => {
    useArabic()

    const wrapper = await mountTab({ editability: draft() })

    expect(document.documentElement.getAttribute('dir')).toBe('rtl')
    // An unknown key renders as itself, so this catches a key that exists in English
    // and not in Arabic. Physical direction utilities are caught by rtlSource.spec.
    expect(wrapper.text()).not.toContain('page.reservation')
    expect(wrapper.text()).not.toContain('page.walk_in')
    expect(wrapper.text()).not.toContain('page.availability')
    expect(wrapper.text()).toContain('الغرفة 1')
    expect(wrapper.text()).toContain('متوسط السعر الليلي')
  })
})
