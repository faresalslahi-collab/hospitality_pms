/**
 * The Reservation Workspace (16.7.2).
 *
 * These tests defend the disclosure rules before they defend anything else. The
 * workspace is an aggregate, and an aggregate is where permission boundaries
 * quietly dissolve: the endpoint omits `guest_standing`, `corporate` and
 * `deposit.credited` for a caller who may not read the DocType each came from, and
 * an *absent* key must never be rendered as a zero, a dash borrowed from the
 * disclosed case, or a negative claim about the guest.
 *
 * The second thing they defend is that this screen decides nothing. Which verbs are
 * offered comes from `allowed_transitions` and `editability`; where a test changes
 * only an editability flag and expects a control to vanish, it is proving there is
 * no second copy of the state machine in Vue.
 *
 * Mounted through a real `RouterView`, not directly: the tab lives in the URL query
 * and the unsaved-changes guard is `onBeforeRouteLeave`, and neither means anything
 * to a component the router is not actually rendering.
 */
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { RouterView, createMemoryHistory, createRouter } from 'vue-router'

import { OPERATIONAL_ROUTES, flush, resetStores, stubProperty, stubSession, useArabic } from '../helpers'

const { workspace, history, update, confirmRes, guaranteeRes } = vi.hoisted(() => ({
  workspace: { data: null, loading: false, error: null, fetch: vi.fn() },
  history: { data: null, loading: false, error: null, fetch: vi.fn() },
  update: { data: null, loading: false, error: null, submit: vi.fn() },
  confirmRes: { data: null, loading: false, error: null, submit: vi.fn() },
  guaranteeRes: { data: null, loading: false, error: null, submit: vi.fn() },
}))

vi.mock('@/resources/reservationWorkspace', async (importOriginal) => {
  const actual = await importOriginal()

  return {
    ...actual,
    reservationWorkspaceResource: () => workspace,
    reservationHistoryResource: () => history,
    updateReservationDetailsResource: () => update,
  }
})

/**
 * The two transitions the page submits itself are stubbed. The role constant comes
 * from the real module: `NO_SHOW_ROLES` mirrors the server list, and a test that
 * stubbed it would prove nothing about the role rule.
 */
vi.mock('@/resources/reservations', async (importOriginal) => {
  const actual = await importOriginal()

  return {
    ...actual,
    confirmReservationResource: () => confirmRes,
    guaranteeReservationResource: () => guaranteeRes,
  }
})

const { default: Reservation } = await import('@/pages/Reservation.vue')

const RES = 'HPMS-RES-2026-00001'

/** One room line, shaped as `_room_lines` sends it. */
function roomLine(overrides = {}) {
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
    assigned_room: 'DOHA01-405',
    // `room_rate` is total/nights *including* every supplement, so it equals no
    // actual night on any stay with an uplift. Nothing in the shell renders it.
    room_rate: 333.33,
    total_amount: 800,
    reservation_status: 'Confirmed',
    special_requests: 'High floor',
    rate_lines: [{ rate_date: '2026-08-08', rate: 300, net_rate: 333.33 }],
    ...overrides,
  }
}

/** The workspace payload, exactly as `get_workspace` returns it. */
function payload(overrides = {}) {
  return {
    reservation: {
      name: RES,
      property: 'DOHA01',
      reservation_status: 'Confirmed',
      reservation_type: 'Individual',
      guest: 'HPMS-GUEST-0001',
      guest_name: 'Layla Haddad',
      guest_mobile: '+97400000000',
      arrival_date: '2026-08-08',
      departure_date: '2026-08-10',
      arrival_time: '18:00:00',
      nights: 2,
      total_rooms: 2,
      total_adults: 3,
      total_children: 1,
      total_amount: 1600,
      room_charges_total: 1600,
      currency: 'QAR',
      booking_source: 'Direct',
      market_segment: 'Leisure',
      external_reference: 'OTA-55',
      special_requests: 'High floor',
      internal_notes: 'Regular guest',
      guarantee_type: 'Credit Card',
      guaranteed_on: '2026-08-01 10:00:00',
      booked_on: '2026-07-20 09:30:00',
      cancellation_charge: 0,
      ...overrides.reservation,
    },
    rooms: overrides.rooms ?? [roomLine(), roomLine({ name: 'RES-LINE-2', idx: 2, assigned_room: null })],
    deposit: {
      deposit_policy: 'STANDARD',
      deposit_required: 500,
      deposit_received: 500,
      deposit_due_date: '2026-08-05',
      allocation: { 'RES-LINE-1': 250, 'RES-LINE-2': 250 },
      credited: 500,
      ...overrides.deposit,
    },
    editability: {
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
      ...overrides.editability,
    },
    allowed_transitions: overrides.allowed_transitions ?? ['Cancelled', 'Checked In', 'Guaranteed', 'No Show'],
    guest_standing: { vip_status: 'VIP', guest_type: 'Corporate', is_blacklisted: false, ...overrides.guest_standing },
    corporate: overrides.corporate ?? {
      account: 'HPMS-CORP-0001',
      account_name: 'Qatar Energy',
      credit_status: 'Active',
      credit: { credit_limit: 50000, credit_used: 1600, credit_available: 48400, unlimited: false },
    },
  }
}

