/**
 * Resolves frappe-ui's `~icons/lucide/*` imports during a test run.
 *
 * In the application build those specifiers are supplied by the frappe-ui Vite
 * plugin, which also rewrites the served `pms.html` and installs the Frappe
 * proxy — neither of which belongs in a test run. Icons carry no operational
 * meaning (every status and action in this app is labelled in text, which is the
 * accessibility rule anyway), so the runner substitutes one empty `<svg>` and
 * keeps the build plugin out of the tests entirely.
 */
const PREFIX = '~icons/lucide/'
const RESOLVED = '\0~icons/lucide/'

export function lucideStub() {
  return {
    name: 'hpms-test-lucide-stub',

    resolveId(id) {
      if (id.startsWith(PREFIX)) return RESOLVED + id.slice(PREFIX.length)
      return null
    },

    load(id) {
      if (!id.startsWith(RESOLVED)) return null

      const name = id.slice(RESOLVED.length)

      return `
import { h } from 'vue'
export default {
  name: 'LucideStub',
  inheritAttrs: false,
  render() {
    return h('svg', { 'data-lucide': ${JSON.stringify(name)}, ...this.$attrs })
  },
}
`
    },
  }
}
