/**
 * The date-only rule, checked in seven timezones.
 *
 * A hotel's booking dates are date-only values: `2026-08-12` is the twelfth of
 * August at that property, not an instant, and it must survive a round trip
 * through the client unchanged from Auckland to Honolulu. Before 16.7.2 it did
 * not — `toServerDate` parsed the string as UTC midnight and read its local parts
 * back, so at any negative offset an arrival moved back a night.
 *
 * The defect was a property of the *runtime's* zone, so the only honest way to
 * test it is to change the zone and run again. Node re-reads `process.env.TZ` on
 * each `Date` construction, which is what makes that possible in-process; the
 * zone is always restored, because a leaked TZ would quietly re-home every other
 * spec in this worker.
 *
 * These live in Vitest rather than beside the `operationalDate` Node checks for
 * one dull reason: `utils/format.js` imports the i18n helper through the `@`
 * alias, which plain Node cannot resolve.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { formatDate, formatDateTime, toServerDate } from '@/utils/format'

/**
 * Chosen for what they break: two negative offsets where the old code lost a
 * day, UTC itself where it accidentally worked (which is how the bug hid), a
 * half-hour offset, this bench's own zone, and the furthest offset there is.
 */
const ZONES = [
  'UTC',
  'America/New_York', // UTC-4/-5 — the offset that lost a day
  'America/Anchorage', // UTC-8/-9 — further west still
  'Pacific/Honolulu', // UTC-10, no DST
  'Asia/Kolkata', // UTC+5:30 — a half-hour offset
  'Asia/Qatar', // UTC+3 — this bench, where it never reproduced
  'Pacific/Kiritimati', // UTC+14 — the far end
]

const ORIGINAL_TZ = process.env.TZ

afterEach(() => {
  if (ORIGINAL_TZ === undefined) delete process.env.TZ
  else process.env.TZ = ORIGINAL_TZ
})

/** Run one assertion once per zone, naming the zone when it fails. */
function inEveryZone(assertion) {
  for (const zone of ZONES) {
    process.env.TZ = zone

    try {
      assertion(zone)
    } catch (error) {
      error.message = `[TZ=${zone}] ${error.message}`
      throw error
    }
  }
}

describe('toServerDate keeps a date-only value date-only', () => {
  it('returns a date-only string unchanged in every timezone', () => {
    inEveryZone(() => {
      expect(toServerDate('2026-08-12')).toBe('2026-08-12')
      expect(toServerDate('2026-01-01')).toBe('2026-01-01')
      // The boundaries the old bug moved across: month, year and leap day.
      expect(toServerDate('2026-09-01')).toBe('2026-09-01')
      expect(toServerDate('2027-01-01')).toBe('2027-01-01')
      expect(toServerDate('2028-02-29')).toBe('2028-02-29')
    })
  })

  it('narrows a datetime to its own day rather than converting it', () => {
    inEveryZone(() => {
      // 03:00 is the hour that crosses back over midnight at a negative offset,
      // which is why the night-audit window was the original victim.
      expect(toServerDate('2026-08-12 03:00:00')).toBe('2026-08-12')
      expect(toServerDate('2026-08-12T03:00:00')).toBe('2026-08-12')
      expect(toServerDate('2026-08-12 23:59:59')).toBe('2026-08-12')
    })
  })

  it('keeps the day a Date object was built for', () => {
    inEveryZone(() => {
      // Constructed from parts, so it is local midnight in whatever zone is
      // current — and its own day is what comes back.
      expect(toServerDate(new Date(2026, 7, 12))).toBe('2026-08-12')
      expect(toServerDate(new Date(2026, 11, 31, 23, 30))).toBe('2026-12-31')
    })
  })

  it('returns nothing for nothing — never today', () => {
    inEveryZone(() => {
      expect(toServerDate(null)).toBe(null)
      expect(toServerDate(undefined)).toBe(null)
      expect(toServerDate('')).toBe(null)
      expect(toServerDate('not a date')).toBe(null)
      expect(toServerDate(new Date('nonsense'))).toBe(null)
    })
  })

  it('survives the round trip the calendar actually performs', () => {
    // The live call site: the calendar opens on the property's business date and
    // sends it straight back as a filter. That is where the day used to vanish.
    inEveryZone(() => {
      const businessDate = '2026-08-12'

      expect(toServerDate(businessDate)).toBe(businessDate)
      expect(toServerDate(toServerDate(businessDate))).toBe(businessDate)
    })
  })

  it('still reproduces the original defect, so this file proves something', () => {
    // The old implementation, verbatim. If this ever stops failing, the runtime
    // has changed and every assertion above has quietly stopped testing anything.
    const brokenToServerDate = (date) => {
      const value = date instanceof Date ? date : new Date(date)
      const month = String(value.getMonth() + 1).padStart(2, '0')
      const day = String(value.getDate()).padStart(2, '0')

      return `${value.getFullYear()}-${month}-${day}`
    }

    process.env.TZ = 'America/New_York'

    expect(brokenToServerDate('2026-08-12')).toBe('2026-08-11')
    expect(toServerDate('2026-08-12')).toBe('2026-08-12')
  })
})

describe('formatDate reads a date-only value as that day', () => {
  it('never displays the day before, in any timezone', () => {
    inEveryZone(() => {
      // `Intl` formats in the local zone, so a UTC-midnight Date printed at a
      // negative offset shows the previous day. Every arrival and departure on
      // every board is rendered through this function.
      expect(formatDate('2026-08-12')).toContain('12')
      expect(formatDate('2026-08-12')).not.toContain('11')
      expect(formatDate('2026-01-01')).toContain('01 Jan 2026')
      expect(formatDate('2028-02-29')).toContain('29 Feb 2028')
    })
  })

  it('keeps the time on a datetime, rather than flattening it to midnight', () => {
    // `formatDateTime` renders audit trails through the same parser; narrowing a
    // timestamp to its day would print every one of them as 00:00.
    inEveryZone(() => {
      expect(formatDateTime('2026-08-12 14:30:00')).toContain('14:30')
      expect(formatDateTime('2026-08-12 14:30:00')).toContain('12')
      expect(formatDateTime('2026-08-12 00:05:00')).toContain('00:05')
    })
  })

  it('treats a zone-bearing value as the instant it is', () => {
    // A value that names its own offset is not a wall clock and is not ours to
    // reinterpret — the platform parser is correct for it.
    process.env.TZ = 'UTC'
    expect(formatDate('2026-08-12T22:00:00Z')).toContain('12')

    process.env.TZ = 'Pacific/Kiritimati' // UTC+14
    expect(formatDate('2026-08-12T22:00:00Z')).toContain('13')
  })

  it('formats a Date object as its own local day', () => {
    inEveryZone(() => {
      expect(formatDate(new Date(2026, 7, 12))).toContain('12')
    })
  })

  it('says nothing for nothing', () => {
    inEveryZone(() => {
      expect(formatDate(null)).toBe('')
      expect(formatDate('')).toBe('')
      expect(formatDate('not a date')).toBe('')
    })
  })
})
