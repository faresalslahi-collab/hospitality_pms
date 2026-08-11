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

import { defaultStayRange, nextDay, operationalDate } from './operationalDate.js'

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
