/**
 * The operating day, for screens that have to pick a default date.
 *
 * A hotel's day is not the calendar's. A property that has not yet run its
 * Night Audit is still working the 8th while every browser in the building
 * says the 10th, and a screen that defaults from `new Date()` opens on a day
 * the hotel has already closed - or has not reached.
 *
 * WalkIn.vue already read the business date from its server context. This is
 * the same rule as a shared function, so Availability and New Reservation
 * cannot drift from it again, and so it can be exercised on its own.
 *
 * Only the *default* is decided here. Nothing stops an agent typing a date in
 * March; that is a legitimate booking, and these functions never see it.
 */

/** ISO `YYYY-MM-DD` for a Date, in local time (never `toISOString`, which is UTC). */
function toIsoDate(value) {
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')

  return `${value.getFullYear()}-${month}-${day}`
}

/**
 * The day an operational screen should open on.
 *
 * @param {string|null|undefined} businessDate the active property's business date
 * @returns {string} `YYYY-MM-DD`
 *
 * Falls back to the browser's date only when there is no property context at
 * all - during the first paint, before `properties.get_property_context` has
 * answered. That window is why the fallback exists and why callers re-derive
 * once the store loads.
 */
export function operationalDate(businessDate) {
  if (typeof businessDate === 'string' && /^\d{4}-\d{2}-\d{2}/.test(businessDate)) {
    return businessDate.slice(0, 10)
  }

  if (businessDate instanceof Date && !Number.isNaN(businessDate.getTime())) {
    return toIsoDate(businessDate)
  }

  return toIsoDate(new Date())
}

/** The day after `date`, as `YYYY-MM-DD`. Departure is never the arrival night. */
export function nextDay(date) {
  const [year, month, day] = operationalDate(date).split('-').map(Number)

  // Constructed from parts rather than parsed, so it is local midnight and a
  // timezone west of UTC cannot roll it back a day.
  const value = new Date(year, month - 1, day)
  value.setDate(value.getDate() + 1)

  return toIsoDate(value)
}

/**
 * Today's *calendar* date at a property, as `YYYY-MM-DD`.
 *
 * This is the civil date — what a wall calendar in the lobby says — and it is
 * emphatically **not** an operational default. Nothing may post to it, default
 * from it or filter on it; `operationalDate()` above remains the only answer to
 * "which day is the hotel working". This exists so a screen can *say* what the
 * real date is, which is the one honest way to show that the business date has
 * fallen behind it.
 *
 * The zone is the property's own `time_zone`, which every Property carries as a
 * required field and `properties.get_property_context` already sends. A Doha
 * hotel administered from London is on Doha's calendar, not the browser's; the
 * browser's zone is used only when the property has not told us its own, which
 * on a configured bench does not happen.
 *
 * @param {string|null|undefined} timeZone IANA zone, e.g. `Asia/Qatar`
 * @param {Date} [now] the instant to read; defaults to the clock
 * @returns {string} `YYYY-MM-DD`
 */
export function currentCalendarDate(timeZone, now = new Date()) {
  if (Number.isNaN(now.getTime())) return ''

  // Built from parts rather than sliced off a formatted string: `en-CA` happens
  // to render ISO order today, but that is a locale detail and not a promise.
  const parts = new Intl.DateTimeFormat('en-US', {
    ...(timeZone ? { timeZone } : {}),
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)

  const at = (type) => parts.find((part) => part.type === type)?.value

  return `${at('year')}-${at('month')}-${at('day')}`
}

/**
 * Whole days from one date-only value to the next, or `null` if either is not
 * a date.
 *
 * Both sides are parsed as UTC midnight, which is safe *because* both are: the
 * offset cancels, so the difference is exact and no zone can round it to the
 * day either side. Nothing here is an instant.
 */
export function daysBetween(from, to) {
  const start = Date.parse(`${String(from).slice(0, 10)}T00:00:00Z`)
  const end = Date.parse(`${String(to).slice(0, 10)}T00:00:00Z`)

  if (Number.isNaN(start) || Number.isNaN(end)) return null

  return Math.round((end - start) / 86_400_000)
}

/**
 * The arrival/departure pair a search or booking form opens with: tonight, on
 * the property's day.
 */
export function defaultStayRange(businessDate) {
  const arrival = operationalDate(businessDate)

  return { arrival, departure: nextDay(arrival) }
}
