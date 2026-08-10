/**
 * Open work per department, for the navigation badges.
 *
 * Presentation state only. These are the same counts the dashboard already
 * fetches in its single aggregate, published here so the sidebar can show them
 * without issuing a request of its own — the alternative is every page in the
 * app paying for a count that only the badge uses.
 *
 * Consequence, deliberately accepted: the badges appear once the dashboard has
 * loaded and are then as fresh as the last dashboard load. A badge is a
 * prompt to go and look, not a figure anyone acts on, and the board it points
 * at is always authoritative.
 */
import { computed, reactive } from 'vue'

const state = reactive({
  loaded: false,
  counts: {},
})

/** Navigation key -> the count that belongs on it. */
const BADGE_KEYS = {
  housekeeping: 'housekeeping_open',
  maintenance: 'maintenance_open',
  guest_services: 'guest_requests_open',
}

export const workload = {
  state,

  isLoaded: computed(() => state.loaded),

  /** Publish the workload block of a dashboard response. */
  set(counts) {
    state.counts = counts || {}
    state.loaded = true
  },

  /** Nothing to show is `null`, not `0`: a zero badge is noise. */
  badgeFor(navigationKey) {
    const field = BADGE_KEYS[navigationKey]
    if (!field || !state.loaded) return null

    const value = Number(state.counts[field] || 0)

    return value > 0 ? value : null
  },
}
