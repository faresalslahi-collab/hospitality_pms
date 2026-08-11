/**
 * GlobalSearch — the one box that finds the record the desk is talking about.
 *
 * Everything asserted here is behaviour a screenshot cannot show: that typing a
 * name is one request and not six, that a slow answer to an abandoned query
 * cannot land on top of the current one, that the keyboard reaches every result
 * and says so through `aria-activedescendant`, that each type lands on the right
 * screen, and that a payload carrying more than the contract promised still
 * cannot print it.
 *
 * No request leaves the process: the resource module is mocked, so `fetch` is a
 * spy whose promise the test controls. Timers are real — a debounce is a promise
 * about wall-clock behaviour, and the component takes its delay as a prop for
 * exactly this reason.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import GlobalSearch from '@/components/operational/GlobalSearch.vue'
import { OPERATIONAL_ROUTES, flush, mountOperational, resetStores, stubProperty, useArabic } from '../helpers'

// `vi.hoisted` because the mock factory runs while the component above is being
// imported, which is before any ordinary top-level binding exists.
const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }))

vi.mock('@/resources/search', () => ({
  SEARCH_MIN_LENGTH: 2,
  SEARCH_LIMIT: 5,
  SEARCH_DEBOUNCE_MS: 250,
  // A single shared stand-in: the component asks for one instance on setup.
  operationalSearchResource: () => ({ fetch: fetchMock }),
}))

/** Short enough to keep the suite quick, long enough to batch real keystrokes. */
const DEBOUNCE = 30

const INPUT = '[data-search-input]'
const PANEL = '[data-search-panel]'
const OPTION = '[data-search-option]'
const GROUP = '[data-search-group]'
const HINT = '[data-search-hint]'

/**
 * `tests/helpers.js` registers the routes the 16.7.0 boards link to, which does
 * not include the room rack. Extended here rather than there: that file is the
 * Lead's, and a search-only route belongs with the search spec. Reported for the
 * Lead to fold in.
 */
const ROUTES = [...OPERATIONAL_ROUTES, { path: '/rooms', name: 'RoomRack', component: { template: '<div />' } }]

const GUEST = {
  type: 'Guest',
  id: 'HPMS-GUEST-0001',
  primary_label: 'Layla Haddad',
  secondary_label: '+97400000000',
  property: null,
  status: '',
  safe_summary: '',
}

const RESERVATION = {
  type: 'Reservation',
  id: 'HPMS-RES-0007',
  primary_label: 'Layla Haddad',
  secondary_label: '12 Aug — 14 Aug',
  property: 'DOHA01',
  status: 'Confirmed',
  safe_summary: '2 nights',
}

const STAY = {
  type: 'Stay',
  id: 'HPMS-STAY-0003',
  primary_label: 'Layla Haddad · 412',
  secondary_label: 'Room 412',
  property: 'DOHA01',
  status: 'In House',
  safe_summary: '',
}

const ROOM = {
  type: 'Hotel Room',
  id: 'HPMS-ROOM-0412',
  primary_label: '412',
  secondary_label: 'Deluxe King',
  property: 'DOHA01',
  status: 'Vacant',
  safe_summary: '',
}

const FOLIO = {
  type: 'Guest Folio',
  id: 'HPMS-FOLIO-0009',
  primary_label: 'Folio 0009',
  secondary_label: 'Layla Haddad',
  property: 'DOHA01',
  status: 'Open',
  safe_summary: '',
}

function payload(results, overrides = {}) {
  return {
    query: 'layla',
    property: 'DOHA01',
    min_length: 2,
    limit: 5,
    truncated: false,
    counts: { Guest: 0, Reservation: 0, Stay: 0, 'Hotel Room': 0, 'Guest Folio': 0 },
    results,
    ...overrides,
  }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })

  return { promise, resolve, reject }
}

async function mountSearch(props = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: ROUTES })
  const wrapper = await mountOperational(GlobalSearch, {
    router,
    props: { debounceMs: DEBOUNCE, ...props },
  })

  return { wrapper, router }
}

/** Let the debounce fire and the resulting render settle. */
async function settle(wrapper, ms = DEBOUNCE * 3) {
  await new Promise((resolve) => setTimeout(resolve, ms))
  await flush(wrapper)
}

async function type(wrapper, text) {
  await wrapper.get(INPUT).setValue(text)
}

async function search(wrapper, term = 'layla') {
  await type(wrapper, term)
  await settle(wrapper)
}

function panelText(wrapper) {
  const panel = wrapper.find(PANEL)

  return panel.exists() ? panel.text() : ''
}

