/**
 * Front Desk Command Center.
 *
 * The screen's contract is geography plus honesty. Geography: the same panels in
 * the same places whatever the time of day, because a receptionist reads this
 * forty times a shift. Honesty: every figure is the server's, the business date
 * is the server's operational day rather than the browser clock, and a payload
 * that arrives without one of 16.7.1's new fields degrades to a zero instead of
 * throwing a whole dashboard away.
 *
 * The demoted business intelligence is tested as firmly as the queues. The
 * booking-source donut and the revenue sparkline must be gone — nothing at a
 * counter changes because 38% of tonight came from an OTA — while ADR and RevPAR
 * must survive as one dated footer line, because in this release a duty manager
 * has nowhere else to read them.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { flush, mountOperational, OPERATIONAL_ROUTES, resetStores, stubProperty, stubSession } from '../helpers'

const { dashboard, arrivals, departures, inHouse, rack, audit } = vi.hoisted(() => {
  const resource = () => ({ data: null, loading: false, error: null, fetch: vi.fn() })

  return {
    dashboard: resource(),
    arrivals: resource(),
    departures: resource(),
    inHouse: resource(),
    rack: resource(),
    audit: resource(),
  }
})

vi.mock('@/resources/frontOffice', async (importOriginal) => {
  const actual = await importOriginal()

  return {
    ...actual,
    dashboardResource: () => dashboard,
    arrivalsBoardResource: () => arrivals,
    departuresBoardResource: () => departures,
  }
})

vi.mock('@/resources/stays', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, inHouseResource: () => inHouse }
})

vi.mock('@/resources/rooms', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, roomRackResource: () => rack }
})

vi.mock('@/resources/nightAudit', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, nightAuditCurrentResource: () => audit }
})

const { default: Dashboard } = await import('@/pages/Dashboard.vue')

const Blank = { template: '<div />' }

/**
 * The routes this screen links to on top of the shared operational set.
 *
 * Named exactly as `src/router/index.js` names them, which is what makes a broken
 * `:to` fail here instead of at a counter.
 */
const COMMAND_CENTER_ROUTES = [
  { path: '/reservations', name: 'Reservations', component: Blank },
  { path: '/reservations/new', name: 'ReservationNew', component: Blank },
  { path: '/availability', name: 'Availability', component: Blank },
  { path: '/calendar', name: 'Calendar', component: Blank },
  { path: '/guest-services', name: 'GuestServices', component: Blank },
  { path: '/housekeeping', name: 'Housekeeping', component: Blank },
  { path: '/maintenance', name: 'Maintenance', component: Blank },
  { path: '/night-audit', name: 'NightAudit', component: Blank },
  { path: '/kitchen', name: 'Kitchen', component: Blank },
]

function dashboardRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [...OPERATIONAL_ROUTES, ...COMMAND_CENTER_ROUTES],
  })
}

function mountDashboard(options = {}) {
  return mountOperational(Dashboard, { router: dashboardRouter(), ...options })
}

/** The `front_office.dashboard` payload, as the service assembles it. */
function dashboardData(overrides = {}) {
  return {
    property: 'DOHA01',
    property_name: 'Doha Grand',
    // Not today: the property is still working the day its last audit closed.
    business_date: '2026-08-08',
    currency: 'QAR',
    rooms: {
      total: 60,
      active: 60,
      occupied: 42,
      vacant: 18,
      vacant_clean: 11,
      vacant_dirty: 4,
      // Every vacant room housekeeping has not released — the 4 Dirty ones plus
      // 3 mid-clean or awaiting inspection. This, not `vacant_dirty`, is what the
      // attention queue lists, so it is what the counter has to agree with.
      vacant_not_ready: 7,
      ready: 50,
      dirty: 9,
      out_of_order: 1,
      out_of_service: 0,
      under_maintenance: 0,
      blocked: 2,
      assignable: 7,
    },
    front_office: {
      arrivals_expected: 14,
      arrivals_pending: 9,
      arrivals_completed: 5,
      arrivals_unassigned: 3,
      departures_expected: 12,
      departures_pending: 6,
      departures_completed: 6,
      in_house_rooms: 42,
      in_house_guests: 71,
      due_out: 5,
    },
    revenue: {
      currency: 'QAR',
      business_date: '2026-08-08',
      room_revenue_posted: 0,
      payments_received: 8450,
      outstanding_balance: 12750,
    },
    performance: {
      available: true,
      name: 'HPMS-NA-2026-00007',
      business_date: '2026-08-07',
      occupancy_percentage: 68.3,
      adr: 420.5,
      revpar: 287.2,
      room_revenue: 25230,
      total_revenue: 31000,
      payments_received: 24000,
      currency: 'QAR',
    },
    workload: { housekeeping_open: 12, maintenance_open: 3, guest_requests_open: 5 },
    ...overrides,
  }
}

