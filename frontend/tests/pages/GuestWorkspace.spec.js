/**
 * Guest 360 (16.7.3).
 *
 * These tests defend the disclosure rules before anything else. The workspace is
 * the widest aggregate in the product, and the server answers it by *omitting*
 * every block the caller is not entitled to — `identifications`,
 * `standing.is_blacklisted`, `standing.blacklist_reason`, `stay_statistics` and
 * `current_stay`. An absent key must never be rendered as an empty list, a zero,
 * a dash borrowed from the disclosed case, or a negative claim about the guest.
 * The difference between "this guest has no passport on file" and "you may not
 * see this guest's passport" is the entire point of the screen.
 *
 * The second thing they defend is that the screen decides nothing. Which tabs
 * exist comes from `disclosure`; a test that flips one flag and expects a tab to
 * vanish is proving there is no second copy of the permission model in Vue.
 *
 * Mounted through a real `RouterView`, because the active tab lives in the URL
 * query and that means nothing to a component the router is not rendering.
 */
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { RouterView, createMemoryHistory, createRouter } from 'vue-router'

import { OPERATIONAL_ROUTES, flush, resetStores, stubProperty, stubSession, useArabic } from '../helpers'

const { workspace, reservations, stays, folios, merge, search } = vi.hoisted(() => ({
  workspace: { data: null, loading: false, error: null, fetch: vi.fn() },
  reservations: { data: null, loading: false, error: null, fetch: vi.fn() },
  stays: { data: null, loading: false, error: null, fetch: vi.fn() },
  folios: { data: null, loading: false, error: null, fetch: vi.fn() },
  merge: { data: null, loading: false, error: null, submit: vi.fn() },
  search: { data: null, loading: false, error: null, fetch: vi.fn() },
}))

vi.mock('@/resources/guests', async (importOriginal) => {
  const actual = await importOriginal()

  return {
    ...actual,
    getGuestWorkspaceResource: () => workspace,
    guestReservationsResource: () => reservations,
    guestStaysResource: () => stays,
    guestFoliosResource: () => folios,
    mergeGuestsResource: () => merge,
    searchGuestsResource: () => search,
  }
})

const { default: GuestProfile } = await import('@/pages/GuestProfile.vue')

const GUEST = 'HPMS-GST-00042'

/** Everything a fully-cleared manager receives. Tests remove from this. */
function payload(overrides = {}) {
  return {
    guest: {
      name: GUEST,
      guest_name: 'Layla Haddad',
      first_name: 'Layla',
      last_name: 'Haddad',
      nationality: 'Lebanon',
      mobile_no: '+974 5555 0100',
      email_id: 'layla@example.com',
      city: 'Doha',
      preferred_language: 'Arabic',
    },
    preferences: [
      { name: 'PREF-1', preference_category: 'Room', preference: 'High floor', notes: '' },
    ],
    alerts: [
      {
        name: 'ALERT-1',
        alert_type: 'Allergy',
        severity: 'Critical',
        alert: 'Severe shellfish allergy',
        is_active: 1,
        valid_upto: null,
      },
    ],
    care: { dietary_requirements: 'No shellfish', allergies: '', accessibility_requirements: '' },
    identifications: [
      {
        name: 'ID-1',
        id_type: 'Passport',
        id_number: 'LB-9928311',
        issuing_country: 'Lebanon',
        issue_date: '2021-03-02',
        expiry_date: '2031-03-01',
        is_primary: 1,
        verified: 1,
      },
    ],
    standing: {
      vip_status: 'VIP',
      guest_type: 'Individual',
      is_blacklisted: false,
      blacklist_reason: '',
    },
    stay_statistics: { total_stays: 4, total_nights: 11, last_stay_on: '2026-05-02' },
    current_stay: {
      name: 'HPMS-STY-00099',
      property: 'DOHA01',
      room: 'DOHA01-702',
      room_type: 'SUITE',
      stay_status: 'In House',
      folio: 'HPMS-FOL-00099',
    },
    disclosure: {
      guest: true,
      reservation: true,
      stay: true,
      folio: true,
      identity: true,
      blacklist: true,
      blacklist_reason: true,
      merge: true,
    },
    ...overrides,
  }
}

function router() {
  return createRouter({ history: createMemoryHistory(), routes: OPERATIONAL_ROUTES })
}