function historyPayload(entries) {
  return { reservation: RES, limit: 100, entries }
}

/** The application's routes, with the real page behind the reservation record. */
function workspaceRouter() {
  const routes = OPERATIONAL_ROUTES.map((route) =>
    route.name === 'Reservation' ? { ...route, component: Reservation } : route,
  )

  return createRouter({ history: createMemoryHistory(), routes })
}

/**
 * The page must be rendered *by* the router, not mounted beside it: without a
 * matched route record `onBeforeRouteLeave` registers no guard at all, and the
 * unsaved-changes tests would pass while the guard did nothing in production.
 */
const Shell = { render: () => h(RouterView) }

async function mountWorkspace({ query = {}, router = workspaceRouter() } = {}) {
  router.push({ name: 'Reservation', params: { id: RES }, query })
  await router.isReady()

  const wrapper = mount(Shell, { attachTo: document.body, global: { plugins: [router] } })

  await flush(wrapper)

  return { wrapper, router }
}

/** All buttons with this exact visible text, inside the mounted tree. */
function buttonsWithText(wrapper, text) {
  return wrapper.findAll('button').filter((button) => button.text().trim() === text)
}

/** A button in a teleported dialog, which is outside the mounted tree. */
function clickInBody(text) {
  const button = Array.from(document.body.querySelectorAll('button')).find(
    (candidate) => candidate.textContent.trim() === text,
  )

  button.click()
}

function tabButton(wrapper, label) {
  return wrapper.findAll('[role="tab"]').find((tab) => tab.text().trim() === label)
}

function activeTabLabel(wrapper) {
  const selected = wrapper.findAll('[role="tab"]').find((tab) => tab.attributes('aria-selected') === 'true')

  return selected ? selected.text().trim() : ''
}

/** The panel an agent is actually looking at. */
function visiblePanel(wrapper) {
  return wrapper.findAll('[role="tabpanel"]').find((panel) => panel.attributes('hidden') === undefined)
}

async function typeInto(wrapper, element, value) {
  await element.setValue(value)
  await flush(wrapper)
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Manager'])

  workspace.data = payload()
  workspace.loading = false
  workspace.error = null
  workspace.fetch.mockClear()

  history.data = null
  history.loading = false
  history.error = null
  history.fetch.mockClear()

  update.submit.mockReset()
  update.submit.mockResolvedValue({})
  confirmRes.submit.mockReset()
  guaranteeRes.submit.mockReset()
})

describe('Reservation workspace loading', () => {
  it('fetches one aggregate for the reservation in the route', async () => {
    const { wrapper } = await mountWorkspace()

    expect(workspace.fetch).toHaveBeenCalledWith({ reservation: RES })
    expect(wrapper.text()).toContain('Layla Haddad')
    expect(wrapper.text()).toContain(RES)
  })

  it('reports loading before the first response', async () => {
    workspace.data = null
    workspace.loading = true

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('Loading')
  })

  it('reports a failure in place, with a retry that refetches', async () => {
    workspace.data = null
    workspace.error = { status: 500, message: 'Internal Server Error' }

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('Something went wrong')

    workspace.fetch.mockClear()
    await buttonsWithText(wrapper, 'Retry')[0].trigger('click')

    expect(workspace.fetch).toHaveBeenCalledWith({ reservation: RES })
  })

  it('reports a permission failure without offering a retry', async () => {
    workspace.data = null
    workspace.error = { status: 403, exc_type: 'PermissionError', message: 'Not allowed' }

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('Not permitted')
    expect(buttonsWithText(wrapper, 'Retry')).toHaveLength(0)
  })
})