function arrivalRow(overrides = {}) {
  return {
    key: 'RES-LINE-1',
    reservation: 'HPMS-RES-2026-00001',
    guest_name: 'Layla Haddad',
    vip_status: '',
    room_type: 'DLX',
    room_type_name: 'Deluxe',
    assigned_room: null,
    room_number: null,
    room_ready: false,
    room_assignable: false,
    occupancy_status: null,
    housekeeping_status: null,
    maintenance_status: null,
    inventory_status: null,
    is_checked_in: false,
    stay: null,
    ...overrides,
  }
}

function departureRow(overrides = {}) {
  return {
    key: 'HPMS-STAY-2026-00001',
    stay: 'HPMS-STAY-2026-00001',
    guest_name: 'Omar Nasser',
    vip_status: '',
    room_number: '204',
    balance: 320,
    currency: 'QAR',
    related_folios: 0,
    folio: 'HPMS-FOL-2026-00001',
    is_checked_out: false,
    can_check_out: true,
    ...overrides,
  }
}

/** One in-house row, as the enriched `stays.in_house` payload sends it. */
function inHouseRow(overrides = {}) {
  return {
    key: 'HPMS-STAY-2026-00010',
    name: 'HPMS-STAY-2026-00010',
    stay: 'HPMS-STAY-2026-00010',
    stay_status: 'In House',
    guest: 'HPMS-GUEST-0010',
    guest_name: 'Fatima Al Kuwari',
    vip_status: '',
    room: 'DOHA01-301',
    room_number: '301',
    room_type: 'DLX',
    room_type_name: 'Deluxe',
    departure_date: '2026-08-11',
    balance: 500,
    currency: 'QAR',
    related_folios: 0,
    alert_count: 0,
    alert_severity: '',
    folio: 'HPMS-FOL-2026-00010',
    can_check_out: true,
    blockers: [],
    ...overrides,
  }
}

function rackRoom(overrides = {}) {
  return {
    name: 'DOHA01-101',
    room_number: '101',
    room_type: 'DLX',
    room_type_name: 'Deluxe',
    floor: 'F1',
    floor_name: 'First',
    floor_level: 1,
    is_active: 1,
    occupancy_status: 'Vacant',
    housekeeping_status: 'Clean',
    maintenance_status: 'Operational',
    inventory_status: 'Available',
    ready: true,
    assignable: true,
    ...overrides,
  }
}

/** One card or section of the page, found by its own heading. */
function panel(wrapper, heading) {
  return wrapper
    .findAll('section')
    .find((section) => section.findAll('h2').some((title) => title.text() === heading))
}

function buttonsWithText(wrapper, text) {
  return wrapper.findAll('button').filter((button) => button.text().trim() === text)
}

/** Every link on the page whose visible text is exactly this. */
function linksWithText(wrapper, text) {
  return wrapper.findAll('a').filter((anchor) => anchor.text().trim() === text)
}

