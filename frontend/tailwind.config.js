import frappeUIPreset from 'frappe-ui/tailwind'

/** @type {import('tailwindcss').Config} */
export default {
  presets: [frappeUIPreset],
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
    './node_modules/frappe-ui/src/components/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      // Operational density: front desk screens show a lot of rows at once.
      spacing: {
        rack: '2.25rem',
      },

      /**
       * Navigation navy.
       *
       * Frappe UI's palette is tuned for a light document surface and has no
       * dark chrome tone. The shell needs one: a permanently dark navigation
       * rail is what separates "where I am in the system" from "the record I am
       * working on", and it survives the operational glare of a front desk far
       * better than a second sheet of white.
       *
       * Extended, never replacing: every `surface-*`, `ink-*` and `outline-*`
       * token from the preset stays exactly as it was, so nothing else in the
       * app shifts.
       */
      colors: {
        navy: {
          50: '#F1F5FB',
          100: '#DDE8F7',
          200: '#B9CDEC',
          300: '#8AABDE',
          400: '#5583C6',
          500: '#2C5FA8',
          600: '#1B4A8C',
          700: '#153B72',
          800: '#102E5A',
          900: '#0D2547',
          950: '#081831',
        },
      },

      // Cards on the dashboard sit on a tinted canvas; the lift has to read at
      // a glance without turning into a drop shadow the eye has to fight.
      boxShadow: {
        card: '0 1px 2px 0 rgb(16 46 90 / 0.04), 0 1px 3px 0 rgb(16 46 90 / 0.06)',
        'card-hover': '0 2px 4px -1px rgb(16 46 90 / 0.08), 0 4px 10px -2px rgb(16 46 90 / 0.08)',
      },
    },
  },
  plugins: [],
}