describe('Reservation workspace header', () => {
  it('renders every figure an agent quotes without changing tab', async () => {
    const { wrapper } = await mountWorkspace()
    const text = wrapper.text()

    expect(text).toContain(RES)
    expect(text).toContain('Layla Haddad')
    expect(text).toContain('Confirmed')
    expect(text).toContain('08 Aug 2026')
    expect(text).toContain('10 Aug 2026')
    expect(text).toContain('Nights')
    expect(text).toContain('3 adult(s), 1 child(ren)')
    // One of the two lines carries a room; the count is of lines, not a claim
    // about either room.
    expect(text).toContain('1 of 2')
    expect(text).toMatch(/1,600\.00/)
    expect(text).toContain('Deposit')
    expect(text).toMatch(/500\.00/)
    expect(text).toContain('20 Jul 2026')
  })

  it('withholds the night count when the lines hold different intervals', async () => {
    // `refresh_header_dates` writes min(arrival)/max(departure), so the header span
    // covers nights no room occupies and a nights figure would be quoted.
    workspace.data = payload({
      rooms: [roomLine(), roomLine({ name: 'RES-LINE-2', idx: 2, departure_date: '2026-08-12' })],
    })

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).not.toContain('Nights')
    // The authoritative per-line intervals are one click away.
    expect(buttonsWithText(wrapper, 'Rooms & rates').length).toBeGreaterThan(0)
  })

  it('renders no per-night rate figure, and no rate comparison', async () => {
    const { wrapper } = await mountWorkspace()
    const text = wrapper.text()

    // `room_rate` is an average including supplements, so the shell never shows it;
    // and there is deliberately no "booked versus current rate" element anywhere,
    // because for a corporate booking the difference is the contract discount.
    expect(text).not.toContain('333.33')
    expect(text).not.toMatch(/\bRate\b/)
  })

  it('never renders a room code where the door number is the fact', async () => {
    // `assigned_room` is the docname — a room *code* — and `room_number` is what is
    // on the door. Both are on this line, and the header states a count and no
    // identifier at all, so neither can be mislabelled as the other.
    workspace.data = payload({
      rooms: [
        roomLine({ assigned_room: 'DOHA01-405', room_number: '405', room_ready: true }),
        roomLine({ name: 'RES-LINE-2', idx: 2, assigned_room: null }),
      ],
    })

    const { wrapper } = await mountWorkspace()

    expect(wrapper.html()).not.toContain('DOHA01-405')
    expect(wrapper.text()).toContain('1 of 2')
  })
})

describe('Reservation workspace tabs', () => {
  it('offers the six tabs in order, with the overview selected by default', async () => {
    const { wrapper } = await mountWorkspace()
    const labels = wrapper.findAll('[role="tab"]').map((tab) => tab.text().trim())

    expect(labels).toEqual(['Overview', 'Rooms & rates', 'Guests', 'Guarantee & deposit', 'Notes', 'History'])
    expect(activeTabLabel(wrapper)).toBe('Overview')
    expect(visiblePanel(wrapper).attributes('id')).toBe('reservation-panel-overview')
  })

  it('puts the tab in the URL so a reload and a shared link land in the same place', async () => {
    const { wrapper, router } = await mountWorkspace()

    await tabButton(wrapper, 'Guests').trigger('click')
    await flush(wrapper)

    expect(router.currentRoute.value.query.tab).toBe('guests')
    expect(activeTabLabel(wrapper)).toBe('Guests')
  })

  it('opens on the tab the URL names', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'notes' } })

    expect(activeTabLabel(wrapper)).toBe('Notes')
    expect(visiblePanel(wrapper).attributes('id')).toBe('reservation-panel-notes')
  })

  it('falls back to the overview for a tab it does not have', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'folio' } })

    expect(activeTabLabel(wrapper)).toBe('Overview')
  })

  it('moves between tabs with the arrow keys, and Home and End', async () => {
    const { wrapper, router } = await mountWorkspace()
    const tablist = wrapper.find('[role="tablist"]')

    await tablist.trigger('keydown', { key: 'ArrowRight' })
    await flush(wrapper)
    expect(router.currentRoute.value.query.tab).toBe('rooms')

    await tablist.trigger('keydown', { key: 'ArrowLeft' })
    await flush(wrapper)
    expect(activeTabLabel(wrapper)).toBe('Overview')

    await tablist.trigger('keydown', { key: 'End' })
    await flush(wrapper)
    expect(activeTabLabel(wrapper)).toBe('History')

    await tablist.trigger('keydown', { key: 'Home' })
    await flush(wrapper)
    expect(activeTabLabel(wrapper)).toBe('Overview')
  })

  it('describes the tabs to a screen reader', async () => {
    const { wrapper } = await mountWorkspace()
    const tab = tabButton(wrapper, 'Notes')

    expect(wrapper.find('[role="tablist"]').exists()).toBe(true)
    expect(tab.attributes('aria-selected')).toBe('false')
    expect(tab.attributes('aria-controls')).toBe('reservation-panel-notes')
    // Only the selected tab is in the tab order; the arrows move within the list.
    expect(tab.attributes('tabindex')).toBe('-1')
    expect(tabButton(wrapper, 'Overview').attributes('tabindex')).toBe('0')

    const panel = visiblePanel(wrapper)

    expect(panel.attributes('role')).toBe('tabpanel')
    expect(panel.attributes('aria-labelledby')).toBe('reservation-tab-overview')
  })

  it('mounts the Rooms & rates tab in its own panel', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'rooms' } })

    // The panel is the shell's; what is inside it belongs to RoomsRatesTab and is
    // covered by that component's own spec. This asserts only that the shell
    // hands the panel over — it was empty while that component did not exist yet.
    expect(visiblePanel(wrapper).attributes('id')).toBe('reservation-panel-rooms')
    expect(visiblePanel(wrapper).text()).not.toBe('')
  })
})