function press(wrapper, key) {
  return wrapper.get(INPUT).trigger('keydown', { key })
}

beforeEach(() => {
  stubProperty()
  fetchMock.mockReset()
  fetchMock.mockResolvedValue(payload([]))
})

afterEach(() => {
  resetStores()
})

describe('GlobalSearch requests', () => {
  it('debounces: several rapid keystrokes are one request for the final term', async () => {
    const { wrapper } = await mountSearch()

    for (const term of ['l', 'la', 'lay', 'layl', 'layla']) {
      await type(wrapper, term)
    }

    await settle(wrapper)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith({
      query: 'layla',
      property: 'DOHA01',
      limit: 5,
    })
  })

  it('sends nothing below the minimum length and says why', async () => {
    const { wrapper } = await mountSearch()

    await search(wrapper, 'l')

    expect(fetchMock).not.toHaveBeenCalled()
    expect(wrapper.get(HINT).text()).toBe('Type at least 2 characters to search.')
    expect(wrapper.find(OPTION).exists()).toBe(false)
  })

  it('shows the searching state while the request is in flight', async () => {
    const pending = deferred()

    fetchMock.mockReturnValueOnce(pending.promise)

    const { wrapper } = await mountSearch()

    await search(wrapper)

    expect(panelText(wrapper)).toContain('Searching')

    pending.resolve(payload([GUEST]))
    await flush(wrapper)

    expect(panelText(wrapper)).not.toContain('Searching')
    expect(wrapper.findAll(OPTION)).toHaveLength(1)
  })

  it('keeps the rows on screen while the next request is in flight', async () => {
    const pending = deferred()

    fetchMock.mockResolvedValueOnce(payload([GUEST])).mockReturnValueOnce(pending.promise)

    const { wrapper } = await mountSearch()

    await search(wrapper, 'layla')

    expect(wrapper.findAll(OPTION)).toHaveLength(1)

    await search(wrapper, 'layla h')

    // Still readable, and reporting itself busy rather than blanking.
    expect(wrapper.findAll(OPTION)).toHaveLength(1)
    expect(wrapper.get(`${PANEL} [aria-busy]`).attributes('aria-busy')).toBe('true')
    expect(panelText(wrapper)).not.toContain('Searching')

    pending.resolve(payload([RESERVATION]))
    await flush(wrapper)

    expect(wrapper.get(`${PANEL} [aria-busy]`).attributes('aria-busy')).toBe('false')
    expect(panelText(wrapper)).toContain('12 Aug — 14 Aug')
  })

  /**
   * The classic typeahead defect: the answer to a query the user has already
   * moved on from arrives last and overwrites the answer they are reading.
   */
  it('drops a stale response that arrives after a newer one', async () => {
    const slow = deferred()
    const fast = deferred()

    fetchMock.mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise)

    const { wrapper } = await mountSearch()

    await search(wrapper, 'lay')
    await search(wrapper, 'layla')

    expect(fetchMock).toHaveBeenCalledTimes(2)

    fast.resolve(payload([RESERVATION], { query: 'layla' }))
    await flush(wrapper)

    expect(panelText(wrapper)).toContain('12 Aug — 14 Aug')
    expect(wrapper.findAll(OPTION)).toHaveLength(1)

    // The abandoned query answers late. It must change nothing.
    slow.resolve(payload([GUEST, STAY, ROOM], { query: 'lay', truncated: true }))
    await flush(wrapper)

    expect(wrapper.findAll(OPTION)).toHaveLength(1)
    expect(panelText(wrapper)).toContain('12 Aug — 14 Aug')
    expect(panelText(wrapper)).not.toContain('Deluxe King')
    expect(wrapper.find('[data-search-truncated]').exists()).toBe(false)
  })
})

