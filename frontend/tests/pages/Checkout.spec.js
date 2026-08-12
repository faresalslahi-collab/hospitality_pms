/**
 * Checkout, and what it may say to a caller who cannot read Guest Folio.
 *
 * The server omits the folio group — `folio`, `currency`, `total_charges`,
 * `total_payments`, `balance`, `related_folios`, `can_check_out` — for a caller
 * without Guest Folio read, and replaces every amount-bearing blocker with one
 * generic "cashier action" sentence (16.7.5-R1B). Ten roles hold Stay read
 * without Guest Folio read.
 *
 * That makes this page's contract two-sided, and both sides are defended here:
 *
 * *It must not crash.* Before R1B the template indexed `summary.data.blockers`
 * and `summary.data.related_folios` directly, so an omitted key would have thrown
 * and taken the whole screen down — for precisely the callers the redaction
 * exists to protect.
 *
 * *It must not lie.* No zero, no blank and no empty currency may stand in for a
 * withheld figure. "Balance QAR 0.00" reads as settled, which is the one thing an
 * undisclosed balance must never be allowed to say, and the city-ledger override
 * must not be offered on the strength of money the caller was not shown.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { flush, mountOperational, resetStores, stubProperty, stubSession, testRouter } from '../helpers'

const { summary, checkOut, reverse } = vi.hoisted(() => {
  const resource = () => ({ data: null, loading: false, error: null, fetch: vi.fn(), submit: vi.fn() })

  return { summary: resource(), checkOut: resource(), reverse: resource() }
})

vi.mock('@/resources/checkout', async (importOriginal) => {
  const actual = await importOriginal()

  return {
    ...actual,
    checkoutSummaryResource: () => summary,
    checkOutResource: () => checkOut,
    reverseCheckoutResource: () => reverse,
  }
})

const { default: Checkout } = await import('@/pages/Checkout.vue')

/** The summary as a Guest Folio reader receives it: everything, amounts included. */
function disclosed(overrides = {}) {
  return {
    stay: 'HPMS-STAY-2026-00037',
    guest_name: 'Stefan Novak',
    room: 'DOHA01-402',
    arrival_date: '2026-08-10',
    departure_date: '2026-08-11',
    folio: 'HPMS-FOL-2026-00073',
    currency: 'QAR',
    total_charges: 2521.5,
    total_payments: 0,
    balance: 2521.5,
    related_folios: [],
    blockers: ['The folio has an outstanding balance of 2521.5.'],
    blocker_kinds: ['outstanding_balance'],
    can_check_out: false,
    ...overrides,
  }
}

/**
 * The same stay as a caller without Guest Folio read receives it.
 *
 * Built by deleting the keys the server omits, rather than by setting them to
 * `null` — the whole point is that they are absent, and a `null` would let the
 * page's optional chaining pass a test that the real payload would fail.
 */
function undisclosed(overrides = {}) {
  const payload = disclosed(overrides)

  for (const field of [
    'folio',
    'currency',
    'total_charges',
    'total_payments',
    'balance',
    'related_folios',
    'can_check_out',
    'blocker_kinds',
  ]) {
    delete payload[field]
  }

  // The exact sentence `api/checkout.py::_abstract_blockers` emits. Kept in step
  // with it deliberately: a fixture that plants a superseded wording tests the
  // page against a server that no longer exists.
  payload.blockers = ['Checkout requires cashier action before this stay can depart.']

  return payload
}

async function mountCheckout() {
  const router = testRouter()
  router.push('/checkout/HPMS-STAY-2026-00037')
  await router.isReady()

  const wrapper = await mountOperational(Checkout, { router })
  await flush(wrapper)

  return wrapper
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Agent'])
  summary.data = null
  summary.error = null
  summary.loading = false
})

describe('Checkout with the folio disclosed', () => {
  beforeEach(() => {
    summary.data = disclosed()
  })

  it('shows the balance, the totals and the server-worded blocker', async () => {
    const wrapper = await mountCheckout()
    const text = wrapper.text()

    expect(text).toMatch(/2[,.]521[,.]5/)
    expect(text).toContain('The folio has an outstanding balance of 2521.5.')
  })

  it('links to the folio', async () => {
    const wrapper = await mountCheckout()

    expect(wrapper.html()).toContain('/folios/HPMS-FOL-2026-00073')
  })

  it('offers the city-ledger override when only money is in the way', async () => {
    const wrapper = await mountCheckout()

    expect(wrapper.text()).toContain('Check out on city ledger')
  })

  it('renders split folios and their balances', async () => {
    summary.data = disclosed({
      related_folios: [
        { name: 'HPMS-FOL-2026-00074', folio_type: 'Company', balance: 300, folio_status: 'Open' },
      ],
    })

    const wrapper = await mountCheckout()

    expect(wrapper.text()).toContain('HPMS-FOL-2026-00074')
    expect(wrapper.text()).toMatch(/300/)
  })
})

