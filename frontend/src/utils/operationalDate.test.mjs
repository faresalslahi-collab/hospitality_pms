/**
 * Focused checks for the operational-date rule.
 *
 * There is no test runner configured for this frontend and adding one is not
 * this wave's business, so these are plain assertions run by Node:
 *
 *     yarn test
 *
 * The logic under test is deliberately pure and lives outside the components,
 * which is what makes that possible - and is also why Availability and New
 * Reservation cannot drift apart from WalkIn again.
 */
import assert from 'node:assert/strict'

import {
  currentCalendarDate,
  daysBetween,
  defaultStayRange,
  nextDay,
  operationalDate,
} from './operationalDate.js'

const iso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

const today = iso(new Date())
const cases = []
const check = (name, fn) => cases.push([name, fn])

check('the property business date is used, not the browser date', () => {
  // The Phase-1 scenario: the hotel is working the 8th, the browser says the 10th.
  assert.equal(operationalDate('2026-08-08'), '2026-08-08')
  assert.notEqual(operationalDate('2026-08-08'), today)
})

check('a datetime is narrowed to its business day', () => {
  assert.equal(operationalDate('2026-08-08 03:00:00'), '2026-08-08')
})

check('a Date object is read in local time, never UTC', () => {
  assert.equal(operationalDate(new Date(2026, 7, 8)), '2026-08-08')
})

check('no property context falls back to the browser date', () => {
  assert.equal(operationalDate(null), today)
  assert.equal(operationalDate(''), today)
  assert.equal(operationalDate(undefined), today)
})

check('departure is the night after arrival', () => {
  assert.equal(nextDay('2026-08-08'), '2026-08-09')
})

check('the day after crosses month, year and leap boundaries', () => {
  assert.equal(nextDay('2026-08-31'), '2026-09-01')
  assert.equal(nextDay('2026-12-31'), '2027-01-01')
  assert.equal(nextDay('2028-02-28'), '2028-02-29')
})

check('a form opens on tonight, on the property day', () => {
  assert.deepEqual(defaultStayRange('2026-08-08'), {
    arrival: '2026-08-08',
    departure: '2026-08-09',
  })
})

check('the calendar date is read in the property zone, not the runtime zone', () => {
  // 22:30 UTC on the 13th is already the 14th in Doha (+3) and still the 13th
  // in New York (-4). The property decides, whatever machine the browser is on.
  const instant = new Date('2026-08-13T22:30:00Z')

  assert.equal(currentCalendarDate('Asia/Qatar', instant), '2026-08-14')
  assert.equal(currentCalendarDate('America/New_York', instant), '2026-08-13')
  assert.equal(currentCalendarDate('Pacific/Kiritimati', instant), '2026-08-14')
  assert.equal(currentCalendarDate('UTC', instant), '2026-08-13')
})

check('the calendar date pads to a comparable YYYY-MM-DD', () => {
  // Compared against the business date as a string in one place, so a missing
  // zero would silently make January look like a lag.
  assert.equal(currentCalendarDate('UTC', new Date('2026-01-05T12:00:00Z')), '2026-01-05')
  assert.equal(currentCalendarDate('UTC', new Date('2028-02-29T12:00:00Z')), '2028-02-29')
})

check('an unknown zone is not fatal', () => {
  // A property whose zone has not been set falls back to the runtime, which is
  // the only thing left to fall back to, and still answers with a real date.
  assert.match(currentCalendarDate(null, new Date('2026-08-13T12:00:00Z')), /^\d{4}-\d{2}-\d{2}$/)
  assert.match(currentCalendarDate('', new Date('2026-08-13T12:00:00Z')), /^\d{4}-\d{2}-\d{2}$/)
})

check('the lag is counted in whole days, in either direction', () => {
  assert.equal(daysBetween('2026-08-08', '2026-08-11'), 3)
  assert.equal(daysBetween('2026-08-11', '2026-08-11'), 0)
  // A business date *ahead* of the calendar is not a lag; the caller decides
  // what to do with a negative, and it must not read as three days behind.
  assert.equal(daysBetween('2026-08-11', '2026-08-08'), -3)
})

check('the lag crosses months, years and a leap day without drifting', () => {
  assert.equal(daysBetween('2026-08-31', '2026-09-01'), 1)
  assert.equal(daysBetween('2026-12-31', '2027-01-01'), 1)
  assert.equal(daysBetween('2028-02-28', '2028-03-01'), 2)
})

check('a datetime is narrowed before the lag is counted', () => {
  assert.equal(daysBetween('2026-08-08 03:00:00', '2026-08-10'), 2)
})

check('a missing date is no lag at all, never a number', () => {
  assert.equal(daysBetween(null, '2026-08-10'), null)
  assert.equal(daysBetween('2026-08-10', undefined), null)
  assert.equal(daysBetween('not a date', '2026-08-10'), null)
})

let failed = 0

for (const [name, fn] of cases) {
  try {
    fn()
    console.log(`  ok    ${name}`)
  } catch (error) {
    failed += 1
    console.error(`  FAIL  ${name}\n        ${error.message}`)
  }
}

console.log(`\n${cases.length - failed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