function reset(resource) {
  resource.data = null
  resource.loading = false
  resource.error = null
  resource.fetch.mockClear()
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Agent'])

  for (const resource of [dashboard, arrivals, departures, inHouse, rack, audit]) reset(resource)

  dashboard.data = dashboardData()
  arrivals.data = { property: 'DOHA01', business_date: '2026-08-08', currency: 'QAR', rows: [], summary: {} }
  departures.data = { property: 'DOHA01', business_date: '2026-08-08', currency: 'QAR', rows: [], summary: {} }
  inHouse.data = { property: 'DOHA01', business_date: '2026-08-08', currency: 'QAR', stays: [], summary: {} }
  rack.data = { property: 'DOHA01', room_types: [], summary: {} }
})

describe('Command Center header', () => {
  it('leads with the property and the real date at that property', async () => {
    vi.setSystemTime(new Date('2026-08-15T09:00:00Z'))

    const wrapper = await mountDashboard()

    expect(wrapper.text()).toContain('Doha Grand')
    // The civil date, with its weekday: the question this header answers is
    // "what day is it", which the rail's business date cannot.
    expect(wrapper.text()).toContain('Saturday')
    expect(wrapper.text()).toContain('15 Aug 2026')
  })

  it('reads the calendar date in the property zone, not the runtime zone', async () => {
    // 22:30 UTC on the 15th is already the 16th in Doha. A bench in London must
    // not make a Doha desk read yesterday.
    vi.setSystemTime(new Date('2026-08-15T22:30:00Z'))

    const wrapper = await mountDashboard()

    expect(wrapper.text()).toContain('16 Aug 2026')
  })

  it('no longer repeats the business date the sidebar already shows', async () => {
    // The rail is the one authoritative place for the operating day, and it now
    // carries the lag warning beside it. Two copies of one figure is not
    // emphasis - it is a screen with nothing to say about the real date.
    vi.setSystemTime(new Date('2026-08-15T09:00:00Z'))
    dashboard.data = dashboardData({ business_date: '2026-08-08' })

    const wrapper = await mountDashboard()

    // Scoped to the header: "business date" still appears in body copy, where it
    // is describing what a board is filtered on. What must not come back is the
    // header repeating the figure the rail already owns.
    const header = wrapper.findComponent({ name: 'PageHeader' })

    expect(header.exists()).toBe(true)
    expect(header.text()).not.toContain('business date')
    expect(header.text()).not.toContain('08 Aug 2026')
    expect(header.text()).toContain('15 Aug 2026')
  })

  it('never takes an operational figure from the clock', async () => {
    // The header's date is civil and decorative. Every fetch this screen makes
    // still goes out on the property alone, never on a browser-derived date.
    vi.setSystemTime(new Date('2026-08-15T09:00:00Z'))

    await mountDashboard()

    for (const [params] of dashboard.fetch.mock.calls) {
      expect(Object.keys(params)).toEqual(['property'])
    }
  })

  it('fetches every board on the property alone, and refetches when it changes', async () => {
    await mountDashboard()

    for (const resource of [dashboard, arrivals, departures, inHouse, rack]) {
      expect(resource.fetch).toHaveBeenCalledWith({ property: 'DOHA01' })

      for (const [params] of resource.fetch.mock.calls) {
        expect(Object.keys(params)).toEqual(['property'])
      }
    }

    dashboard.fetch.mockClear()
    stubProperty({ name: 'DOHA02', property_name: 'Doha Corniche' })
    await flush()

    expect(dashboard.fetch).toHaveBeenCalledWith({ property: 'DOHA02' })
  })
})

describe('Command Center search', () => {
  it('leads with the header and puts the search box under it', async () => {
    const wrapper = await mountDashboard()

    const html = wrapper.html()
    const header = html.indexOf('Doha Grand')
    const search = html.indexOf('data-global-search')

    expect(header).toBeGreaterThan(-1)
    expect(search).toBeGreaterThan(-1)
    expect(search).toBeGreaterThan(header)
  })

  it('mounts exactly one search box, as the shell did', async () => {
    const wrapper = await mountDashboard()

    expect(wrapper.findAll('[data-global-search]')).toHaveLength(1)
  })

  it('offers the search before the boards have answered', async () => {
    // A desk looking for a guest should not have to wait for a rack.
    dashboard.loading = true
    dashboard.data = null

    const wrapper = await mountDashboard()

    expect(wrapper.find('[data-global-search]').exists()).toBe(true)
  })
})

