/**
 * The Reservation Workspace read model, and the one write the workspace itself owns.
 *
 * `get_workspace` is a single aggregate: the tabs are six views of one booking, so
 * the screen fetches once rather than once per tab and never shows six different
 * moments of the same reservation. `get_history` is the booking's audit trail and
 * is fetched separately, because a hundred log rows are not needed to paint the
 * page and the tab that shows them is opened rarely.
 *
 * Both are GET and read nothing back into the client's hands that the server did
 * not decide to disclose. Sections the caller is not entitled to — `guest_standing`,
 * `corporate`, `deposit.credited` — arrive as *absent keys*, so every consumer must
 * test presence with `hasField` (see `resources/guests.js`) and never truthiness:
 * a `0` or a `false` invented on the client is a claim the server refused to make.
 *
 * The only mutation here is `update_reservation_details`, and it is deliberately
 * not a document save: the service refuses any key outside its own writable list,
 * so the workspace sends a field map of what the operator actually changed. Every
 * other verb the workspace offers (confirm, guarantee, cancel, no-show, assign,
 * check-in) is a lifecycle operation and stays in `resources/reservations.js`.
 */
import { apiResource } from '@/resources'

/** Everything the workspace opens with, for one reservation. */
export function reservationWorkspaceResource() {
  return apiResource('reservation_workspace.get_workspace', { method: 'GET' })
}

/** The booking's immutable log. Read-only by construction — there is no writer. */
export function reservationHistoryResource() {
  return apiResource('reservation_workspace.get_history', { method: 'GET' })
}

/**
 * Correct the non-inventory details of a booking.
 *
 * `{ reservation, changes: { field: value } }`. The service owns the allow list
 * (`services.reservations.DETAIL_WRITABLE_FIELDS`) and refuses anything outside
 * it, which is why the workspace collects an edit rather than saving a document.
 */
export function updateReservationDetailsResource() {
  return apiResource('reservations.update_reservation_details')
}

/**
 * The detail fields this workspace collects, split by the tab that shows them.
 *
 * A subset of the server's writable list on purpose: `guarantee_type` is also
 * writable there, but the workspace changes a guarantee through the guarantee
 * *transition*, which is a separate server operation with its own audit record —
 * not part of a collected edit.
 */
export const OVERVIEW_EDIT_FIELDS = ['booking_source', 'market_segment', 'arrival_time']
export const NOTE_EDIT_FIELDS = ['special_requests', 'internal_notes']
export const DETAIL_EDIT_FIELDS = [...OVERVIEW_EDIT_FIELDS, ...NOTE_EDIT_FIELDS]