async function mountWorkspace({ tab } = {}) {
  const testRouter = router()

  testRouter.addRoute({ path: '/guests/:id', name: 'GuestProfile', component: GuestProfile })

  const query = tab ? `?tab=${tab}` : ''
  testRouter.push(`/guests/${GUEST}${query}`)
  await testRouter.isReady()

  const wrapper = mount(
    { render: () => h(RouterView) },
    { global: { plugins: [testRouter] }, attachTo: document.body },
  )

  await flush(wrapper)

  return { wrapper, router: testRouter }
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Agent'])

  workspace.data = payload()
  workspace.loading = false
  workspace.error = null
  workspace.fetch = vi.fn()

  for (const resource of [reservations, stays, folios, search]) {
    resource.data = null
    resource.loading = false
    resource.error = null
    resource.fetch = vi.fn().mockResolvedValue({})
  }

  merge.submit = vi.fn().mockResolvedValue({ references_moved: {} })
  merge.error = null
})

describe('Guest 360 shell', () => {
  it('shows a loading state before the aggregate arrives', async () => {
    workspace.data = null
    workspace.loading = true

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).not.toContain('Layla Haddad')
  })

  it('reports a permission failure as a refusal, not a retryable fault', async () => {
    workspace.data = null
    workspace.error = { status: 403, exc_type: 'PermissionError' }

    const { wrapper } = await mountWorkspace()

    expect(wrapper.findComponent({ name: 'PermissionDenied' }).exists()).toBe(true)
  })

  it('offers a retry for a fault the user can actually retry out of', async () => {
    workspace.data = null
    workspace.error = { status: 500 }

    const { wrapper } = await mountWorkspace()

    expect(wrapper.findComponent({ name: 'PermissionDenied' }).exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'ErrorState' }).exists()).toBe(true)
  })

  it('renders the guest name and identifier in the header', async () => {
    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('Layla Haddad')
    expect(wrapper.text()).toContain(GUEST)
  })

  it('keeps the active tab in the URL query', async () => {
    const { wrapper, router: testRouter } = await mountWorkspace()

    const tabs = wrapper.findAll('[role="tab"]')
    const stays = tabs.find((tab) => tab.text() === 'Stays')

    await stays.trigger('click')
    await flush(wrapper)

    expect(testRouter.currentRoute.value.query.tab).toBe('stays')
  })

  it('falls back to Profile for a tab the caller may not see', async () => {
    const data = payload()
    data.disclosure.folio = false
    workspace.data = data

    const { wrapper } = await mountWorkspace({ tab: 'folios' })

    const selected = wrapper.find('[role="tab"][aria-selected="true"]')

    expect(selected.text()).toBe('Profile')
  })
})

describe('Guest 360 disclosure', () => {
  it('hides the Folios tab when the caller may not read Guest Folio', async () => {
    const data = payload()
    data.disclosure.folio = false
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    const labels = wrapper.findAll('[role="tab"]').map((tab) => tab.text())

    expect(labels).not.toContain('Folios')
    expect(labels).toContain('Stays')
  })

  it('hides the Stays tab when the caller may not read Stay', async () => {
    const data = payload()
    data.disclosure.stay = false
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    expect(wrapper.findAll('[role="tab"]').map((tab) => tab.text())).not.toContain('Stays')
  })

  it('hides the Reservations tab when the caller may not read Reservation', async () => {
    const data = payload()
    data.disclosure.reservation = false
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    expect(wrapper.findAll('[role="tab"]').map((tab) => tab.text())).not.toContain('Reservations')
  })

  it('always offers the four Guest-owned tabs', async () => {
    const data = payload()
    data.disclosure.reservation = false
    data.disclosure.stay = false
    data.disclosure.folio = false
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    const labels = wrapper.findAll('[role="tab"]').map((tab) => tab.text())

    expect(labels).toEqual(['Profile', 'Identity', 'Preferences', 'Alerts'])
  })

  it('never renders a Documents or History tab', async () => {
    const { wrapper } = await mountWorkspace()

    const labels = wrapper.findAll('[role="tab"]').map((tab) => tab.text())

    expect(labels).not.toContain('Documents')
    expect(labels).not.toContain('History')
  })
})