describe('GlobalSearch results', () => {
  it('groups results under the right headings, in the fixed operational order', async () => {
    // Deliberately shuffled: the grouping is the component's, not the payload's.
    fetchMock.mockResolvedValue(payload([FOLIO, ROOM, STAY, RESERVATION, GUEST]))

    const { wrapper } = await mountSearch()

    await search(wrapper)

    const headings = wrapper.findAll(GROUP).map((node) => node.text())

    expect(headings).toEqual(['Guests', 'Reservations', 'Stays', 'Rooms', 'Folios'])

    const groups = wrapper.findAll('[role="group"]')

    expect(groups).toHaveLength(5)
    expect(groups[0].text()).toContain('Layla Haddad')
    expect(groups[3].text()).toContain('Deluxe King')

    // Type and status are words, never colour alone.
    expect(groups[1].text()).toContain('Confirmed')
    expect(groups[2].text()).toContain('In House')
  })

  it('announces the result count in a live region', async () => {
    fetchMock.mockResolvedValue(payload([GUEST, RESERVATION]))

    const { wrapper } = await mountSearch()

    await search(wrapper)

    const live = wrapper.get('[data-search-live]')

    expect(live.attributes('aria-live')).toBe('polite')
    expect(live.text()).toBe('2 result(s)')
  })

  it('names the query in the empty state', async () => {
    fetchMock.mockResolvedValue(payload([], { query: 'zzqq' }))

    const { wrapper } = await mountSearch()

    await search(wrapper, 'zzqq')

    expect(panelText(wrapper)).toContain('zzqq')
    expect(panelText(wrapper)).toContain('Nothing matches')
  })

  it('reports a permission failure with the permission wording', async () => {
    fetchMock.mockRejectedValue({ status: 403 })

    const { wrapper } = await mountSearch()

    await search(wrapper)

    expect(panelText(wrapper)).toContain('Not permitted')
    expect(panelText(wrapper)).toContain('permission')
    expect(wrapper.find(OPTION).exists()).toBe(false)
  })

  it('asks the user to refine when the server truncated the answer', async () => {
    fetchMock.mockResolvedValue(payload([GUEST], { truncated: true }))

    const { wrapper } = await mountSearch()

    await search(wrapper)

    expect(wrapper.get('[data-search-truncated]').text()).toBe('More matches exist — refine the search.')
  })

  /**
   * PRIVACY BOUNDARY. The panel renders a projection of the seven contract
   * fields, so a payload carrying a blacklist flag, its reason, an
   * identification number or an alert body has nowhere to put them.
   */
  it('renders none of the sensitive fields a polluted payload might carry', async () => {
    fetchMock.mockResolvedValue(
      payload([
        {
          ...GUEST,
          is_blacklisted: true,
          blacklist_reason: 'incident 2025-114',
          id_number: 'QA-1122334455',
          id_type: 'Passport',
          alert: 'do not admit',
          folio_balance: 1240.5,
        },
      ]),
    )

    const { wrapper } = await mountSearch()

    await search(wrapper)

    const html = wrapper.html()

    expect(wrapper.findAll(OPTION)).toHaveLength(1)
    expect(panelText(wrapper)).toContain('Layla Haddad')

    for (const secret of [
      'incident 2025-114',
      'QA-1122334455',
      'do not admit',
      'blacklist',
      'Blacklisted',
      'id_number',
      'Passport',
      '1240.5',
    ]) {
      expect(html).not.toContain(secret)
    }
  })
})