describe('Reservation workspace overview', () => {
  it('shows the stay, the occupancy, the status and the total', async () => {
    const { wrapper } = await mountWorkspace()
    const panel = visiblePanel(wrapper)
    const text = panel.text()

    expect(text).toContain('08 Aug 2026')
    expect(text).toContain('10 Aug 2026')
    expect(text).toContain('Nights')
    expect(text).toContain('3 adult(s), 1 child(ren)')
    expect(text).toContain('Confirmed')
    expect(text).toMatch(/1,600\.00/)
    // Never editable here: the reference is the channel's and the booking's own.
    expect(text).toContain('OTA-55')
    expect(text).toContain('Individual')

    // The three collected fields are editable for a live booking, so their values
    // are in the controls rather than in the page text.
    const values = panel.findAll('input').map((input) => input.element.value)

    expect(values).toContain('Direct')
    expect(values).toContain('Leisure')
    expect(values).toContain('18:00:00')
  })

  it('offers the corporate contract only when the server disclosed it', async () => {
    const { wrapper } = await mountWorkspace()

    expect(visiblePanel(wrapper).text()).toContain('Qatar Energy')

    const withheld = payload()
    delete withheld.corporate
    workspace.data = withheld

    const second = await mountWorkspace()

    expect(second.wrapper.text()).not.toContain('Qatar Energy')
    // Absence means either "no company" or "not disclosed to you", and the two are
    // indistinguishable from here, so neither is claimed.
    expect(second.wrapper.text()).not.toContain('Company')
  })

  it('says the credit position is unavailable rather than showing a zero', async () => {
    workspace.data = payload({
      corporate: { account: 'HPMS-CORP-0001', account_name: 'Qatar Energy', credit_status: 'Active', credit: null },
    })

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('The credit position is unavailable for this account.')
  })

  it('says why a field cannot be edited, in the server terms', async () => {
    workspace.data = payload({
      reservation: { reservation_status: 'Cancelled' },
      editability: { status: 'Cancelled', may_edit_details: false, is_terminal: true, may_assign_room: false },
      allowed_transitions: [],
    })

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('This cannot be changed while the booking is Cancelled.')
    // Read-only means no control at all, not a disabled one.
    expect(visiblePanel(wrapper).findAll('input')).toHaveLength(0)
  })
})

describe('Reservation workspace guests tab', () => {
  it('shows the primary guest and links to the profile', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'guests' } })
    const panel = visiblePanel(wrapper)

    expect(panel.text()).toContain('Layla Haddad')
    expect(panel.text()).toContain('+97400000000')
    expect(panel.text()).toContain('3 adult(s), 1 child(ren)')

    const link = panel.findAll('a').find((anchor) => anchor.text() === 'Open guest profile')

    expect(link.attributes('href')).toBe('/guests/HPMS-GUEST-0001')
  })

  it('is an association, not a guest dossier', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'guests' } })
    const panel = visiblePanel(wrapper).text()

    // No Guest 360: no stay history, no folio history, no documents, no merge.
    expect(panel).not.toContain('Stay history')
    expect(panel).not.toContain('Folio')
    expect(panel).not.toContain('Identification')
    expect(panel).not.toContain('Merge')
  })

  it('reports withheld standing as withheld, and claims nothing about the guest', async () => {
    const withheld = payload()
    delete withheld.guest_standing
    workspace.data = withheld

    const { wrapper } = await mountWorkspace({ query: { tab: 'guests' } })
    const panel = visiblePanel(wrapper).text()

    expect(panel).toContain('Guest standing is not shown to your role.')
    // A reader the server withheld the section from has been told nothing. Neither
    // an all-clear nor an absence of VIP standing may be borrowed from that.
    expect(panel).not.toContain('Not blacklisted')
    expect(panel).not.toContain('Blacklisted')
    expect(panel).not.toContain('VIP')
    expect(panel).not.toContain('Guest type')
  })

  it('shows the blacklist flag as a flag, and never its reason', async () => {
    const reason = 'Card chargeback, incident 2025-114'
    workspace.data = payload({
      guest_standing: { vip_status: '', guest_type: 'Individual', is_blacklisted: true, blacklist_reason: reason },
    })

    const { wrapper } = await mountWorkspace({ query: { tab: 'guests' } })

    expect(visiblePanel(wrapper).text()).toContain('Blacklisted')
    expect(wrapper.html()).not.toContain(reason)
    expect(wrapper.html()).not.toContain('chargeback')
  })

  it('says nothing about the blacklist when that clearance was not given', async () => {
    // `is_blacklisted` is permlevel 2 and absent on its own, even when the rest of
    // the standing was disclosed.
    const partial = payload()
    delete partial.guest_standing.is_blacklisted
    workspace.data = partial

    const { wrapper } = await mountWorkspace({ query: { tab: 'guests' } })
    const panel = visiblePanel(wrapper).text()

    expect(panel).toContain('VIP')
    expect(panel).not.toContain('Blacklisted')
    expect(panel).not.toContain('Not blacklisted')
  })
})

