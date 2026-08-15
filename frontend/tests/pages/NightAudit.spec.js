/**
 * Night Audit — the business-date close.
 *
 * The screen's contract is that it never claims more than the server said.
 * Three invariants carry this file:
 *
 *   - a step reads as complete only where the audit record carries the stamp the
 *     service wrote for it. The rail this replaces derived completion from
 *     `audit_status`, and because one status spans several steps it ticked
 *     "Mark no-shows" for a sweep that had never run. That regression has a test
 *     of its own below and must never come back;
 *   - the close is offered on the server's own `audit_status` and
 *     `blocking_count`, never on a rule re-derived here — and a refusal from the
 *     server draws no success state;
 *   - every button says what it will do. "Run" told an auditor at 3am nothing.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { flush, mountOperational, resetStores, stubProperty, stubSession, useArabic } from '../helpers'

const { current, start, review, noShows, postCharges, dueOuts, reconcile, close } = vi.hoisted(() => {
  const resource = () => ({ data: null, loading: false, error: null, fetch: vi.fn(), submit: vi.fn() })

  return {
    current: resource(),
    start: resource(),
    review: resource(),
    noShows: resource(),
    postCharges: resource(),
    dueOuts: resource(),
    reconcile: resource(),
    close: resource(),
  }
})

// The step model, the labels and the status themes stay real — they are what is
// under test. Only the network-bearing factories are replaced.
vi.mock('@/resources/nightAudit', async (importOriginal) => {
  const actual = await importOriginal()

  return {
    ...actual,
    nightAuditCurrentResource: () => current,
    startNightAuditResource: () => start,
    reviewNightAuditResource: () => review,
    markNoShowsResource: () => noShows,
    postRoomChargesResource: () => postCharges,
    markDueOutsResource: () => dueOuts,
    reconcileNightAuditResource: () => reconcile,
    closeNightAuditResource: () => close,
  }
})

const { default: NightAudit } = await import('@/pages/NightAudit.vue')
const { property } = await import('@/stores/property')

/**
 * An audit part-way through, as `night_audit.get_current` sends it.
 *
 * Start, review and no-shows carry their stamps; charges do not. That is the
 * shape the assertions below lean on: four steps behind, one in hand.
 */
function auditRecord(overrides = {}) {
  return {
    name: 'HPMS-NA-2026-00042',
    property: 'DOHA01',
    audit_status: 'Reviewing',
    business_date: '2026-08-11',
    next_business_date: '2026-08-12',
    started_on: '2026-08-12 03:01:00',
    review_completed_on: '2026-08-12 03:04:00',
    no_shows_completed_on: '2026-08-12 03:06:00',
    posting_completed_on: null,
    due_outs_completed_on: null,
    reconciliation_completed_on: null,
    closed_on: null,
    ...overrides,
  }
}

function payload(overrides = {}) {
  // `audit` is merged onto the record and applied last, so an override of one
  // stamp does not silently replace the whole audit with a partial one.
  const { audit, ...rest } = overrides

  return {
    property: 'DOHA01',
    exceptions: [],
    counts: {
      arrivals_expected: 14,
      arrivals_completed: 12,
      departures_expected: 9,
      departures_completed: 9,
      in_house_rooms: 15,
      rooms_charged: 15,
      charges_posted: 15,
      postings_failed: 0,
    },
    figures: {
      currency: 'QAR',
      room_revenue: 25230,
      payments_received: 24000,
      outstanding_balance: 1230,
      occupancy_percentage: 68.3,
      adr: 420.5,
      revpar: 287.2,
    },
    blocking_count: 0,
    ...rest,
    audit: auditRecord(audit || {}),
  }
}

/** One blocking exception row, as review raises them. */
function exceptionRow(overrides = {}) {
  return {
    name: 'row-1',
    type: 'Unresolved Arrival',
    severity: 'Blocking',
    description: 'HPMS-RES-2026-00014 has not arrived and has not been marked a no-show.',
    is_resolved: 0,
    ...overrides,
  }
}

/** The rail, as `{ stepKey: state }`. */
function rail(wrapper) {
  return Object.fromEntries(
    wrapper.findAll('[data-step]').map((li) => [li.attributes('data-step'), li.attributes('data-state')]),
  )
}

