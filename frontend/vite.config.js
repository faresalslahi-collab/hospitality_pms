import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'

export default defineConfig({
  plugins: [
    frappeui({
      // Deep links under /pms are handled by the Vue router; the build writes
      // the generated index into the app's www/ folder so Frappe serves it.
      frontendRoute: '/pms',
      buildConfig: {
        indexHtmlPath: '../hospitality_pms/www/pms.html',
        sourcemap: false,
      },
    }),
    vue(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  optimizeDeps: {
    include: ['feather-icons', 'engine.io-client'],
  },
})
