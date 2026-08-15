/**
 * The shell, and the search box it no longer carries.
 *
 * Global search used to sit in a bar above every page. That put a "find any
 * record" box on top of screens that already have their own, better-scoped
 * search — the reservations filter, the guest lookup, every board's column
 * search — and made the Command Center open on a text box rather than on the
 * hotel and the date.
 *
 * The rule this file protects has three parts:
 *
 *   - the shell renders no global search on any route;
 *   - the Command Center renders exactly one, itself (asserted in
 *     `tests/pages/Dashboard.spec.js`, where the page is mounted);
 *   - a page's own search control is none of the shell's business and is left
 *     exactly as the page rendered it.
 */
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { mountOperational, OPERATIONAL_ROUTES, resetStores, stubProperty, stubSession } from '../helpers'

const { default: AppLayout } = await import('@/components/AppLayout.vue')

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, '..', '..', 'src')

const Blank = { template: '<div>page body</div>' }

/**
 * A page that brings its own search control, as most operational pages do.
 *
 * Deliberately not a `GlobalSearch`: the point is that the shell must not touch
 * a page's own filter while removing the global one.
 */
const PageWithOwnSearch = {
  template: `
    <div>
      <input data-page-search placeholder="Search reservations" />
      <p>page body</p>
    </div>
  `,
}

/**
 * The routes the navigation rail links to.
 *
 * The shell mounts the real sidebar, so every entry a front desk agent can see
 * has to resolve or `RouterLink` throws while building its href.
 */
const SIDEBAR_ROUTES = [
  { path: '/reservations', name: 'Reservations', component: Blank },
  { path: '/calendar', name: 'Calendar', component: Blank },
  { path: '/availability', name: 'Availability', component: Blank },
  { path: '/kitchen', name: 'Kitchen', component: Blank },
  { path: '/guest-services', name: 'GuestServices', component: Blank },
]

function shellRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [...OPERATIONAL_ROUTES, ...SIDEBAR_ROUTES],
  })
}

async function mountShell(path = '/', page = Blank) {
  const router = shellRouter()

  router.push(path)
  await router.isReady()

  return mountOperational(AppLayout, { router, slots: { default: page } })
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Agent'])
})

describe('Shell global search', () => {
  it('renders no global search bar on any route, including the Command Center', async () => {
    // The Command Center has one, but it is the page's and is asserted where the
    // page is mounted. From the shell's side the answer is the same everywhere:
    // not mine.
    for (const path of ['/', '/arrivals', '/rooms', '/reservations', '/in-house', '/kitchen']) {
      const wrapper = await mountShell(path)

      expect(wrapper.find('[data-global-search]').exists()).toBe(false)
    }
  })

  it('still renders the page it wraps', async () => {
    for (const path of ['/', '/arrivals']) {
      const wrapper = await mountShell(path)

      expect(wrapper.text()).toContain('page body')
    }
  })

  it('leaves a page\'s own search control alone', async () => {
    const wrapper = await mountShell('/reservations', PageWithOwnSearch)

    expect(wrapper.find('[data-page-search]').exists()).toBe(true)
    expect(wrapper.find('[data-page-search]').attributes('placeholder')).toBe('Search reservations')
    // Removed the global one; kept the page's.
    expect(wrapper.find('[data-global-search]').exists()).toBe(false)
  })

  it('keeps the navigation and the mobile bar it does own', async () => {
    // The bar carried the search; removing the search must not have taken the
    // shell's own chrome with it.
    const wrapper = await mountShell('/arrivals')

    expect(wrapper.findComponent({ name: 'AppSidebar' }).exists()).toBe(true)
    expect(wrapper.text()).toContain('Hospitality PMS')
  })
})

/**
 * One box, one call site.
 *
 * Read off the source rather than the DOM: a second `GlobalSearch` mounted on
 * another page would each keep its own open panel and its own live region, and
 * a rendering test on one page could never see the other.
 */
describe('Global search is mounted in exactly one place', () => {
  function vueFilesUnder(dir) {
    const out = []

    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name)

      if (entry.isDirectory()) out.push(...vueFilesUnder(path))
      else if (entry.name.endsWith('.vue')) out.push(path)
    }

    return out
  }

  it('is imported by the Command Center and by nothing else', () => {
    const importers = vueFilesUnder(SRC)
      .filter((path) => !path.endsWith(join('operational', 'GlobalSearch.vue')))
      .filter((path) => /import\s+GlobalSearch\s+from/.test(readFileSync(path, 'utf8')))
      .map((path) => path.slice(SRC.length + 1))

    expect(importers).toEqual([join('pages', 'Dashboard.vue')])
  })
})