/** The one current-action card. */
function actionCard(wrapper) {
  return wrapper.find('section[aria-labelledby="night-audit-current-action"]')
}

function buttonsWithText(wrapper, text) {
  return wrapper.findAll('button').filter((button) => button.text().trim() === text)
}

/**
 * The confirmation dialog renders through a teleport, so it lands in
 * `document.body` rather than inside the mounted wrapper. These read the
 * document, which is also what a user's eyes and a screen reader would do.
 */
function dialogText() {
  return document.body.textContent || ''
}

async function clickInDialog(text) {
  const button = [...document.body.querySelectorAll('button')].find(
    (node) => node.textContent.trim() === text,
  )

  if (!button) throw new Error(`No dialog button labelled "${text}"`)

  button.click()
  await flush()
}

function mountAudit() {
  return mountOperational(NightAudit)
}

beforeEach(() => {
  resetStores()
  stubProperty({ property_name: 'Doha Grand Hotel' })
  stubSession(['Night Auditor'])

  for (const resource of [current, start, review, noShows, postCharges, dueOuts, reconcile, close]) {
    resource.data = null
    resource.loading = false
    resource.error = null
    resource.fetch.mockClear()
    resource.submit.mockClear().mockResolvedValue({})
  }

  current.data = payload()
  vi.spyOn(property, 'refresh').mockResolvedValue({})
})

describe('Night Audit header', () => {
  it('names the property, the date being closed and the date that follows', async () => {
    const wrapper = await mountAudit()
    const header = wrapper.find('section[aria-labelledby="night-audit-header"]')

    expect(header.text()).toContain('Doha Grand Hotel')
    expect(header.text()).toContain('Business date being closed')
    expect(header.text()).toContain('11 Aug 2026')
    expect(header.text()).toContain('Next business date')
    expect(header.text()).toContain('12 Aug 2026')
    expect(header.text()).toContain('Reviewing')
  })

  it('counts only the steps the server has evidence for', async () => {
    // start, review and no-shows are stamped. Charges, due-outs, reconcile and
    // close are not.
    const wrapper = await mountAudit()

    // "recorded complete", not "complete": the count is of server stamps, and a
    // stamp can sit ahead of the step the operator is on. The wording says what
    // is actually being counted rather than implying a journey through them.
    expect(wrapper.text()).toContain('3 of 7 steps recorded complete')
  })

  it('never presents the browser clock as the business date', async () => {
    current.data = payload({ audit: { business_date: '2026-07-04', next_business_date: '2026-07-05' } })

    const wrapper = await mountAudit()

    expect(wrapper.find('section[aria-labelledby="night-audit-header"]').text()).toContain('04 Jul 2026')
  })
})