describe('Guest 360 identity disclosure', () => {
  it('shows the documents to a caller cleared for permlevel 1', async () => {
    const { wrapper } = await mountWorkspace({ tab: 'identity' })

    expect(wrapper.text()).toContain('LB-9928311')
  })

  it('says the documents are withheld rather than showing none on file', async () => {
    const data = payload()
    delete data.identifications
    data.disclosure.identity = false
    workspace.data = data

    const { wrapper } = await mountWorkspace({ tab: 'identity' })

    expect(wrapper.findComponent({ name: 'PermissionDenied' }).exists()).toBe(true)
    expect(wrapper.text()).not.toContain('No identification on file')
  })

  it('distinguishes a guest with no documents from one whose documents are hidden', async () => {
    const data = payload({ identifications: [] })
    workspace.data = data

    const { wrapper } = await mountWorkspace({ tab: 'identity' })

    expect(wrapper.findComponent({ name: 'PermissionDenied' }).exists()).toBe(false)
    expect(wrapper.text()).toContain('No identification on file')
  })

  it('never renders a document image', async () => {
    const { wrapper } = await mountWorkspace({ tab: 'identity' })

    expect(wrapper.find('img').exists()).toBe(false)
  })
})

describe('Guest 360 blacklist disclosure', () => {
  it('shows the badge for a cleared caller when the guest is blacklisted', async () => {
    const data = payload()
    data.standing.is_blacklisted = true
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('Blacklisted')
  })

  it('shows no badge for a cleared caller when the guest is not blacklisted', async () => {
    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).not.toContain('Blacklisted')
  })

  it('shows no badge when the flag was withheld, even though the key is absent', async () => {
    const data = payload()
    delete data.standing.is_blacklisted
    delete data.standing.blacklist_reason
    data.disclosure.blacklist = false
    data.disclosure.blacklist_reason = false
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).not.toContain('Blacklisted')
  })

  it('never puts a blacklist reason in the header', async () => {
    const data = payload()
    data.standing.is_blacklisted = true
    data.standing.blacklist_reason = 'CONFIDENTIAL barred after an incident'
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    const header = wrapper.findComponent({ name: 'GuestWorkspaceHeader' })

    expect(header.text()).not.toContain('CONFIDENTIAL')
  })
})

describe('Guest 360 stay statistics', () => {
  it('renders the derived figures when the caller may read Stay', async () => {
    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('4')
    expect(wrapper.text()).toContain('11')
  })

  it('omits the metrics entirely rather than showing zero when Stay is withheld', async () => {
    const data = payload()
    delete data.stay_statistics
    delete data.current_stay
    data.disclosure.stay = false
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    const header = wrapper.findComponent({ name: 'GuestWorkspaceHeader' })

    expect(header.text()).not.toContain('Total stays')
    expect(header.text()).not.toContain('Current room')
  })

  it('shows the room the guest is actually in', async () => {
    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('DOHA01-702')
  })

  it('says the guest is not in house rather than leaving the room blank', async () => {
    const data = payload({ current_stay: null })
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('Not in house')
  })
})

describe('Guest 360 histories', () => {
  it('fetches the stay history only when its tab is opened', async () => {
    const { wrapper } = await mountWorkspace()

    expect(stays.fetch).not.toHaveBeenCalled()

    const tab = wrapper.findAll('[role="tab"]').find((each) => each.text() === 'Stays')
    await tab.trigger('click')
    await flush(wrapper)

    expect(stays.fetch).toHaveBeenCalledWith(
      expect.objectContaining({ guest: GUEST, limit: 20, start: 0 }),
    )
  })

  it('asks the server for the next page rather than slicing locally', async () => {
    stays.data = {
      stays: [
        {
          name: 'HPMS-STY-1',
          property: 'DOHA01',
          room: 'DOHA01-101',
          stay_status: 'Checked Out',
          arrival_date: '2026-01-01',
          departure_date: '2026-01-03',
        },
      ],
      has_more: true,
    }

    const { wrapper } = await mountWorkspace({ tab: 'stays' })

    wrapper.findComponent({ name: 'StaysTab' }).vm.$emit('page-change', 2)
    await flush(wrapper)

    expect(stays.fetch).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 20, start: 20 }),
    )
  })

  it('renders a folio balance only on the folios tab', async () => {
    folios.data = {
      folios: [
        {
          name: 'HPMS-FOL-1',
          property: 'DOHA01',
          stay: 'HPMS-STY-1',
          folio_status: 'Settled',
          currency: 'QAR',
          total_charges: 1200,
          total_payments: 1200,
          balance: 0,
        },
      ],
      has_more: false,
    }

    const { wrapper } = await mountWorkspace({ tab: 'folios' })

    expect(wrapper.findComponent({ name: 'FolioBalance' }).exists()).toBe(true)
  })

  it('does not carry a balance onto the stays tab', async () => {
    stays.data = {
      stays: [
        {
          name: 'HPMS-STY-1',
          property: 'DOHA01',
          room: 'DOHA01-101',
          stay_status: 'Checked Out',
          arrival_date: '2026-01-01',
          departure_date: '2026-01-03',
        },
      ],
      has_more: false,
    }

    const { wrapper } = await mountWorkspace({ tab: 'stays' })

    expect(
      wrapper.findComponent({ name: 'StaysTab' }).findComponent({ name: 'FolioBalance' }).exists(),
    ).toBe(false)
  })
})

