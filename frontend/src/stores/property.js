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

const STORAGE_KEY = 'hpms:active-property'

const state = reactive({
  properties: [],
  active: null,
  loaded: false,
})

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

  load() {
    if (state.loaded) return Promise.resolve(state)
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