describe('Command Center work counters', () => {
  it('counts the work in rooms, including the unassigned arrivals', async () => {
    const wrapper = await mountDashboard()
    const counters = panel(wrapper, 'Front desk today')

    expect(counters.text()).toContain('Pending check-ins')
    expect(counters.text()).toContain('9')
    expect(counters.text()).toContain('Unassigned arrivals')
    expect(counters.text()).toContain('3')
    expect(counters.text()).toContain('Pending check-outs')
    expect(counters.text()).toContain('Due out')
    expect(counters.text()).toContain('Rooms not ready')
    expect(counters.text()).toContain('Available now')
    expect(counters.text()).toContain('In-house rooms')
    // The sentence that says what "unassigned" costs: a line with no room chosen
    // cannot be made ready, keyed or checked in.
    expect(wrapper.text()).toContain('Arriving on this business date with no room assigned yet.')
  })

  it('drops the totals and the head count: a total is a report, not work', async () => {
    const wrapper = await mountDashboard()
    const counters = panel(wrapper, 'Front desk today')

    expect(counters.text()).not.toContain('Arrivals today')
    expect(counters.text()).not.toContain('Departures today')
    expect(counters.text()).not.toContain('In-house guests')
  })

  it('counts rooms that are not ready on vacancy, never on "dirty" alone', async () => {
    // `dirty` is 9 and includes occupied stayovers, which nobody is waiting on;
    // `vacant_not_ready` is 7 and means "nobody can be walked into it".
    const wrapper = await mountDashboard()
    // The tile itself, not the grid around it: every counter is a link to the
    // board behind it, so the anchor is the tile.
    const tile = panel(wrapper, 'Front desk today')
      .findAll('a')
      .find((node) => node.text().includes('Rooms not ready'))

    expect(tile.text()).toContain('7')
    expect(tile.text()).not.toContain('9')
  })

  it('falls back to the strict dirty count on an older payload', async () => {
    // A bench mid-upgrade has no `vacant_not_ready`. Showing the Dirty subset is
    // an understatement; showing zero would say the house is ready when it is not.
    const payload = dashboardData()
    delete payload.rooms.vacant_not_ready

    dashboard.data = payload

    const wrapper = await mountDashboard()
    const tile = panel(wrapper, 'Front desk today')
      .findAll('a')
      .find((node) => node.text().includes('Rooms not ready'))

    expect(tile.text()).toContain('4')
  })

  it('degrades to zero when a bench is still serving the older payload', async () => {
    const payload = dashboardData()
    delete payload.front_office.arrivals_unassigned

    dashboard.data = payload

    const wrapper = await mountDashboard()
    const tile = panel(wrapper, 'Front desk today')
      .findAll('a')
      .find((node) => node.text().includes('Unassigned arrivals'))

    expect(tile.text()).toContain('0')
  })

  it('links each counter to the board behind it', async () => {
    const wrapper = await mountDashboard()
    const hrefs = panel(wrapper, 'Front desk today')
      .findAll('a')
      .map((anchor) => anchor.attributes('href'))

    expect(hrefs).toContain('/arrivals')
    expect(hrefs).toContain('/departures')
    expect(hrefs).toContain('/in-house')
    expect(hrefs).toContain('/rooms')
  })
})

