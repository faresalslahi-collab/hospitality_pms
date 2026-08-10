import { apiResource } from '@/resources'

/** Type-ahead guest search by name, email or mobile. */
export function searchGuestsResource() {
  return apiResource('guests.search_guests', { method: 'GET' })
}

/**
 * One guest profile.
 *
 * Identification and blacklist fields are permission-gated on the server and
 * are simply absent from the payload for a user not cleared to see them —
 * distinct from being present and empty. Always check with `hasField`, never
 * a truthiness check, so an absent section is never rendered as "none on
 * file".
 */
export function getGuestResource() {
  return apiResource('guests.get_guest', { method: 'GET' })
}

export function findGuestMatchesResource() {
  return apiResource('guests.find_matches')
}

/**
 * Register a new guest.
 *
 * The server answers a duplicate-looking payload with `{ created: false,
 * duplicates: [...] }` rather than an error, because "this may already be a
 * guest we hold" is a decision for the desk, not a failure. Re-submitting with
 * `ignore_duplicates: 1` is the "Create Anyway" branch.
 */
export function createGuestResource() {
  return apiResource('guests.create_guest')
}

/** Correct an existing guest. Returns the same payload shape as `get_guest`. */
export function updateGuestResource() {
  return apiResource('guests.update_guest')
}

/** Whether the server included a permission-gated field in the payload. */
export function hasField(payload, field) {
  return Boolean(payload) && Object.prototype.hasOwnProperty.call(payload, field)
}

export const ALERT_SEVERITY_THEME = {
  Info: 'blue',
  Warning: 'orange',
  Critical: 'red',
}

export function alertSeverityTheme(severity) {
  return ALERT_SEVERITY_THEME[severity] || 'gray'
}

export const VIP_STATUS_THEME = {
  VIP: 'orange',
  VVIP: 'red',
  'Loyalty Member': 'blue',
  'Repeat Guest': 'green',
}

export function vipStatusTheme(status) {
  return VIP_STATUS_THEME[status] || 'gray'
}