describe('Night Audit progress rail', () => {
  it('marks completed, current and future steps distinctly', async () => {
    const wrapper = await mountAudit()

    expect(rail(wrapper)).toEqual({
      start: 'done',
      review: 'done',
      mark_no_shows: 'done',
      post_room_charges: 'current',
      mark_due_outs: 'pending',
      reconcile: 'pending',
      close: 'pending',
    })
  })

  it('does not tick a step just because the audit reached a later status', async () => {
    // The regression this rail exists to kill. The audit is Posting — charges
    // have been posted — but the no-show sweep was never run, so it carries no
    // stamp and must not read as complete.
    current.data = payload({
      audit: {
        audit_status: 'Posting',
        no_shows_completed_on: null,
        posting_completed_on: '2026-08-12 03:10:00',
      },
    })

    const wrapper = await mountAudit()

    expect(rail(wrapper).mark_no_shows).not.toBe('done')
    // Stamped, and ahead of the operator: real evidence, its own state.
    expect(rail(wrapper).post_room_charges).toBe('recorded')
    expect(wrapper.text()).toContain('3 of 7 steps recorded complete')
  })

  it('marks the close step blocked rather than pending when it cannot run', async () => {
    current.data = payload({
      audit: {
        audit_status: 'Ready to Close',
        posting_completed_on: '2026-08-12 03:10:00',
        due_outs_completed_on: '2026-08-12 03:12:00',
        reconciliation_completed_on: '2026-08-12 03:20:00',
      },
      exceptions: [exceptionRow()],
      blocking_count: 1,
    })

    const wrapper = await mountAudit()

    expect(rail(wrapper).close).toBe('blocked')
  })

  it('does not present a later completed step as progress already made', async () => {
    // Start, Review and Reconcile stamped; the no-show sweep never ran. The
    // reconcile stamp is true and stays visible, but it sits ahead of the
    // marker and must not read like the four steps behind it.
    current.data = payload({
      audit: {
        audit_status: 'Reviewing',
        no_shows_completed_on: null,
        posting_completed_on: null,
        due_outs_completed_on: null,
        reconciliation_completed_on: '2026-08-12 03:20:00',
      },
    })

    const wrapper = await mountAudit()
    const states = rail(wrapper)

    expect(states.review).toBe('done')
    expect(states.mark_no_shows).toBe('current')
    expect(states.reconcile).toBe('recorded')
    expect(states.reconcile).not.toBe('done')
  })

  it('names the out-of-sequence state in words too', async () => {
    current.data = payload({
      audit: {
        no_shows_completed_on: null,
        reconciliation_completed_on: '2026-08-12 03:20:00',
      },
    })

    const wrapper = await mountAudit()

    expect(wrapper.find('[data-step="reconcile"]').text()).toContain('Recorded earlier')
  })

  it('keeps every step in exactly one of the six states', async () => {
    current.data = payload({
      audit: {
        audit_status: 'Ready to Close',
        no_shows_completed_on: null,
        posting_completed_on: '2026-08-12 03:10:00',
        due_outs_completed_on: '2026-08-12 03:12:00',
        reconciliation_completed_on: '2026-08-12 03:20:00',
      },
      exceptions: [exceptionRow()],
      blocking_count: 1,
    })

    const wrapper = await mountAudit()
    const allowed = ['done', 'recorded', 'current', 'pending', 'blocked', 'closed']

    for (const state of Object.values(rail(wrapper))) {
      expect(allowed).toContain(state)
    }

    // The operator is on the sweep; everything stamped after it reads as
    // recorded rather than travelled.
    expect(rail(wrapper).mark_no_shows).toBe('current')
    expect(rail(wrapper).post_room_charges).toBe('recorded')
    expect(rail(wrapper).reconcile).toBe('recorded')
  })

  it('names each state in words, not only in colour', async () => {
    const wrapper = await mountAudit()
    const text = wrapper.find('[data-step="post_room_charges"]').text()

    expect(text).toContain('Current step')
    expect(wrapper.find('[data-step="review"]').text()).toContain('Complete')
  })
})

describe('Night Audit current action', () => {
  it('shows one card for the step in hand, with its position', async () => {
    const wrapper = await mountAudit()
    const card = actionCard(wrapper)

    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('Step 4 of 7')
    expect(card.text()).toContain('Post room charges')
    expect(card.text()).toContain("Post one night's room charge for every in-house stay.")
  })

  it('carries the server figures that bear on this step', async () => {
    const wrapper = await mountAudit()
    const card = actionCard(wrapper)

    expect(card.text()).toContain('In-house rooms')
    expect(card.text()).toContain('15')
    expect(card.text()).toContain('Postings failed')
  })

  it('labels the button for the action, never "Run"', async () => {
    const wrapper = await mountAudit()

    expect(actionCard(wrapper).find('button').text().trim()).toBe('Post room charges')
    // The old screen's seven identical buttons. Exact match, because
    // "Run reconciliation" is a legitimate label and this is not.
    expect(buttonsWithText(wrapper, 'Run')).toHaveLength(0)
  })

  it('uses each step\'s own wording as the audit advances', async () => {
    const cases = [
      [{ started_on: null, review_completed_on: null, no_shows_completed_on: null }, 'Start audit'],
      [{ review_completed_on: null, no_shows_completed_on: null }, 'Review day'],
      [{ no_shows_completed_on: null }, 'Mark no-shows'],
      [{ posting_completed_on: '2026-08-12 03:10:00' }, 'Mark due-outs'],
      [
        { posting_completed_on: '2026-08-12 03:10:00', due_outs_completed_on: '2026-08-12 03:12:00' },
        'Run reconciliation',
      ],
    ]

    for (const [audit, label] of cases) {
      current.data = payload({ audit })

      const wrapper = await mountAudit()

      expect(actionCard(wrapper).find('button').text().trim()).toBe(label)
    }
  })

  it('runs the step it is showing, then re-reads the server', async () => {
    const wrapper = await mountAudit()

    current.fetch.mockClear()
    await actionCard(wrapper).find('button').trigger('click')

    expect(postCharges.submit).toHaveBeenCalledWith({ audit: 'HPMS-NA-2026-00042' })
    expect(current.fetch).toHaveBeenCalled()
  })
})

