/**
 * Shared test setup, for the things every operational component needs.
 *
 * Deliberately small. Four repeated needs justified a helper: a router (every
 * board links to another screen), the property and session stores (every board
 * is scoped to a property and hides actions by role), a stand-in for a
 * frappe-ui resource (no test may reach the network), and the document
 * direction (RTL is a first-release requirement, not a later port).
 *
 * The stores are plain `reactive` modules rather than Pinia, so a test mutates
 * the real store and the component under test sees the real thing.
 */
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { property } from '@/stores/property'
import { session } from '@/stores/session'
import { setLocale } from '@/utils/i18n'

const Blank = { template: '<div />' }

/**
 * The routes the migrated boards link to, with stub components.
 *
 * Not the application router: that one carries a `beforeEach` which loads the
 * session over HTTP, and a web history that jsdom cannot navigate. The names
 * must match `src/router/index.js`, which is what makes a broken `:to` fail a
 * test instead of failing in production.
 */
export const OPERATIONAL_ROUTES = [
  { path: '/', name: 'Dashboard', component: Blank },
  { path: '/arrivals', name: 'Arrivals', component: Blank },
  { path: '/departures', name: 'Departures', component: Blank },
  { path: '/in-house', name: 'InHouse', component: Blank },
  { path: '/reservations/:id', name: 'Reservation', component: Blank },
  { path: '/stays/:id', name: 'Stay', component: Blank },
  { path: '/folios/:id', name: 'Folio', component: Blank },
  { path: '/check-in/:reservation', name: 'CheckIn', component: Blank },
  { path: '/checkout/:stay', name: 'Checkout', component: Blank },
  { path: '/guests/:id', name: 'GuestProfile', component: Blank },
]

export function testRouter() {
  return createRouter({ history: createMemoryHistory(), routes: OPERATIONAL_ROUTES })
}

/**
 * Mount a component with the operational context installed.
 *
 * `attachTo: document.body` by default because focus management is part of the
 * contract for the drawer and the row actions, and `document.activeElement`
 * only means anything for a mounted tree that is actually in the document.
 */
export async function mountOperational(component, options = {}) {
  const { router = testRouter(), attach = true, ...rest } = options

  router.push('/')
  await router.isReady()

  const wrapper = mount(component, {
    ...rest,
    attachTo: attach ? document.body : undefined,
    global: {
      ...rest.global,
      plugins: [router, ...(rest.global?.plugins || [])],
    },
  })

  await wrapper.vm.$nextTick()

  return wrapper
}

/**
 * A stand-in for a frappe-ui resource.
 *
 * Only the surface the pages actually use: `data`, `loading`, `error`, and the
 * two calls. `fetch` and `submit` are spies, so a test can assert that a board
 * refetched after an action without any request leaving the process.
 */
export function fakeResource(initial = {}) {
  const resource = reactive({
    data: initial.data ?? null,
    loading: initial.loading ?? false,
    error: initial.error ?? null,
    fetch: vi.fn(),
    submit: vi.fn(),
    reload: vi.fn(),
  })

  return resource
}

/** Put a property in context, the way `properties.get_property_context` would. */
export function stubProperty(overrides = {}) {
  const record = {
    name: 'DOHA01',
    property_name: 'Doha Grand',
    currency: 'QAR',
    // Not today: a property mid-Night-Audit is still working an earlier day,
    // and a screen that defaults from the browser clock is the defect this
    // fixture exists to catch.
    business_date: '2026-08-08',
    ...overrides,
  }

  property.state.properties = [record]
  property.state.active = record.name
  property.state.loaded = true

  return record
}

/** Give the session a set of roles. Never a permission decision — see SAD 11. */
export function stubSession(roles = [], overrides = {}) {
  session.state.user = 'agent@hospitality-pms.invalid'
  session.state.roles = roles
  session.state.loaded = true
  Object.assign(session.state, overrides)
}

export function resetStores() {
  property.state.properties = []
  property.state.active = null
  property.state.loaded = false
  session.state.user = null
  session.state.roles = []
  session.state.loaded = false
}

/**
 * Set the document direction.
 *
 * Components are expected to be direction-agnostic — CSS logical properties,
 * never `left`/`right` — so this sets the attribute the browser would set and
 * changes nothing else. Arabic *labels* are a separate question: use
 * `setLocale('ar')` for that.
 */
export function setDirection(dir) {
  document.documentElement.setAttribute('dir', dir)
}

/** Arabic locale and RTL together, as a real Arabic session has them. */
export function useArabic() {
  setLocale('ar')
  setDirection('rtl')
}

/**
 * Let pending work and the resulting re-render settle.
 *
 * The macrotask tick is load-bearing: a component that calls `router.push()`
 * cannot hand its promise to the test, and Vue Router resolves a navigation
 * across a macrotask boundary. Microtasks alone leave the route unchanged, which
 * reads as "the action did nothing" rather than "the test looked too early".
 */
export async function flush(wrapper) {
  await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  if (wrapper) await wrapper.vm.$nextTick()
}