describe('Reservation workspace deposit tab', () => {
  it('states the position and that it is for reference only', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'deposit' } })
    const panel = visiblePanel(wrapper).text()

    expect(panel).toContain('Shown for reference. A deposit is taken as a payment on the folio, never edited here.')
    expect(panel).toContain('Deposit policy')
    expect(panel).toContain('STANDARD')
    expect(panel).toContain('Deposit required')
    expect(panel).toContain('Deposit recorded')
    expect(panel).toContain('05 Aug 2026')
    expect(panel).toContain('Credit Card')
    expect(panel).toContain('Allocation per room')
    expect(panel).toMatch(/250\.00/)
  })

  it('has no editable money field anywhere', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'deposit' } })
    const panel = visiblePanel(wrapper)

    // Money enters the system as a payment on a folio. There is nothing to type.
    expect(panel.findAll('input')).toHaveLength(0)
    expect(panel.findAll('textarea')).toHaveLength(0)
    expect(panel.findAll('select')).toHaveLength(0)
  })

  it('warns when a deposit is expected and nothing is recorded against it', async () => {
    // Nothing in the application writes `deposit_received`, and a folio's only
    // production creator is check-in — so this state blocks arrival with no in-app
    // remedy, and the agent is told that rather than shown a figure to collect.
    workspace.data = payload({ deposit: { deposit_required: 500, deposit_received: 0 } })

    const { wrapper } = await mountWorkspace({ query: { tab: 'deposit' } })
    const panel = visiblePanel(wrapper).text()

    expect(panel).toContain('is required')
    expect(panel).toMatch(/500\.00/)
    expect(panel).toMatch(/0\.00/)
    // Not an outstanding balance and not a folio position: no verb exists for it.
    expect(panel).not.toContain('Balance due')
    expect(panel).not.toContain('outstanding')
  })

  it('does not warn when the booking records the deposit it asked for', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'deposit' } })

    expect(visiblePanel(wrapper).text()).not.toContain('is required;')
  })

  it('reports withheld folio credit as withheld, and still states the expectation', async () => {
    const withheld = payload()
    delete withheld.deposit.credited
    workspace.data = withheld

    const { wrapper } = await mountWorkspace({ query: { tab: 'deposit' } })
    const panel = visiblePanel(wrapper).text()

    expect(panel).toContain('What the folios have been credited is not shown to your role.')
    // The expectation is Reservation's own and is not withheld with it.
    expect(panel).toContain('Deposit required')
    expect(panel).toContain('Deposit recorded')
    expect(panel).toMatch(/500\.00/)
  })

  it('names the allocation rows by the room type name, never only the code', async () => {
    workspace.data = payload({
      rooms: [roomLine({ room_type_name: 'Executive King' }), roomLine({ name: 'RES-LINE-2', idx: 2 })],
    })

    const { wrapper } = await mountWorkspace({ query: { tab: 'deposit' } })
    const panel = visiblePanel(wrapper).text()

    expect(panel).toContain('Room 1')
    expect(panel).toContain('Executive King')
  })

  it('makes no readiness claim when the room condition was not disclosed', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'deposit' } })
    const panel = visiblePanel(wrapper).text()

    // The Hotel Room keys are absent for an uncleared caller, and "ready" is a
    // claim about a room this payload said nothing about.
    expect(panel).not.toContain('Ready')
    expect(panel).not.toContain('Vacant Clean')
  })
})