describe('Command Center queues', () => {
  it('renders the arrivals queue', async () => {
    arrivals.data = { ...arrivals.data, rows: [arrivalRow(), arrivalRow({ key: 'RES-LINE-2', guest_name: 'Yusuf Rahman' })] }

    const wrapper = await mountDashboard()
    const queue = panel(wrapper, "Today's arrivals")

    expect(queue.text()).toContain('Layla Haddad')
    expect(queue.text()).toContain('Yusuf Rahman')
    expect(queue.findAll('tbody tr')).toHaveLength(2)
  })

  it('shows six arrival rows rather than five', async () => {
    arrivals.data = {
      ...arrivals.data,
      rows: Array.from({ length: 8 }, (unused, index) =>
        arrivalRow({ key: `RES-LINE-${index}`, guest_name: `Guest ${index}` }),
      ),
    }

    const wrapper = await mountDashboard()

    expect(panel(wrapper, "Today's arrivals").findAll('tbody tr')).toHaveLength(6)
  })

  it('renders the departures queue, six deep', async () => {
    departures.data = {
      ...departures.data,
      rows: Array.from({ length: 8 }, (unused, index) =>
        departureRow({ key: `STAY-${index}`, stay: `STAY-${index}`, guest_name: `Leaver ${index}`, room_number: `30${index}` }),
      ),
    }

    const wrapper = await mountDashboard()
    const queue = panel(wrapper, "Today's departures")

    expect(queue.text()).toContain('Leaver 0')
    expect(queue.findAll('tbody tr')).toHaveLength(6)
  })

  it('renders the room attention queue with a leading reason', async () => {
    rack.data = {
      property: 'DOHA01',
      room_types: [
        {
          name: 'DLX',
          room_type_name: 'Deluxe',
          rooms: [
            rackRoom({ name: 'DOHA01-101', room_number: '101', housekeeping_status: 'Dirty' }),
            rackRoom({ name: 'DOHA01-102', room_number: '102', maintenance_status: 'Out of Order' }),
            rackRoom({ name: 'DOHA01-103', room_number: '103', inventory_status: 'Stop Sell' }),
          ],
        },
      ],
      summary: {},
    }

    const wrapper = await mountDashboard()
    const queue = panel(wrapper, 'Rooms needing attention')

    expect(queue.findAll('tbody tr')).toHaveLength(3)
    expect(queue.findAll('[data-attention-reason]').map((badge) => badge.text())).toEqual([
      'Dirty',
      'Out of Order',
      'Stop Sell',
    ])
  })

  it('ranks an arrival that cannot take its guest above every other room', async () => {
    arrivals.data = {
      ...arrivals.data,
      rows: [arrivalRow({ assigned_room: 'DOHA01-901', room_number: '901', housekeeping_status: 'Dirty' })],
    }
    rack.data = {
      property: 'DOHA01',
      room_types: [
        { name: 'DLX', rooms: [rackRoom({ name: 'DOHA01-101', room_number: '101', housekeeping_status: 'Dirty' })] },
      ],
      summary: {},
    }

    const wrapper = await mountDashboard()
    const rows = panel(wrapper, 'Rooms needing attention').findAll('[data-attention-room]')

    expect(rows.map((node) => node.text())).toEqual(['901', '101'])
  })

  it('shows only the in-house guests who still owe money, most owed first', async () => {
    inHouse.data = {
      ...inHouse.data,
      stays: [
        inHouseRow({ key: 'S1', stay: 'S1', guest_name: 'Small Balance', room_number: '101', balance: 120 }),
        inHouseRow({ key: 'S2', stay: 'S2', guest_name: 'Settled Guest', room_number: '102', balance: 0 }),
        inHouseRow({ key: 'S3', stay: 'S3', guest_name: 'Big Balance', room_number: '103', balance: 4300 }),
        inHouseRow({ key: 'S4', stay: 'S4', guest_name: 'Credit Guest', room_number: '104', balance: -250 }),
      ],
    }

    const wrapper = await mountDashboard()
    const queue = panel(wrapper, 'In house now')
    const guests = queue.findAll('tbody tr').map((tr) => tr.findAll('td')[1].text())

    expect(guests).toEqual(['Big Balance', 'Small Balance'])
    expect(queue.text()).not.toContain('Settled Guest')
    // A credit is the hotel owing the guest. It is settled at checkout by the
    // folio screen, not collected at the counter, so it is not in a collection
    // queue.
    expect(queue.text()).not.toContain('Credit Guest')
  })

  it('restates the in-house and due-out counters beside that list', async () => {
    const wrapper = await mountDashboard()
    const queue = panel(wrapper, 'In house now')

    expect(queue.text()).toContain('42')
    expect(queue.text()).toContain('5')
  })

  it('collapses to one honest line when nobody owes anything', async () => {
    inHouse.data = { ...inHouse.data, stays: [inHouseRow({ balance: 0 })] }

    const wrapper = await mountDashboard()
    const queue = panel(wrapper, 'In house now')

    // Not "no guests are in house": there are forty-two of them, and saying
    // otherwise over an occupied house would be a lie the desk could act on.
    expect(queue.text()).toContain('No in-house guests match this filter.')
    expect(queue.text()).not.toContain('No guests are in house right now.')
  })

  it('says the house is empty when it actually is', async () => {
    const wrapper = await mountDashboard()

    expect(panel(wrapper, 'In house now').text()).toContain('No guests are in house right now.')
  })

  it('survives an in-house row that arrived without a balance', async () => {
    const row = inHouseRow()
    delete row.balance
    delete row.currency

    inHouse.data = { ...inHouse.data, stays: [row] }

    const wrapper = await mountDashboard()

    expect(panel(wrapper, 'In house now').text()).toContain('No in-house guests match this filter.')
  })

  it('sends each queue to the board that stays the authority', async () => {
    const wrapper = await mountDashboard()
    const hrefs = linksWithText(wrapper, 'View all').map((anchor) => anchor.attributes('href'))

    expect(hrefs).toContain('/arrivals')
    expect(hrefs).toContain('/departures')
    expect(hrefs).toContain('/in-house')
    expect(hrefs).toContain('/rooms')
  })
})

