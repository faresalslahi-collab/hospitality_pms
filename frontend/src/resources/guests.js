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

/**
 * The Guest 360 workspace payload.
 *
 * One aggregate, so the tabs cannot show six different moments of the same
 * guest. Blocks the caller is not entitled to arrive as **absent keys** —
 * `identifications`, `standing.is_blacklisted`, `standing.blacklist_reason`,
 * `stay_statistics` and `current_stay` are each gated on the source that owns
 * them, so every consumer must test presence with `hasField` and never
 * truthiness. An absent block is "not shown to your role"; an empty one is
 * "there is none", and rendering the first as the second is a lie.
 *
 * `disclosure` reports what the caller's own roles allow and never what the
 * record contains, which is what lets a tab say the honest thing about why it
 * is empty.
 */
export function getGuestWorkspaceResource() {
  return apiResource('guest_workspace.get_workspace', { method: 'GET' })
}

/**
 * Paginated histories, one resource each.
 *
 * Separate from the workspace because a lifetime of bookings is not needed to
 * paint the page. Server-side bounds: `limit` and `start` in, `has_more` out —
 * there is no `total`, so `OperationalDataTable` decides "there is another
 * page" from a full page rather than from a count.
 */
export function guestReservationsResource() {
  return apiResource('guest_workspace.get_reservations', { method: 'GET' })
}

export function guestStaysResource() {
  return apiResource('guest_workspace.get_stays', { method: 'GET' })
}

export function guestFoliosResource() {
  return apiResource('guest_workspace.get_folios', { method: 'GET' })
}

/**
 * Merge a duplicate guest into the record being kept.
 *
 * Role-gated on the server (`services.guests.MERGE_ROLES`) and reason-mandatory.
 * A merge repoints reservation, stay and folio history onto another guest;
 * getting it wrong costs far more than a duplicate record does, which is why it
 * is a deliberate action and not a button on the duplicate dialog.
 */
export function mergeGuestsResource() {
  return apiResource('guests.merge')
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
