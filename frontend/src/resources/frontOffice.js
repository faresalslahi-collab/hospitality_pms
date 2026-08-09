/**
 * Front Office board resources.
 *
 * Four read-only aggregates behind the dashboard, the arrivals and departures
 * boards and the reservation calendar. Each is one request that returns a whole
 * screen, rather than a screen that assembles itself from many
 * (Frontend Standards section 6).
 *
 * Nothing here changes state. Check-in, checkout, room assignment and folio
 * posting stay on their own resources, which reach the services that own those
 * rules.
 */
import { apiResource } from '@/resources'

/** Every KPI the dashboard shows, in one call. */
export function dashboardResource() {
  return apiResource('front_office.dashboard', { method: 'GET' })
}

/** One row per room arriving on the business date. */
export function arrivalsBoardResource() {
  return apiResource('front_office.arrivals', { method: 'GET' })
}

/** One row per stay departing on the business date, with its blockers. */
export function departuresBoardResource() {
  return apiResource('front_office.departures', { method: 'GET' })
}

/** A page of rooms across a bounded date window, with what occupies them. */
export function calendarGridResource() {
  return apiResource('front_office.calendar', { method: 'GET' })
}

/**
 * Roles the server will accept for each front office action.
 *
 * Mirrored here only to decide whether showing a control is worth it. The
 * server re-checks every one of them; a user who gets past this list is still
 * refused where it counts (Roles Matrix section 2).
 */
export const FRONT_DESK_ROLES = [
  'Front Office Agent',
  'Front Office Manager',
  'Hotel Manager',
  'General Manager',
  'Hospitality Administrator',
  'System Manager',
]

/** Kinds of calendar bar, and how each reads. */
export const CALENDAR_BAR_THEME = {
  stay: 'green',
  reservation: 'blue',
  block: 'red',
}

/**
 * Badge theme for a folio balance.
 *
 * Zero is settled, positive is owed by the guest, negative is a credit the
 * hotel holds. All three are normal; only the first means "ready to leave".
 */
export function balanceTheme(balance) {
  const value = Number(balance || 0)

  if (Math.abs(value) <= 0.005) return 'green'

  return value > 0 ? 'orange' : 'blue'
}