describe('Command Center house state, work and money', () => {
  it('restates the live house in rooms, with what can be sold now', async () => {
    const wrapper = await mountDashboard()

    expect(wrapper.text()).toContain('Occupied now')
    expect(wrapper.text()).toContain('70.0%')
    expect(wrapper.text()).toContain('42 / 60 rooms')
    expect(wrapper.text()).toContain('Available now')
    expect(wrapper.text()).toContain('7')
  })

  it('keeps the open work counters exactly as they were', async () => {
    const wrapper = await mountDashboard()
    const work = panel(wrapper, 'Open work')

    expect(work.text()).toContain('Housekeeping tasks')
    expect(work.text()).toContain('12')
    expect(work.text()).toContain('Maintenance tickets')
    expect(work.text()).toContain('Guest requests')
  })

  it('shows the money as one row: taken, owed, and posted with its caveat', async () => {
    const wrapper = await mountDashboard()
    const money = panel(wrapper, 'Recorded today')

    expect(money.text()).toContain('Payments received')
    expect(money.text()).toMatch(/8[,.]450/)
    expect(money.text()).toContain('Outstanding balance')
    expect(money.text()).toMatch(/12[,.]750/)
    // Posted room revenue keeps the sentence that explains its zero.
    expect(money.text()).toContain('Room charges are posted by the Night Audit')
  })

  it('keeps the rack below the queues', async () => {
    rack.data = {
      property: 'DOHA01',
      room_types: [{ name: 'DLX', rooms: [rackRoom()] }],
      summary: {},
    }

    const wrapper = await mountDashboard()
    const html = wrapper.html()

    expect(html.indexOf("Today's arrivals")).toBeLessThan(html.indexOf('Room status board'))
  })
})

/**
 * Guest Folio disclosure (16.7.5-R1B).
 *
 * The server omits the whole `revenue` block for a caller who may not read Guest
 * Folio — ten roles hold Stay read without it, and every one of them lands here,
 * because this screen's navigation entry carries no role filter.
 *
 * The screen must hide the strip rather than render the absence. `?? 0` would
 * print "Payments received 0.00 / Outstanding balance 0.00", which reads as a
 * quiet day on which everyone has paid: a claim about the hotel's money that this
 * caller was specifically not told, and one that may be flatly untrue.
 */