describe('Reservation workspace notes tab', () => {
  it('edits exactly two fields', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'notes' } })
    const panel = visiblePanel(wrapper)

    expect(panel.text()).toContain('Special requests')
    expect(panel.text()).toContain('Internal notes')
    expect(panel.findAll('textarea')).toHaveLength(2)
  })

  it('saves through the reservation details endpoint, as a field map', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'notes' } })
    const textareas = visiblePanel(wrapper).findAll('textarea')

    await typeInto(wrapper, textareas[1], 'Allergic to feather pillows')

    workspace.fetch.mockClear()
    await buttonsWithText(wrapper, 'Save changes')[0].trigger('click')
    await flush(wrapper)

    expect(update.submit).toHaveBeenCalledWith({
      reservation: RES,
      changes: { internal_notes: 'Allergic to feather pillows' },
    })
    // A field map, never a document: the service refuses any key outside its own
    // writable list, so only what was actually changed is sent.
    expect(Object.keys(update.submit.mock.calls[0][0])).toEqual(['reservation', 'changes'])
    expect(workspace.fetch).toHaveBeenCalledWith({ reservation: RES })
  })

  it('collects the Overview and Notes edits into one call', async () => {
    const { wrapper, router } = await mountWorkspace({ query: { tab: 'notes' } })

    await typeInto(wrapper, visiblePanel(wrapper).findAll('textarea')[0], 'Late arrival')

    // The draft belongs to the workspace, so it survives a tab change.
    router.replace({ query: { tab: 'overview' } })
    await flush(wrapper)

    const sourceField = visiblePanel(wrapper)
      .findAll('input')
      .find((input) => input.element.value === 'Direct')

    await typeInto(wrapper, sourceField, 'Phone')

    await buttonsWithText(wrapper, 'Save changes')[0].trigger('click')
    await flush(wrapper)

    expect(update.submit).toHaveBeenCalledTimes(1)
    expect(update.submit).toHaveBeenCalledWith({
      reservation: RES,
      changes: { special_requests: 'Late arrival', booking_source: 'Phone' },
    })
  })

  it('discards a draft without touching the server', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'notes' } })

    await typeInto(wrapper, visiblePanel(wrapper).findAll('textarea')[1], 'Draft note')
    expect(buttonsWithText(wrapper, 'Save changes').length).toBe(1)

    await buttonsWithText(wrapper, 'Discard changes')[0].trigger('click')
    await flush(wrapper)

    expect(update.submit).not.toHaveBeenCalled()
    expect(buttonsWithText(wrapper, 'Save changes')).toHaveLength(0)
  })

  it('treats a field typed back to the server value as no change at all', async () => {
    const { wrapper } = await mountWorkspace({ query: { tab: 'notes' } })
    const textarea = visiblePanel(wrapper).findAll('textarea')[1]

    await typeInto(wrapper, textarea, 'Something else')
    expect(buttonsWithText(wrapper, 'Save changes').length).toBe(1)

    await typeInto(wrapper, textarea, 'Regular guest')

    // Otherwise the leave warning fires for work that does not exist, and an agent
    // learns to dismiss it.
    expect(buttonsWithText(wrapper, 'Save changes')).toHaveLength(0)
  })

  it('reports a refusal in the server own words and keeps the draft', async () => {
    update.submit.mockRejectedValue({
      status: 417,
      exc_type: 'ValidationError',
      message: 'Reservation HPMS-RES-2026-00001 cannot be edited while it is Cancelled.',
    })

    const { wrapper } = await mountWorkspace({ query: { tab: 'notes' } })

    await typeInto(wrapper, visiblePanel(wrapper).findAll('textarea')[1], 'Draft note')
    await buttonsWithText(wrapper, 'Save changes')[0].trigger('click')
    await flush(wrapper)

    expect(wrapper.text()).toContain('cannot be edited while it is Cancelled')
    expect(buttonsWithText(wrapper, 'Save changes').length).toBe(1)
  })
})

describe('Reservation workspace unsaved changes', () => {
  async function withDraft() {
    const mounted = await mountWorkspace({ query: { tab: 'notes' } })

    await typeInto(mounted.wrapper, visiblePanel(mounted.wrapper).findAll('textarea')[1], 'Draft note')

    return mounted
  }

  it('holds a navigation away and asks', async () => {
    const { wrapper, router } = await withDraft()

    router.push('/').catch(() => {})
    await flush(wrapper)

    expect(document.body.textContent).toContain('This booking has changes that have not been saved. Leave anyway?')
    expect(router.currentRoute.value.name).toBe('Reservation')
  })

  it('can be dismissed, and the agent stays where they were', async () => {
    const { wrapper, router } = await withDraft()

    router.push('/').catch(() => {})
    await flush(wrapper)

    clickInBody('Stay on this page')
    await flush(wrapper)

    expect(router.currentRoute.value.name).toBe('Reservation')
    expect(buttonsWithText(wrapper, 'Save changes').length).toBe(1)
  })

  it('lets the agent leave once they have said so', async () => {
    const { wrapper, router } = await withDraft()

    router.push('/').catch(() => {})
    await flush(wrapper)

    clickInBody('Leave without saving')
    await flush(wrapper)

    expect(router.currentRoute.value.name).toBe('Dashboard')
  })

  it('does not ask when there is nothing unsaved', async () => {
    const { wrapper, router } = await mountWorkspace()

    router.push('/').catch(() => {})
    await flush(wrapper)

    expect(router.currentRoute.value.name).toBe('Dashboard')
    expect(document.body.textContent).not.toContain('Leave anyway?')
  })

  it('does not ask when only the tab changes', async () => {
    const { wrapper, router } = await withDraft()

    await tabButton(wrapper, 'Overview').trigger('click')
    await flush(wrapper)

    expect(router.currentRoute.value.query.tab).toBe('overview')
    expect(document.body.textContent).not.toContain('Leave anyway?')
  })
})

