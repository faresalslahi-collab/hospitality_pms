/**
 * Active property context.
 *
 * Shared state because almost every operational screen is scoped to a property
 * and its business date (Frontend Standards section 7). The server still
 * re-authorises the property on every call; this store only decides what the
 * user is looking at.
 */
import { computed, reactive } from 'vue'

import { apiResource } from '@/resources'
import { currentCalendarDate, daysBetween } from '@/utils/operationalDate'

const STORAGE_KEY = 'hpms:active-property'

/** How often the shared clock asks whether the calendar day has turned. */
const CLOCK_INTERVAL_MS = 60_000

const state = reactive({
  properties: [],
  active: null,
  loaded: false,
  /**
   * Bumped by the clock below. Nothing reads its value — it exists so the
   * `today` computed has something to invalidate on, which is what lets a
   * terminal left open across midnight notice.
   */
  clockTick: 0,
})

let clock = null

/**
 * Start the one clock the app needs.
 *
 * One timer for the whole session rather than one per component: two screens
 * ask what today's date is, and two intervals answering the same question is
 * two chances to disagree. It only bumps a counter; the day is re-derived
 * lazily, and the computed below re-renders only when the string it produces
 * actually changes.
 */
function startClock() {
  if (clock || typeof window === 'undefined') return

  clock = window.setInterval(() => {
    state.clockTick += 1
  }, CLOCK_INTERVAL_MS)
}

export const propertyResource = apiResource('properties.get_property_context', {
  method: 'GET',
  onSuccess(data) {
    state.properties = data.properties || []

    const remembered = readRemembered()
    const known = (name) => state.properties.some((p) => p.name === name)

    state.active =
      (known(remembered) && remembered) ||
      (known(data.default_property) && data.default_property) ||
      state.properties[0]?.name ||
      null

    state.loaded = true
  },
})

export const property = {
  state,

  list: computed(() => state.properties),
  isLoaded: computed(() => state.loaded),
  activeName: computed(() => state.active),
  active: computed(() => state.properties.find((p) => p.name === state.active) || null),

  /** Currency of the active property; never assumed, always read from the record. */
  currency: computed(() => property.active.value?.currency || null),

  /**
   * The property's operating day, which is not necessarily today: a property
   * that has not run its Night Audit is still working yesterday's date.
   */
  businessDate: computed(() => property.active.value?.business_date || null),

  /**
   * The property's own IANA zone, from the Property record.
   *
   * Required on every Property and already in the context payload, so a screen
   * that needs to know what day it *is* never has to ask the browser. A hotel
   * in Doha administered from a laptop in London is on Doha's calendar.
   */
  timeZone: computed(() => property.active.value?.time_zone || null),

  /**
   * Today's calendar date at the property — the civil date, not the hotel's.
   *
   * Never an operational default. Screens post to, filter on and default from
   * `businessDate`; this is here so the two can be *compared*, and so a screen
   * can say what the real date is.
   */
  today: computed(() => {
    void state.clockTick

    return currentCalendarDate(property.timeZone.value)
  }),

  /**
   * How many days the operating day is behind the property's calendar day.
   *
   * Zero on a property whose audit ran, and this is a *report* of the gap, not
   * a cause of it: nothing here advances a business date, which only the Night
   * Audit service may do. Negative values — a business date ahead of the
   * calendar — are floored to zero rather than announced as a negative lag.
   */
  businessDateLag: computed(() => {
    const behind = daysBetween(property.businessDate.value, property.today.value)

    return behind && behind > 0 ? behind : 0
  }),

  load() {
    startClock()

    if (state.loaded) return Promise.resolve(state)
    return propertyResource.fetch()
  },

  /**
   * Re-read the property context unconditionally.
   *
   * `load()` is a once-per-session guard; this is for the one thing that moves a
   * property's business date under a running session — the Night Audit close.
   * Re-reading here is what updates the navigation rail and every screen scoped
   * to the business date, instead of asking the operator to reload the browser.
   */
  refresh() {
    return propertyResource.fetch()
  },

  setActive(name) {
    if (!state.properties.some((p) => p.name === name)) return

    state.active = name
    writeRemembered(name)
  },
}

function readRemembered() {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    // Private browsing and locked-down kiosks can refuse storage; the store
    // still works, it just will not remember the choice.
    return null
  }
}

function writeRemembered(name) {
  try {
    window.localStorage.setItem(STORAGE_KEY, name)
  } catch {
    // ignore, see readRemembered
  }
}