describe('Command Center financial disclosure', () => {
  /** A dashboard payload with the folio-derived block genuinely absent. */
  function undisclosed() {
    const payload = dashboardData()
    delete payload.revenue

    return payload
  }

  it('hides the financial section when the server did not disclose it', async () => {
    dashboard.data = undisclosed()

    const wrapper = await mountDashboard()

    expect(panel(wrapper, 'Recorded today')).toBeUndefined()
  })

  it('renders no zero in place of a withheld figure', async () => {
    dashboard.data = undisclosed()

    const wrapper = await mountDashboard()
    const text = wrapper.text()

    // Asserted on the figures rather than on the labels. "Outstanding balance"
    // is also the In-House panel's column heading, and that panel is gated
    // separately and correctly — it takes its rows from `stays.in_house`, which
    // passes them through `_folio_position`. Asserting on the label would have
    // pinned an unrelated panel's wording into this test.
    expect(text).not.toMatch(/8[,.]450/)
    expect(text).not.toMatch(/12[,.]750/)

    // The caveat sentence goes with the strip it explains.
    expect(text).not.toContain('Room charges are posted by the Night Audit')

    // And no confident zero appeared where a withheld figure used to be.
    expect(panel(wrapper, 'Recorded today')).toBeUndefined()
  })

  it('still renders the operational queues and counters', async () => {
    dashboard.data = undisclosed()

    const wrapper = await mountDashboard()
    const text = wrapper.text()

    // The screen is this role's landing page: redaction, never an outage.
    expect(text).toContain("Today's arrivals")
    expect(text).toContain('In house')
    expect(panel(wrapper, 'Room status board')).toBeDefined()
    expect(text).toContain('Doha Grand')
  })

  it('keeps the audited performance line, which Night Audit owns and not the folio', async () => {
    dashboard.data = undisclosed()

    const wrapper = await mountDashboard()

    // ADR and RevPAR come from the Night Audit that computed them, whose readers
    // are not Guest Folio's. Hiding them with the money would blind a Revenue
    // Manager on a boundary that does not exist.
    expect(wrapper.text()).toMatch(/420[,.]5/)
  })

  it('shows the strip again for a caller who was told the money', async () => {
    dashboard.data = dashboardData()

    const wrapper = await mountDashboard()

    expect(panel(wrapper, 'Recorded today')).toBeDefined()
    expect(wrapper.text()).toMatch(/12[,.]750/)
  })
})

describe('Command Center quick actions', () => {
  it('offers the walk-in and the guest search alongside the existing actions', async () => {
    const wrapper = await mountDashboard()
    const actions = panel(wrapper, 'Quick actions')
    const hrefs = actions.findAll('a').map((anchor) => anchor.attributes('href'))

    expect(actions.text()).toContain('Walk-in')
    expect(hrefs).toContain('/walk-in')
    expect(actions.text()).toContain('Find a guest')
    expect(hrefs).toContain('/guests')

    expect(actions.text()).toContain('New reservation')
    expect(actions.text()).toContain('Find a reservation')
    expect(actions.text()).toContain('Room rack')
    expect(hrefs).toContain('/rooms')
  })

  it('withholds the actions the server would refuse anyway', async () => {
    stubSession(['Room Attendant'])

    const wrapper = await mountDashboard()
    const actions = panel(wrapper, 'Quick actions')

    expect(actions.text()).not.toContain('New reservation')
    expect(actions.text()).not.toContain('Walk-in')
    expect(actions.text()).not.toContain('Find a guest')
    // What is left is still a usable screen rather than an empty card.
    expect(actions.text()).toContain('Room rack')
  })
})