describe('Night Audit blockers', () => {
  it('says plainly that the day cannot close, and lists what to do', async () => {
    current.data = payload({ exceptions: [exceptionRow()], blocking_count: 1 })

    const wrapper = await mountAudit()

    expect(wrapper.text()).toContain('Night Audit cannot be closed yet')
    expect(wrapper.text()).toContain('Unresolved Arrival')
    expect(wrapper.text()).toContain('has not been marked a no-show')
  })

  it('says so positively when there is nothing blocking', async () => {
    const wrapper = await mountAudit()

    expect(wrapper.text()).toContain('No blocking exceptions')
    expect(wrapper.text()).not.toContain('Night Audit cannot be closed yet')
  })

  it('keeps warnings and resolved rows out of the blocking list', async () => {
    current.data = payload({
      exceptions: [
        exceptionRow({ name: 'w1', severity: 'Warning', type: 'Late Checkout' }),
        exceptionRow({ name: 'r1', is_resolved: 1, type: 'Settled Arrival' }),
      ],
      blocking_count: 0,
    })

    const wrapper = await mountAudit()

    expect(wrapper.text()).toContain('No blocking exceptions')
    expect(wrapper.text()).toContain('Late Checkout')
    expect(wrapper.text()).toContain('Resolved')
  })
})

describe('Night Audit close', () => {
  /** Everything stamped, server says Ready to Close, nothing blocking. */
  function readyToClose(overrides = {}) {
    return payload({
      audit: {
        audit_status: 'Ready to Close',
        posting_completed_on: '2026-08-12 03:10:00',
        due_outs_completed_on: '2026-08-12 03:12:00',
        reconciliation_completed_on: '2026-08-12 03:20:00',
      },
      ...overrides,
    })
  }

  it('makes the final step read differently from ordinary actions', async () => {
    current.data = readyToClose()

    const wrapper = await mountAudit()
    const card = actionCard(wrapper)

    expect(card.text()).toContain('Close business day')
    expect(card.text()).toContain('Closing will finalise 11 Aug 2026')
    expect(card.text()).toContain('advance the property business date to 12 Aug 2026')
    // Red, not the blue of an ordinary step.
    expect(card.classes()).toContain('border-outline-red-1')
  })

  it('never closes on the button alone: it opens a confirmation naming both dates', async () => {
    current.data = readyToClose()

    const wrapper = await mountAudit()

    await actionCard(wrapper).find('button').trigger('click')
    await flush()

    expect(close.submit).not.toHaveBeenCalled()
    expect(dialogText()).toContain('You are closing')
    expect(dialogText()).toContain('Next business date')

    await clickInDialog('Close business date')

    expect(close.submit).toHaveBeenCalledWith({ audit: 'HPMS-NA-2026-00042' })
  })

  it('refuses to offer the close while the server reports blockers', async () => {
    current.data = readyToClose({ exceptions: [exceptionRow()], blocking_count: 1 })

    const wrapper = await mountAudit()
    const card = actionCard(wrapper)

    expect(card.text()).toContain('Blocking exceptions must be resolved')
    expect(card.find('button').attributes('disabled')).toBeDefined()
  })

  it('explains a not-ready day differently from a blocked one', async () => {
    // Reconciliation ran but the server did not move the audit to Ready to
    // Close, and raised no exception. The operator is told to finish the steps,
    // not to go hunting for an exception that does not exist.
    current.data = payload({
      audit: {
        audit_status: 'Posting',
        posting_completed_on: '2026-08-12 03:10:00',
        due_outs_completed_on: '2026-08-12 03:12:00',
        reconciliation_completed_on: '2026-08-12 03:20:00',
      },
      blocking_count: 0,
    })

    const wrapper = await mountAudit()

    expect(actionCard(wrapper).text()).toContain('not ready to close yet')
    expect(actionCard(wrapper).text()).not.toContain('Blocking exceptions must be resolved')
  })

  it('shows the closed day and the new business date, and refreshes the property', async () => {
    current.data = readyToClose()
    close.submit.mockResolvedValue({ business_date: '2026-08-11', next_business_date: '2026-08-12' })

    const wrapper = await mountAudit()

    await actionCard(wrapper).find('button').trigger('click')
    await flush()
    await clickInDialog('Close business date')

    expect(wrapper.text()).toContain('Business day closed')
    expect(wrapper.text()).toContain('Current business date')
    // The sidebar's business date lives in this store; re-reading it is what
    // updates the rail and the Command Center without a browser reload.
    expect(property.refresh).toHaveBeenCalled()
    expect(current.fetch).toHaveBeenCalled()
  })

  it('draws no success state when the server refuses the close', async () => {
    current.data = readyToClose()
    close.submit.mockRejectedValue(new Error('Accounting changed after reconciliation.'))

    const wrapper = await mountAudit()

    await actionCard(wrapper).find('button').trigger('click')
    await flush()
    await clickInDialog('Close business date')

    expect(wrapper.text()).not.toContain('Business day closed')
    expect(dialogText()).toContain('Accounting changed after reconciliation.')
    expect(property.refresh).not.toHaveBeenCalled()
  })

  it('keeps the operator on the step when a step is refused', async () => {
    postCharges.submit.mockRejectedValue(new Error('Posting period is closed.'))

    const wrapper = await mountAudit()

    await actionCard(wrapper).find('button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Posting period is closed.')
    expect(actionCard(wrapper).text()).toContain('Step 4 of 7')
    // Re-read even on failure: a partial post changes the figures.
    expect(current.fetch).toHaveBeenCalled()
  })
})

