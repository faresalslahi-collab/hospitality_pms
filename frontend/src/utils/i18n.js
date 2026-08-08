/**
 * Translation for the operational frontend.
 *
 * Frontend UI strings live in `src/locales/*.json`. Server-generated messages
 * (validation errors, workflow refusals) arrive already translated because the
 * server renders them in the user's language, so there is exactly one source of
 * truth per message and no duplicated catalogue.
 *
 * Never pass an English literal to a component that is meant to be reused;
 * pass a key (Frontend Standards section 10).
 */
import { computed, reactive } from 'vue'

import ar from '@/locales/ar.json'
import en from '@/locales/en.json'

const messages = { en, ar }

const RTL_LOCALES = new Set(['ar', 'he', 'fa', 'ur'])

const state = reactive({
  locale: 'en',
})

export const locale = computed(() => state.locale)
export const direction = computed(() => (RTL_LOCALES.has(state.locale) ? 'rtl' : 'ltr'))
export const isRTL = computed(() => direction.value === 'rtl')

/**
 * Translate a key, with optional `{name}` placeholder interpolation.
 *
 * An unknown key returns the key itself rather than an empty string, so a
 * missing translation is visible in review instead of silently blanking the UI.
 */
export function t(key, params) {
  const catalogue = messages[state.locale] || messages.en
  let text = catalogue[key] ?? messages.en[key] ?? key

  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.replaceAll(`{${name}}`, value)
    }
  }

  return text
}

/** Switch the active locale and mirror the document for RTL. */
export function setLocale(next) {
  state.locale = messages[next] ? next : 'en'

  if (typeof document !== 'undefined') {
    document.documentElement.lang = state.locale
    document.documentElement.dir = direction.value
  }
}

export const i18n = {
  install(app) {
    app.config.globalProperties.$t = t
    app.provide('t', t)
  },
}
