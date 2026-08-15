/**
 * Property context indicator, and the Night Audit lag it now reports.
 *
 * The rail is the one place the business date lives. That makes it the only
 * honest place to say the business date has fallen behind the real one — a date
 * shown on its own, with no gap named, reads as current, and a desk that
 * believes it is working today's day will post charges into a closed one.
 *
 * The warning reports the gap. It does not close it and must not appear to:
 * only the Night Audit service moves a business date forward, and nothing here
 * touches it.
 *
 * The clock is pinned in every test that depends on it. Only `Date` is faked;
 * faking timers as well would stall Vue's own scheduling.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mountOperational, resetStores, stubProperty, stubSession, useArabic } from '../helpers'

const { default: PropertySelector } = await import('@/components/PropertySelector.vue')

/** 22:30 UTC on the 13th — already Friday the 14th in Doha (+3). */
const NOW = '2026-08-13T22:30:00Z'

function pin(instant = NOW) {
  vi.setSystemTime(new Date(instant))
}

beforeEach(() => {
  resetStores()
  stubSession(['Front Office Agent'])
  vi.useFakeTimers({ toFake: ['Date'] })
  pin()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Property context indicator', () => {
  it('keeps the business date exactly where it was', async () => {
    stubProperty({ business_date: '2026-08-14' })

    const wrapper = await mountOperational(PropertySelector)

    expect(wrapper.text()).toContain('Doha Grand')
    expect(wrapper.text()).toContain('Business date')
    expect(wrapper.text()).toContain('14 Aug 2026')
  })

  it('says nothing about a lag when the audit is up to date', async () => {
    stubProperty({ business_date: '2026-08-14' })

    const wrapper = await mountOperational(PropertySelector)

    expect(wrapper.text()).not.toContain('Night Audit pending')
  })
})

describe('Night Audit lag warning', () => {
  it('names the gap in days when the business date is behind', async () => {
    // Working the 11th while the property's calendar says the 14th.
    stubProperty({ business_date: '2026-08-11' })

    const wrapper = await mountOperational(PropertySelector)

    expect(wrapper.text()).toContain('Night Audit pending · 3 days behind')
  })

  it('counts one day as one day', async () => {
    stubProperty({ business_date: '2026-08-13' })

    const wrapper = await mountOperational(PropertySelector)

    expect(wrapper.text()).toContain('Night Audit pending · 1 day behind')
  })

  it('measures the lag against the property zone, not the runtime', async () => {
    // The same instant is still the 13th in New York, so a property working the
    // 13th there is level — while a Doha property on the same date is a day
    // behind. A warning computed from the browser's zone could not tell them
    // apart, and would raise a false alarm on one of them.
    stubProperty({ name: 'NYC01', time_zone: 'America/New_York', business_date: '2026-08-13' })

    const wrapper = await mountOperational(PropertySelector)

    expect(wrapper.text()).not.toContain('Night Audit pending')
  })

  it('stays quiet when the business date is ahead of the calendar', async () => {
    // A property mid-audit can carry tomorrow's date. That is not a lag, and
    // "-1 days behind" would be a nonsense the desk cannot act on.
    stubProperty({ business_date: '2026-08-20' })

    const wrapper = await mountOperational(PropertySelector)

    expect(wrapper.text()).not.toContain('Night Audit pending')
    expect(wrapper.text()).not.toContain('-')
  })

  it('says nothing at all before the property context has loaded', async () => {
    const wrapper = await mountOperational(PropertySelector)

    expect(wrapper.text()).toBe('')
  })

  it('changes nothing about the business date it sits beside', async () => {
    // The warning is a report. The date it qualifies is the server's and is
    // rendered exactly as it arrived.
    stubProperty({ business_date: '2026-08-11' })

    const wrapper = await mountOperational(PropertySelector)

    expect(wrapper.text()).toContain('11 Aug 2026')
    expect(wrapper.text()).not.toContain('14 Aug 2026')
  })
})

describe('Night Audit lag warning in Arabic', () => {
  beforeEach(() => useArabic())

  it('takes the dual form for two days, which English does not have', async () => {
    stubProperty({ business_date: '2026-08-12' })

    const wrapper = await mountOperational(PropertySelector)

    // يومين, not "2 أيام": Arabic has a form for exactly two, and substituting a
    // numeral into the plural would be wrong in a way a numeral cannot fix.
    // Asserted on the phrase, not on the digit — the business date beside it is
    // full of digits and says nothing about grammar.
    expect(wrapper.text()).toContain('متأخر يومين')
    expect(wrapper.text()).not.toContain('متأخر 2')
  })

  it('takes the plural form for three', async () => {
    stubProperty({ business_date: '2026-08-11' })

    const wrapper = await mountOperational(PropertySelector)

    expect(wrapper.text()).toContain('أيام')
  })

  it('takes the singular form for one', async () => {
    stubProperty({ business_date: '2026-08-13' })

    const wrapper = await mountOperational(PropertySelector)

    expect(wrapper.text()).toContain('يوماً واحداً')
  })
})