describe('Reservation workspace actions', () => {
  it('offers only the transitions the server said are reachable', async () => {
    const { wrapper } = await mountWorkspace()

    expect(buttonsWithText(wrapper, 'Check in').length).toBe(1)
    expect(buttonsWithText(wrapper, 'Guarantee').length).toBe(1)
    expect(buttonsWithText(wrapper, 'Cancel booking').length).toBe(1)
    expect(buttonsWithText(wrapper, 'Mark no-show').length).toBe(1)
    // `Confirmed` was not offered for a booking that already holds inventory.
    expect(buttonsWithText(wrapper, 'Confirm')).toHaveLength(0)
  })

  it('offers nothing transitional for a terminal booking', async () => {
    workspace.data = payload({
      reservation: { reservation_status: 'Cancelled' },
      editability: { status: 'Cancelled', is_terminal: true, may_edit_details: false, may_assign_room: false },
      allowed_transitions: [],
    })

    const { wrapper } = await mountWorkspace()

    for (const label of ['Check in', 'Confirm', 'Guarantee', 'Cancel booking', 'Mark no-show']) {
      expect(buttonsWithText(wrapper, label)).toHaveLength(0)
    }
  })

  it('withholds the no-show from a role the server refuses', async () => {
    stubSession(['Front Office Agent'])

    const { wrapper } = await mountWorkspace()

    // `NO_SHOW_ROLES` excludes Front Office Agent; cancellation is a front-desk verb.
    expect(buttonsWithText(wrapper, 'Mark no-show')).toHaveLength(0)
    expect(buttonsWithText(wrapper, 'Cancel booking').length).toBe(1)
  })

  it('submits a guarantee and re-reads the aggregate', async () => {
    guaranteeRes.submit.mockResolvedValue({})

    const { wrapper } = await mountWorkspace()

    workspace.fetch.mockClear()
    await buttonsWithText(wrapper, 'Guarantee')[0].trigger('click')
    await flush(wrapper)

    expect(guaranteeRes.submit).toHaveBeenCalledWith({ reservation: RES, guarantee_type: 'Credit Card' })
    expect(workspace.fetch).toHaveBeenCalledWith({ reservation: RES })
  })

  it('confirms a booking that the server says may be confirmed', async () => {
    confirmRes.submit.mockResolvedValue({})
    workspace.data = payload({
      reservation: { reservation_status: 'Tentative' },
      editability: { status: 'Tentative', is_draft_like: true, is_holding: false },
      allowed_transitions: ['Cancelled', 'Confirmed'],
    })

    const { wrapper } = await mountWorkspace()

    await buttonsWithText(wrapper, 'Confirm')[0].trigger('click')
    await flush(wrapper)

    expect(confirmRes.submit).toHaveBeenCalledWith({ reservation: RES })
  })

  it("surfaces the server refusal of a stale offer in the server's words", async () => {
    guaranteeRes.submit.mockRejectedValue({
      status: 409,
      exc_type: 'InvalidStateTransitionError',
      message: 'Reservation HPMS-RES-2026-00001 cannot move from Cancelled to Guaranteed.',
    })

    const { wrapper } = await mountWorkspace()

    await buttonsWithText(wrapper, 'Guarantee')[0].trigger('click')
    await flush(wrapper)

    expect(wrapper.text()).toContain('cannot move from Cancelled to Guaranteed')
  })

  it('navigates to check-in rather than transitioning in place', async () => {
    const { wrapper, router } = await mountWorkspace()

    await buttonsWithText(wrapper, 'Check in')[0].trigger('click')
    await flush(wrapper)

    expect(router.currentRoute.value.name).toBe('CheckIn')
    expect(router.currentRoute.value.params.reservation).toBe(RES)
  })

  it('offers no assignment verb in the header — assignment is per line', async () => {
    // The header briefly carried an Assign button, but only for a booking with
    // exactly one room line, because there was no per-line control yet. A booking
    // is one row per physical room, so a header-level verb had to either guess
    // which line it meant or refuse to appear on the multi-room bookings that most
    // need it. `RoomsRatesTab` now owns the control per line, and its own spec
    // covers both halves — the `may_assign_room` flag and the role hint.
    workspace.data = payload({ rooms: [roomLine({ assigned_room: null })] })

    const { wrapper } = await mountWorkspace()
    const header = wrapper.find('header')

    // Prove the scope exists first: `findAll` on a missing element is empty, so
    // without this the absence below would pass for a header that never rendered.
    expect(header.exists()).toBe(true)
    expect(header.text()).toContain(RES)

    expect(buttonsWithText(header, 'Assign a room')).toHaveLength(0)

    // The shell still owns the dialog the tab asks it to open, so the wiring is
    // present even though the trigger is not.
    expect(wrapper.html()).not.toContain('reservation-header-assign')
  })

  it('never surfaces a room line status, which is only a copy of the header', async () => {
    // `Reservation Room.reservation_status` is stamped from the header, so it is
    // identical on every line and cannot say which room is in house. Per-line state
    // comes from the line's Stay, in Rooms & rates.
    workspace.data = payload({
      rooms: [roomLine({ reservation_status: 'Checked In' })],
      allowed_transitions: ['Cancelled'],
    })

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).not.toContain('Checked In')
  })
})