describe('Night Audit daily summary', () => {
  it('keeps the figures, below the workflow', async () => {
    const wrapper = await mountAudit()
    const html = wrapper.html()

    expect(wrapper.text()).toContain('Daily summary')
    expect(wrapper.text()).toContain('Occupancy')
    expect(wrapper.text()).toContain('68.3%')
    expect(html.indexOf('night-audit-current-action')).toBeLessThan(html.indexOf('night-audit-summary'))
  })

  it('renders no zero in place of money the caller was not told', async () => {
    // The server splices the folio totals out for a caller without Guest Folio
    // read. "Outstanding balance 0.00" would read as "nothing is owed".
    const data = payload()
    delete data.figures.room_revenue
    delete data.figures.payments_received
    delete data.figures.outstanding_balance
    current.data = data

    const wrapper = await mountAudit()

    expect(wrapper.text()).not.toContain('Outstanding balance')
    expect(wrapper.text()).toContain('Occupancy')
  })
})

describe('Night Audit in Arabic', () => {
  beforeEach(() => useArabic())

  it('translates the workflow, the action and the blockers', async () => {
    current.data = payload({ exceptions: [exceptionRow()], blocking_count: 1 })

    const wrapper = await mountAudit()

    expect(wrapper.text()).toContain('تاريخ العمل التالي')
    expect(actionCard(wrapper).text()).toContain('ترحيل رسوم الغرف')
    expect(wrapper.text()).toContain('لا يمكن إغلاق التدقيق الليلي بعد')
  })

  it('names the out-of-sequence state in Arabic too', async () => {
    // Colour is never the only channel, and the words have to exist in both
    // locales or an Arabic session reads amber with no explanation.
    current.data = payload({
      audit: {
        no_shows_completed_on: null,
        reconciliation_completed_on: '2026-08-12 03:20:00',
      },
    })

    const wrapper = await mountAudit()

    expect(wrapper.find('[data-step="reconcile"]').text()).toContain('مُسجّل سابقاً')
  })

  it('expresses the rail logically, with no physical direction', async () => {
    const wrapper = await mountAudit()
    const html = wrapper.html()

    expect(html).not.toMatch(/\bml-\d|\bmr-\d|\btext-left\b|\btext-right\b/)
  })
})