describe('Command Center night audit', () => {
  it('shows the audit card, and asks for it, only for a role that may read it', async () => {
    stubSession(['Night Auditor'])
    audit.data = { audit: { name: 'HPMS-NA-2026-00008', business_date: '2026-08-08', audit_status: 'Open' }, blocking_count: 0 }

    const wrapper = await mountDashboard()

    expect(wrapper.text()).toContain('Night audit status')
    expect(audit.fetch).toHaveBeenCalledWith({ property: 'DOHA01' })
  })

  it('leaves it out for a front desk agent, and never asks for it', async () => {
    const wrapper = await mountDashboard()

    expect(wrapper.text()).not.toContain('Night audit status')
    expect(audit.fetch).not.toHaveBeenCalled()
  })
})

describe('Command Center demoted business intelligence', () => {
  it('renders no booking-source donut and no revenue sparkline', async () => {
    arrivals.data = {
      ...arrivals.data,
      rows: [arrivalRow({ booking_source: 'Booking.com' }), arrivalRow({ key: 'RES-LINE-2', booking_source: 'Direct' })],
    }

    const wrapper = await mountDashboard()

    expect(wrapper.text()).not.toContain('Booking sources')
    expect(wrapper.text()).not.toContain('Rooms arriving today')
    expect(wrapper.html()).not.toContain('Room revenue over the last closed business dates')
  })

  it('keeps ADR and RevPAR as one dated footer line', async () => {
    const wrapper = await mountDashboard()

    // Still the last *closed* audit, still named and dated: today's ADR does not
    // exist until tonight's audit closes.
    expect(wrapper.text()).toContain('Audited 07 Aug 2026')
    expect(wrapper.text()).toContain('ADR')
    expect(wrapper.text()).toMatch(/420\.50/)
    expect(wrapper.text()).toContain('RevPAR')
    expect(wrapper.text()).toMatch(/287\.20/)
    expect(wrapper.text()).toContain('68.3%')
    expect(wrapper.text()).toContain("Today's figures are not final until tonight's audit closes.")
  })

  it('says so plainly when no audit has ever closed', async () => {
    dashboard.data = dashboardData({ performance: { available: false } })

    const wrapper = await mountDashboard()

    expect(wrapper.text()).toContain('No Night Audit has been closed for this property yet')
    expect(wrapper.text()).not.toContain('Audited 07 Aug 2026')
  })
})

describe('Command Center loading, failure and a quiet property', () => {
  it('reports loading before the first response', async () => {
    dashboard.data = null
    dashboard.loading = true

    const wrapper = await mountDashboard()

    expect(wrapper.text()).toContain('Loading')
  })

  it('reports a failure in place, with a retry that refetches', async () => {
    dashboard.data = null
    dashboard.error = { status: 500, message: 'Internal Server Error' }

    const wrapper = await mountDashboard()

    expect(wrapper.text()).toContain('Something went wrong')

    dashboard.fetch.mockClear()
    await buttonsWithText(wrapper, 'Retry')[0].trigger('click')

    expect(dashboard.fetch).toHaveBeenCalledWith({ property: 'DOHA01' })
  })

  it('reads as a quiet property, not a broken screen, with no rooms and no arrivals', async () => {
    dashboard.data = dashboardData({
      rooms: { total: 0, active: 0, occupied: 0, vacant: 0, vacant_clean: 0, vacant_dirty: 0, assignable: 0 },
      front_office: {},
      revenue: { currency: 'QAR', room_revenue_posted: 0, payments_received: 0, outstanding_balance: 0 },
      performance: { available: false },
      workload: {},
    })

    const wrapper = await mountDashboard()

    expect(wrapper.text()).toContain('Doha Grand')
    expect(wrapper.text()).toContain('0.0%')
    expect(wrapper.text()).toContain('No arrivals for this business date.')
    expect(wrapper.text()).toContain('No departures for this business date.')
    expect(wrapper.text()).toContain('No room needs attention right now.')
    expect(wrapper.text()).toContain('No guests are in house right now.')
    expect(wrapper.text()).toContain('No rooms have been set up for this property yet.')
    expect(wrapper.text()).not.toContain('NaN')
    expect(wrapper.text()).not.toContain('undefined')
  })
})
