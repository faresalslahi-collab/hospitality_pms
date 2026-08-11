/**
 * Global test setup.
 *
 * Two things only: unmount every component after its test so a drawer left open
 * cannot steal focus from the next one, and reset the document direction, which
 * is global state that an RTL test would otherwise leak into the file after it.
 */
import { enableAutoUnmount } from '@vue/test-utils'
import { afterEach } from 'vitest'

import { setLocale } from '@/utils/i18n'

enableAutoUnmount(afterEach)

afterEach(() => {
  setLocale('en')
  document.documentElement.removeAttribute('dir')
  document.documentElement.removeAttribute('lang')
})