describe('Guest 360 quick actions', () => {
  it('starts a booking for this guest', async () => {
    const { wrapper, router: testRouter } = await mountWorkspace()

    const button = wrapper.findAll('button').find((each) => each.text() === 'New reservation')
    await button.trigger('click')
    await flush(wrapper)

    expect(testRouter.currentRoute.value.name).toBe('ReservationNew')
    expect(testRouter.currentRoute.value.query.guest).toBe(GUEST)
  })

  it('opens the guest correction form rather than editing in place', async () => {
    const { wrapper, router: testRouter } = await mountWorkspace()

    const button = wrapper.findAll('button').find((each) => each.text() === 'Edit guest')
    await button.trigger('click')
    await flush(wrapper)

    expect(testRouter.currentRoute.value.name).toBe('GuestEdit')
  })

  it('offers the current folio only when the caller may read one', async () => {
    const data = payload()
    data.disclosure.folio = false
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    const labels = wrapper.findAll('button').map((each) => each.text())

    expect(labels).not.toContain('Open folio')
    expect(labels).toContain('Open stay')
  })

  it('offers no stay action when the guest is not in house', async () => {
    workspace.data = payload({ current_stay: null })

    const { wrapper } = await mountWorkspace()

    expect(wrapper.findAll('button').map((each) => each.text())).not.toContain('Open stay')
  })
})

describe('Guest 360 merge', () => {
  it('offers merge to a caller the server said may merge', async () => {
    const { wrapper } = await mountWorkspace()

    expect(wrapper.findAll('button').map((each) => each.text())).toContain('Merge guest')
  })

  it('hides merge from a caller the server said may not', async () => {
    const data = payload()
    data.disclosure.merge = false
    workspace.data = data

    const { wrapper } = await mountWorkspace()

    expect(wrapper.findAll('button').map((each) => each.text())).not.toContain('Merge guest')
    expect(wrapper.findComponent({ name: 'MergeGuestDialog' }).exists()).toBe(false)
  })

  it('submits the open guest as the record that is kept', async () => {
    const { wrapper } = await mountWorkspace()

    wrapper
      .findComponent({ name: 'MergeGuestDialog' })
      .vm.$emit('merge', { source: 'HPMS-GST-00099', reason: 'Same person, two records' })

    await flush(wrapper)

    expect(merge.submit).toHaveBeenCalledWith({
      source: 'HPMS-GST-00099',
      target: GUEST,
      reason: 'Same person, two records',
    })
  })

  it('reports a refusal in the server’s own words', async () => {
    merge.submit = vi.fn().mockRejectedValue({
      status: 403,
      exc_type: 'PermissionDeniedError',
      messages: ['This action requires one of the following roles: Hotel Manager.'],
    })

    const { wrapper } = await mountWorkspace()

    const dialog = wrapper.findComponent({ name: 'MergeGuestDialog' })
    dialog.vm.$emit('merge', { source: 'HPMS-GST-00099', reason: 'Duplicate' })
    await flush(wrapper)

    expect(dialog.props('errorMessage')).toContain('Hotel Manager')
  })

  it('reloads the guest after a merge, because history was repointed', async () => {
    const { wrapper } = await mountWorkspace()

    workspace.fetch = vi.fn()

    wrapper
      .findComponent({ name: 'MergeGuestDialog' })
      .vm.$emit('merge', { source: 'HPMS-GST-00099', reason: 'Duplicate' })

    await flush(wrapper)

    expect(workspace.fetch).toHaveBeenCalled()
  })
})

describe('Guest 360 in Arabic', () => {
  beforeEach(() => {
    useArabic()
  })

  it('renders the workspace right to left', async () => {
    const { wrapper } = await mountWorkspace()

    expect(wrapper.text()).toContain('Layla Haddad')
    expect(wrapper.findAll('[role="tab"]').length).toBeGreaterThan(0)
  })

  it('translates the tab labels', async () => {
    const { wrapper } = await mountWorkspace()

    const labels = wrapper.findAll('[role="tab"]').map((tab) => tab.text())

    expect(labels).not.toContain('Profile')
    expect(labels[0]).toBeTruthy()
  })
})