describe('GlobalSearch keyboard and combobox semantics', () => {
  it('is a combobox that owns its listbox', async () => {
    fetchMock.mockResolvedValue(payload([GUEST, RESERVATION]))

    const { wrapper } = await mountSearch()
    const input = wrapper.get(INPUT)

    expect(input.attributes('role')).toBe('combobox')
    expect(input.attributes('aria-expanded')).toBe('false')

    await search(wrapper)

    expect(input.attributes('aria-expanded')).toBe('true')

    const listbox = wrapper.get('[role="listbox"]')

    expect(input.attributes('aria-controls')).toBe(listbox.attributes('id'))

    const options = wrapper.findAll(OPTION)

    expect(options.map((option) => option.attributes('role'))).toEqual(['option', 'option'])
    expect(options.map((option) => option.attributes('aria-selected'))).toEqual(['true', 'false'])
    expect(options.every((option) => Boolean(option.attributes('id')))).toBe(true)
  })

  it('moves the active option with the arrow keys, wrapping, and exposes it', async () => {
    fetchMock.mockResolvedValue(payload([GUEST, RESERVATION, STAY]))

    const { wrapper } = await mountSearch()

    await search(wrapper)

    const input = wrapper.get(INPUT)
    const ids = wrapper.findAll(OPTION).map((option) => option.attributes('id'))

    expect(input.attributes('aria-activedescendant')).toBe(ids[0])

    await press(wrapper, 'ArrowDown')
    expect(input.attributes('aria-activedescendant')).toBe(ids[1])
    expect(wrapper.findAll(OPTION)[1].attributes('aria-selected')).toBe('true')

    await press(wrapper, 'ArrowDown')
    expect(input.attributes('aria-activedescendant')).toBe(ids[2])

    // Wraps rather than dead-ending.
    await press(wrapper, 'ArrowDown')
    expect(input.attributes('aria-activedescendant')).toBe(ids[0])

    await press(wrapper, 'ArrowUp')
    expect(input.attributes('aria-activedescendant')).toBe(ids[2])

    await press(wrapper, 'ArrowUp')
    expect(input.attributes('aria-activedescendant')).toBe(ids[1])
  })

  it('opens the active result on Enter', async () => {
    fetchMock.mockResolvedValue(payload([GUEST, RESERVATION]))

    const { wrapper, router } = await mountSearch()

    await search(wrapper)
    await press(wrapper, 'ArrowDown')
    await press(wrapper, 'Enter')
    await flush(wrapper)

    expect(router.currentRoute.value.name).toBe('Reservation')
    expect(router.currentRoute.value.params.id).toBe('HPMS-RES-0007')
    expect(wrapper.find(PANEL).exists()).toBe(false)
  })

  it('closes on Escape and returns focus to the input', async () => {
    fetchMock.mockResolvedValue(payload([GUEST]))

    const { wrapper } = await mountSearch()
    const input = wrapper.get(INPUT)

    input.element.focus()
    await search(wrapper)

    expect(wrapper.find(PANEL).exists()).toBe(true)

    // Focus is somewhere else in the panel when Escape arrives.
    wrapper.get('[data-search-close]').element.focus()
    expect(document.activeElement).not.toBe(input.element)

    await press(wrapper, 'Escape')
    await flush(wrapper)

    expect(wrapper.find(PANEL).exists()).toBe(false)
    expect(document.activeElement).toBe(input.element)

    // Focus is what opens the panel, so a dismissed panel must not spring back
    // open just because Escape handed focus to the input. Typing brings it back.
    await search(wrapper, 'layla haddad')

    expect(wrapper.find(PANEL).exists()).toBe(true)
  })

  it('closes on Tab without swallowing the keystroke', async () => {
    fetchMock.mockResolvedValue(payload([GUEST]))

    const { wrapper } = await mountSearch()

    await search(wrapper)
    await press(wrapper, 'Tab')

    expect(wrapper.find(PANEL).exists()).toBe(false)
  })
})

describe('GlobalSearch navigation, one case per entity type', () => {
  async function openFirst(result) {
    fetchMock.mockResolvedValue(payload([result]))

    const { wrapper, router } = await mountSearch()

    await search(wrapper)
    await wrapper.get(OPTION).trigger('click')
    await flush(wrapper)

    return router.currentRoute.value
  }

  it('opens a Guest on the guest profile', async () => {
    const route = await openFirst(GUEST)

    expect(route.name).toBe('GuestProfile')
    expect(route.params.id).toBe('HPMS-GUEST-0001')
  })

  it('opens a Reservation on the reservation screen', async () => {
    const route = await openFirst(RESERVATION)

    expect(route.name).toBe('Reservation')
    expect(route.params.id).toBe('HPMS-RES-0007')
  })

  it('opens a Stay on the stay screen', async () => {
    const route = await openFirst(STAY)

    expect(route.name).toBe('Stay')
    expect(route.params.id).toBe('HPMS-STAY-0003')
  })

  it('opens a Guest Folio on the folio screen', async () => {
    const route = await openFirst(FOLIO)

    expect(route.name).toBe('Folio')
    expect(route.params.id).toBe('HPMS-FOLIO-0009')
  })

  /**
   * `pages/RoomRack.vue` selects a room from its own local state and reads
   * neither a route param nor a query, so the rack is opened plain. A query
   * parameter here would look like deep-linking and do nothing; raised for 16.7.4.
   */
  it('opens a Hotel Room on the room rack, with no parameter it would ignore', async () => {
    const route = await openFirst(ROOM)

    expect(route.name).toBe('RoomRack')
    expect(route.params).toEqual({})
    expect(route.query).toEqual({})
  })
})

describe('GlobalSearch in an Arabic session', () => {
  it('renders no physical direction utility', async () => {
    useArabic()

    fetchMock.mockResolvedValue(payload([GUEST, RESERVATION, ROOM], { truncated: true }))

    const { wrapper } = await mountSearch()

    await search(wrapper)

    const classes = (wrapper.html().match(/class="[^"]*"/g) || []).join(' ')

    expect(classes).not.toMatch(/(^|[\s"])(ml-|mr-|pl-|pr-|left-|right-)/)
    expect(classes).not.toMatch(/text-(left|right)\b/)
    expect(classes).toContain('text-start')

    // Arabic labels, not just an Arabic direction.
    expect(wrapper.findAll(GROUP).map((node) => node.text())).toEqual(['النزلاء', 'الحجوزات', 'الغرف'])
  })
})
