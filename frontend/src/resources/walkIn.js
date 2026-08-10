import { apiResource } from '@/resources'

/**
 * Walk-in endpoints.
 *
 * Only the two endpoints the walk-in itself owns live here. The wizard's room
 * and rate lookups go through the resources that already own them —
 * `availability.search`, `availability.assignable_rooms` and
 * `reservations.quote` — because a second search that drifts from the first is
 * how a screen ends up offering a room the booking path will refuse.
 */

/**
 * The property context a walk-in starts from.
 *
 * The arrival date of a walk-in is the property's *business date*, not today:
 * a property that has not run its Night Audit is still working yesterday, and
 * a browser clock cannot know that. The frontend therefore never derives the
 * arrival date — it asks for it and renders it read-only.
 */
export function walkInContextResource() {
  return apiResource('walk_in.get_walk_in_context', { method: 'GET' })
}

/**
 * Book and check in a guest standing at the desk, in one operation.
 *
 * The server creates the Reservation, the Stay and the Guest Folio and applies
 * every arrival guard on the way — blacklist, identification, deposit, room
 * readiness, availability. None of those is pre-judged here: the refusal text
 * that comes back is the thing the agent has to act on, so it is rendered
 * verbatim rather than reshaped into a generic failure.
 *
 * No rate is ever sent. Pricing is resolved server-side from the room type and
 * rate plan, so the quote shown in the wizard and the amount posted to the
 * folio cannot diverge (Frontend Standards section 5).
 */
export function createWalkInResource() {
  return apiResource('walk_in.create_walk_in')
}