describe('Reservation workspace history tab', () => {
  const entries = [
    {
      name: 'LOG-2',
      changed_by: 'agent@hospitality-pms.invalid',
      changed_at: '2026-08-02 11:15:00',
      from_status: 'Confirmed',
      to_status: 'Guaranteed',
      reason: 'Card taken over the phone',
      details: { room_type: 'DLX', assigned_room: 'DOHA01-405', nights: 2, rate_plan: 'BAR', waived: false },
    },
    {
      name: 'LOG-1',
      changed_by: 'Administrator',
      changed_at: '2026-07-20 09:30:00',
      from_status: null,
      to_status: 'Tentative',
      reason: null,
      details: {},
    },
  ]

  it('fetches the log when the tab is opened, and not before', async () => {
    const { wrapper } = await mountWorkspace()

    expect(history.fetch).not.toHaveBeenCalled()

    await tabButton(wrapper, 'History').trigger('click')
    await flush(wrapper)

    expect(history.fetch).toHaveBeenCalledWith({ reservation: RES })
  })

  it('renders the transition, who, when and why', async () => {
    history.data = historyPayload(entries)

    const { wrapper } = await mountWorkspace({ query: { tab: 'history' } })
    const panel = visiblePanel(wrapper).text()

    expect(panel).toContain("The booking's own record. It is written by the server and cannot be edited.")
    expect(panel).toContain('Confirmed → Guaranteed')
    expect(panel).toContain('agent@hospitality-pms.invalid')
    expect(panel).toContain('02 Aug 2026')
    expect(panel).toContain('Card taken over the phone')
    // The first record of a booking has nothing to move from.
    expect(panel).toContain('Created')
  })

  it('renders the detail keys as labelled pairs, never as a blob', async () => {
    history.data = historyPayload(entries)

    const { wrapper } = await mountWorkspace({ query: { tab: 'history' } })
    const panel = visiblePanel(wrapper)

    expect(panel.text()).toContain('Room type: DLX')
    expect(panel.text()).toContain('Nights: 2')
    expect(panel.text()).toContain('Assigned room: DOHA01-405')
    // No JSON reaches the DOM, and no unresolved translation key either.
    expect(panel.html()).not.toContain('{"')
    expect(panel.html()).not.toContain('page.arrivals.room_type')
  })

  it('drops a nested detail rather than printing it', async () => {
    history.data = historyPayload([
      {
        ...entries[0],
        details: { fields: ['booking_source'], nested: { secret: 'do not print me' } },
      },
    ])

    const { wrapper } = await mountWorkspace({ query: { tab: 'history' } })

    expect(wrapper.html()).not.toContain('do not print me')
    expect(wrapper.html()).not.toContain('[object Object]')
    expect(visiblePanel(wrapper).text()).toContain('booking_source')
  })

  it('offers no way to change the record', async () => {
    history.data = historyPayload(entries)

    const { wrapper } = await mountWorkspace({ query: { tab: 'history' } })
    const panel = visiblePanel(wrapper)

    expect(panel.findAll('textarea')).toHaveLength(0)
    expect(panel.findAll('button').map((button) => button.text().trim())).not.toContain('Save changes')
  })

  it('reports an empty log as empty, not as a failure', async () => {
    history.data = historyPayload([])

    const { wrapper } = await mountWorkspace({ query: { tab: 'history' } })

    expect(visiblePanel(wrapper).text()).toContain('Nothing has been recorded against this booking yet.')
  })

  it('reports a permission failure on the log without a retry', async () => {
    history.error = { status: 403, exc_type: 'PermissionError', message: 'Not allowed' }

    const { wrapper } = await mountWorkspace({ query: { tab: 'history' } })
    const panel = visiblePanel(wrapper)

    expect(panel.text()).toContain('Not permitted')
    expect(buttonsWithText(wrapper, 'Retry')).toHaveLength(0)
  })
})

describe('Reservation workspace in Arabic', () => {
  it('renders mirrored, with the catalogue Arabic and no physical direction', async () => {
    useArabic()

    const { wrapper } = await mountWorkspace()

    expect(document.documentElement.getAttribute('dir')).toBe('rtl')

    const labels = wrapper.findAll('[role="tab"]').map((tab) => tab.text().trim())

    expect(labels[0]).toBe('نظرة عامة')
    expect(labels[5]).toBe('السجل')
    // Every key resolved: an unknown key renders as itself.
    expect(wrapper.text()).not.toContain('page.reservation.')
  })

  it('moves forward with ArrowLeft, the way the tabs are laid out', async () => {
    useArabic()

    const { wrapper, router } = await mountWorkspace()

    await wrapper.find('[role="tablist"]').trigger('keydown', { key: 'ArrowLeft' })
    await flush(wrapper)

    expect(router.currentRoute.value.query.tab).toBe('rooms')
  })
})
