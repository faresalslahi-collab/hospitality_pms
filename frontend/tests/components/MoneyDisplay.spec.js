/**
 * MoneyDisplay — the one way an amount of money reaches the screen.
 *
 * The cases below are the ones that have bitten hotel software before: a settled
 * folio that renders blank because zero was treated as "no value", a refund that
 * loses its sign, a missing amount that renders a dash with nothing for a screen
 * reader, and an Arabic session that gets English formatting.
 *
 * Where a format is asserted exactly, the expectation is built from `Intl`
 * directly rather than from the app's own helper, so the test is an independent
 * reference and not a restatement of the code under test.
 */
import { describe, expect, it } from 'vitest'

import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import { t } from '@/utils/i18n'

import { mountOperational, setDirection, useArabic } from '../helpers'

/** Physical direction utilities. RTL is a first-release requirement (CLAUDE.md). */
const PHYSICAL_CLASSES = /\b(?:text-left|text-right|ml-|mr-|pl-|pr-|left-|right-)/

/** An independent reference formatter — not the app's `utils/format`. */
function reference(value, { locale = 'en-GB', currency = null } = {}) {
  return new Intl.NumberFormat(locale, {
    ...(currency ? { style: 'currency', currency } : {}),
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

describe('MoneyDisplay', () => {
  it('renders a normal amount with its currency', async () => {
    const wrapper = await mountOperational(MoneyDisplay, {
      props: { value: 1234.5, currency: 'QAR' },
    })

    expect(wrapper.text()).toBe(reference(1234.5, { currency: 'QAR' }))
    expect(wrapper.text()).toContain('1,234.50')
    expect(wrapper.text()).toContain('QAR')
  })

  it('accepts the amount as a string, as a JSON payload delivers it', async () => {
    const wrapper = await mountOperational(MoneyDisplay, {
      props: { value: '1234.5', currency: 'QAR' },
    })

    expect(wrapper.text()).toBe(reference(1234.5, { currency: 'QAR' }))
  })

  it('renders zero as 0.00 — a settled folio is not a missing one', async () => {
    const wrapper = await mountOperational(MoneyDisplay, {
      props: { value: 0, currency: 'QAR' },
    })

    expect(wrapper.text()).toContain('0.00')
    expect(wrapper.text()).not.toContain('—')
    expect(wrapper.text().trim()).not.toBe('')
    // Zero is a known amount, so it carries no "not available" label.
    expect(wrapper.attributes('aria-label')).toBeUndefined()
  })

  it('renders a negative amount as negative, the way the locale writes it', async () => {
    const wrapper = await mountOperational(MoneyDisplay, {
      props: { value: -1000, currency: 'QAR' },
    })

    const text = wrapper.text()

    // Exactly what Intl produces: the sign is placed by the locale, never by
    // concatenating a '-' onto a formatted positive number.
    expect(text).toBe(reference(-1000, { currency: 'QAR' }))
    expect(text).toContain('1,000.00')
    expect(text).toMatch(/[-−]/)
    // One sign only — a doubled minus is the signature of manual concatenation.
    expect(text.match(/[-−]/g)).toHaveLength(1)
    expect(text).not.toBe(reference(1000, { currency: 'QAR' }))
  })

  it('renders the placeholder and an accessible label when the value is null', async () => {
    const wrapper = await mountOperational(MoneyDisplay, {
      props: { value: null, currency: 'QAR' },
    })

    expect(wrapper.text()).toBe('—')
    expect(wrapper.attributes('aria-label')).toBe(t('ui.money.unknown'))
    expect(wrapper.attributes('aria-label')).toBe('Not available')
    expect(wrapper.attributes('title')).toBe('Not available')
  })

  it('treats an empty string as unknown', async () => {
    const wrapper = await mountOperational(MoneyDisplay, {
      props: { value: '', currency: 'QAR' },
    })

    expect(wrapper.text()).toBe('—')
    expect(wrapper.attributes('aria-label')).toBe('Not available')
  })

  it('falls back to plain number formatting when no currency was supplied', async () => {
    const wrapper = await mountOperational(MoneyDisplay, {
      props: { value: 1234.5 },
    })

    expect(wrapper.text()).toBe(reference(1234.5))
    expect(wrapper.text()).toBe('1,234.50')
    expect(wrapper.text()).not.toContain('QAR')
  })

  it('formats in the Arabic locale for an Arabic RTL session', async () => {
    useArabic()

    const wrapper = await mountOperational(MoneyDisplay, {
      props: { value: 1234.5, currency: 'QAR' },
    })

    expect(wrapper.text()).toBe(reference(1234.5, { locale: 'ar', currency: 'QAR' }))
    // The Arabic currency form, not the Latin code.
    expect(wrapper.text()).toContain('ر.ق')
    expect(wrapper.text()).not.toContain('QAR')
    expect(document.documentElement.getAttribute('dir')).toBe('rtl')
  })

  it('carries the Arabic unknown label in an Arabic session', async () => {
    useArabic()

    const wrapper = await mountOperational(MoneyDisplay, { props: { value: null } })

    expect(wrapper.attributes('aria-label')).toBe('غير متوفر')
  })

  it('uses no physical direction utilities', async () => {
    setDirection('rtl')

    const wrapper = await mountOperational(MoneyDisplay, {
      props: { value: -1234.5, currency: 'QAR', muted: true, bold: true },
    })

    expect(wrapper.html()).not.toMatch(PHYSICAL_CLASSES)
  })
})
