/**
 * Global operational search.
 *
 * One aggregate GET behind the Front Desk Command Center search box:
 * `search.operational_search` answers guests, reservations, stays, rooms and
 * folios in a single call.
 *
 * One endpoint rather than five on purpose. The server decides which of the
 * five entities this user may read, which property is in scope and what a
 * result row is allowed to contain; a client that fanned out to five endpoints
 * and merged the replies would be assembling a picture no single permission
 * check ever authorised, and would show its five states at five different times
 * (CLAUDE.md server authority, Frontend Standards section 6).
 *
 * The endpoint mutates nothing, so it is GET — which is exactly why the caller
 * debounces rather than firing per keystroke.
 */
import { apiResource } from '@/resources'

/**
 * Shortest query the server will act on — mirrors
 * `services.search.MIN_QUERY_LENGTH`.
 *
 * Mirrored so the client can *explain* a short query instead of sending a
 * request that is guaranteed to come back empty. The server still enforces it;
 * the response echoes `min_length` for exactly this reason.
 */
export const SEARCH_MIN_LENGTH = 2

/**
 * Per-entity cap requested — mirrors `services.search.DEFAULT_LIMIT`.
 *
 * The search box is a jump-to-record affordance, not a report: five per type
 * keeps the panel readable, and the server answers `truncated: true` when more
 * exist so the user is told to refine rather than left believing they saw
 * everything. The server clamps this to its own maximum.
 */
export const SEARCH_LIMIT = 5

/**
 * Debounce window for the search box, in milliseconds.
 *
 * Long enough that typing a guest name is one request rather than six, short
 * enough that the panel still feels live at a front desk counter.
 */
export const SEARCH_DEBOUNCE_MS = 250

/**
 * The aggregate search resource.
 *
 * A factory, not a module-level singleton: the component owns its own instance,
 * so two mounted search boxes cannot overwrite each other's state.
 *
 * Note for callers: `fetch()` resolves with the payload and rejects with the
 * raw error, and the resource's own `data`/`error`/`loading` are shared by every
 * in-flight call on the instance. A typeahead therefore reads the *resolved
 * value* of its own call and keeps its own state, so a slow response for an
 * abandoned query cannot overwrite a newer one.
 */
export function operationalSearchResource() {
  return apiResource('search.operational_search', { method: 'GET' })
}
