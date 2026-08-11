/**
 * Component test configuration.
 *
 * Deliberately separate from `vite.config.js`: the production config carries the
 * frappe-ui build plugin, which rewrites `hospitality_pms/www/pms.html` as a
 * side effect of a build. A test run must never touch a served template, so the
 * runner gets the two things it actually needs — the Vue plugin and the `@`
 * alias — and nothing else.
 */
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

import { lucideStub } from './tests/lucideStub'

export default defineConfig({
  plugins: [lucideStub(), vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.spec.js'],
    // The plain Node checks in src/utils are run by `yarn test:node`; picking
    // them up here too would report the same assertions twice.
    exclude: ['**/node_modules/**', '**/*.test.mjs'],
    restoreMocks: true,
    server: {
      deps: {
        // frappe-ui ships source with extensionless relative imports, which
        // Node's ESM resolver refuses. Processing it through Vite's resolver -
        // the same one the application build uses - is what makes it loadable.
        inline: ['frappe-ui'],
      },
    },
  },
})