describe('Checkout without Guest Folio disclosure', () => {
  beforeEach(() => {
    summary.data = undisclosed()
  })

  it('renders the page instead of throwing on the absent keys', async () => {
    const wrapper = await mountCheckout()

    // The regression this file was written for: `summary.data.blockers.length`
    // and `summary.data.related_folios.length` used to be indexed directly.
    expect(wrapper.text()).toContain('Stefan Novak')
    expect(wrapper.text()).toContain('DOHA01-402')
  })

  it('shows the safe generic blocker so the operator knows checkout is blocked', async () => {
    const wrapper = await mountCheckout()

    expect(wrapper.text()).toContain('Checkout requires cashier action')
  })

  it('renders no amount anywhere on the page', async () => {
    const wrapper = await mountCheckout()
    const text = wrapper.text()

    expect(text).not.toMatch(/2[,.]521/)
    expect(text).not.toContain('2521.5')
  })

  it('renders no zero in place of the withheld balance', async () => {
    const wrapper = await mountCheckout()
    const text = wrapper.text()

    // The three money rows are dropped, not blanked. A "Balance" label with an
    // empty or zero value beside it is the lie this assertion exists to catch.
    expect(text).not.toContain('Total charges')
    expect(text).not.toContain('Total payments')
    expect(text).not.toContain('Balance')
  })

  it('keeps the operational detail rows', async () => {
    const wrapper = await mountCheckout()
    const text = wrapper.text()

    // Redaction, not outage: the Stay's own fields are this endpoint's to show.
    expect(text).toContain('HPMS-STAY-2026-00037')
    expect(text).toContain('Arrival')
    expect(text).toContain('Departure')
  })

  it('offers no folio link, because it was not told which folio', async () => {
    const wrapper = await mountCheckout()

    expect(wrapper.html()).not.toContain('/folios/')
  })

  it('does not offer the city-ledger override', async () => {
    const wrapper = await mountCheckout()

    // It needs a manager role the server will refuse this caller anyway, and
    // deciding it client-side would need the balance they were not shown. A
    // button that cannot work is worse than no button.
    expect(wrapper.text()).not.toContain('Check out on city ledger')
  })

  it('still disables Check out while the blocker stands', async () => {
    const wrapper = await mountCheckout()

    const button = wrapper
      .findAll('button')
      .find((candidate) => candidate.text().trim() === 'Check out')

    expect(button.attributes('disabled')).toBeDefined()
  })

  it('shows no split-folio block', async () => {
    const wrapper = await mountCheckout()

    expect(wrapper.text()).not.toContain('Related folios')
  })
})

/**
 * Reverse checkout: the standing-invoice signal without the invoice names.
 *
 * `standing_invoices` is a list of Sales Invoice names and is withheld from a
 * caller without Sales Invoice read — which, on this app's permission setup, is
 * every role. The count carries the operational fact on its own, because the
 * note beside it is worded hypothetically ("any submitted invoice"), so without
 * the count an operator cannot tell whether one actually stands.
 */
describe('Checkout reverse result', () => {
  beforeEach(() => {
    summary.data = disclosed()
  })

  async function reverseWith(result) {
    reverse.submit = vi.fn().mockResolvedValue(result)

    const wrapper = await mountCheckout()

    wrapper.vm.reverseReason = 'guest returned'
    await wrapper.vm.doReverse()
    await flush(wrapper)

    return wrapper
  }

  it('reports how many invoices stand without naming them', async () => {
    const wrapper = await reverseWith({
      stay: 'HPMS-STAY-2026-00037',
      note: 'Any submitted invoice is left standing and must be handled by finance.',
      standing_invoice_count: 2,
      disclosure: { standing_invoices: false },
    })

    const text = wrapper.text()

    expect(text).toContain('2 submitted invoice(s) are left standing for finance.')
    expect(text).not.toContain('ACC-SINV')
  })

  it('names them for a caller entitled to the names', async () => {
    const wrapper = await reverseWith({
      stay: 'HPMS-STAY-2026-00037',
      note: 'Any submitted invoice is left standing and must be handled by finance.',
      standing_invoice_count: 1,
      standing_invoices: ['ACC-SINV-2026-00001'],
      disclosure: { standing_invoices: true },
    })

    expect(wrapper.text()).toContain('ACC-SINV-2026-00001')
  })

  it('says nothing about standing invoices when none stand', async () => {
    const wrapper = await reverseWith({
      stay: 'HPMS-STAY-2026-00037',
      note: 'Any submitted invoice is left standing and must be handled by finance.',
      standing_invoice_count: 0,
      disclosure: { standing_invoices: false },
    })

    // A zero count is a real answer, and it must not be announced as a warning.
    expect(wrapper.text()).not.toContain('left standing for finance')
  })
})

describe('Checkout without disclosure when nothing blocks departure', () => {
  it('reports no blockers and enables Check out', async () => {
    // A settled folio: the server sends an empty blocker list, and an
    // undisclosed caller sees the same emptiness rather than a fabricated one.
    summary.data = undisclosed()
    summary.data.blockers = []

    const wrapper = await mountCheckout()

    const button = wrapper
      .findAll('button')
      .find((candidate) => candidate.text().trim() === 'Check out')

    expect(button.attributes('disabled')).toBeUndefined()
  })
})
