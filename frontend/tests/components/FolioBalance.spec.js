/**
 * FolioBalance — one balance presentation for the whole operation.
 *
 * Two things are being protected here. The first is that the three states are
 * read off the amount and nothing else, including the rounding threshold that
 * separates "settled" from "owes four tenths of a riyal". The second, and the
 * reason this component exists at all, is that a balance must never be turned
 * into a departure decision: `can_check_out` comes from the server with blockers
 * this component cannot see, so no wording here may suggest a guest is free to go.
 */
import { describe, expect, it } from 'vitest'

import FolioBalance from '@/components/operational/FolioBalance.vue'

import { mountOperational, setDirection, useArabic } from '../helpers'

const PHYSICAL_CLASSES = /\b(?:text-left|text-right|ml-|mr-|pl-|pr-|left-|right-)/

/**
 * Any wording that would read as "this guest may leave".
 *
 * Checked against the full markup, not just the visible text, so an aria-label
 * or a tooltip cannot smuggle the claim past the assertion.
 */
const CHECKOUT_WORDING =
  /ready|check[\s-]?out|checkout|depart|eligib|may leave|can leave|clear to|free to go|settle up/i

const STATE_WORDS = ['Settled', 'Balance due', 'Credit']

/**
 * An independent reference formatter, so the expected accessible name is not a
 * restatement of `utils/format`. Note the non-breaking space Intl puts between
 * the currency and the number: asserting a plain space would be asserting a bug
 * that is not there.
 */
function reference(value, currency = null) {
  return new Intl.NumberFormat('en-GB', {
    ...(currency ? { style: 'currency', currency } : {}),
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

describe('FolioBalance', () => {
  it('reads a zero balance as settled', async () => {
    const wrapper = await mountOperational(FolioBalance, {
      props: { balance: 0, currency: 'QAR' },
    })

    expect(wrapper.text()).toContain('Settled')
    expect(wrapper.text()).toContain('0.00')
    expect(wrapper.attributes('aria-label')).toBe(`Settled: ${reference(0, 'QAR')}`)
    // Settled is green, the theme balanceTheme() already gives the boards.
    expect(wrapper.html()).toContain('green')
  })

  it('treats a rounding remainder as settled, not as a debt', async () => {
    const wrapper = await mountOperational(FolioBalance, {
      props: { balance: 0.004, currency: 'QAR' },
    })

    expect(wrapper.text()).toContain('Settled')
    expect(wrapper.text()).not.toContain('Balance due')

    const negative = await mountOperational(FolioBalance, {
      props: { balance: -0.004, currency: 'QAR' },
    })

    expect(negative.text()).toContain('Settled')
  })

  it('reads a positive balance as owed by the guest', async () => {
    const wrapper = await mountOperational(FolioBalance, {
      props: { balance: 250.75, currency: 'QAR' },
    })

    expect(wrapper.text()).toContain('Balance due')
    expect(wrapper.text()).toContain('250.75')
    expect(wrapper.attributes('aria-label')).toBe(`Balance due: ${reference(250.75, 'QAR')}`)
    // balanceTheme() returns 'orange', which frappe-ui renders as amber.
    expect(wrapper.html()).toContain('amber')
  })

  it('reads a negative balance as a credit held by the hotel', async () => {
    const wrapper = await mountOperational(FolioBalance, {
      props: { balance: -120, currency: 'QAR' },
    })

    expect(wrapper.text()).toContain('Credit')
    expect(wrapper.text()).toContain('120.00')
    expect(wrapper.text()).toMatch(/[-−]/)
    expect(wrapper.html()).toContain('blue')
  })

  it('hides the state word on request but keeps it in the accessible name', async () => {
    const wrapper = await mountOperational(FolioBalance, {
      props: { balance: 250.75, currency: 'QAR', showLabel: false },
    })

    expect(wrapper.text()).not.toContain('Balance due')
    expect(wrapper.text()).toContain('250.75')
    // Never colour-only: the state still reaches assistive technology.
    expect(wrapper.attributes('aria-label')).toBe(`Balance due: ${reference(250.75, 'QAR')}`)
    expect(wrapper.attributes('title')).toBe(`Balance due: ${reference(250.75, 'QAR')}`)
  })

  it('renders the amount in both the compact and the larger size', async () => {
    for (const size of ['sm', 'md']) {
      const wrapper = await mountOperational(FolioBalance, {
        props: { balance: 340.5, currency: 'QAR', size },
      })

      expect(wrapper.text()).toContain('340.50')
      expect(wrapper.text()).toContain('QAR')
      expect(wrapper.text()).toContain('Balance due')
    }
  })

  it('renders through MoneyDisplay rather than formatting its own amount', async () => {
    const wrapper = await mountOperational(FolioBalance, {
      props: { balance: 1234.5, currency: 'QAR' },
    })

    // MoneyDisplay's signature: a non-wrapping, tabular-figure span.
    expect(wrapper.html()).toContain('tabular-nums')
    expect(wrapper.text()).toContain('1,234.50')
  })

  it('falls back to plain number formatting when no currency arrived', async () => {
    const wrapper = await mountOperational(FolioBalance, {
      props: { balance: 90, currency: null },
    })

    expect(wrapper.text()).toContain('90.00')
    expect(wrapper.text()).not.toContain('QAR')
    expect(wrapper.attributes('aria-label')).toBe(`Balance due: ${reference(90)}`)
  })

  it('makes no semantic claim when the balance was never supplied', async () => {
    for (const balance of [null, '']) {
      const wrapper = await mountOperational(FolioBalance, {
        props: { balance, currency: 'QAR' },
      })

      expect(wrapper.text()).toContain('—')

      for (const word of STATE_WORDS) {
        expect(wrapper.text()).not.toContain(word)
      }

      // No state, so no state colour and no state sentence.
      expect(wrapper.attributes('aria-label')).toBeUndefined()
      expect(wrapper.html()).not.toMatch(/green|amber|blue/)
      // MoneyDisplay still says "not available" for the amount itself.
      expect(wrapper.html()).toContain('Not available')
    }
  })

  it('never suggests checkout eligibility, in any state or size', async () => {
    for (const balance of [null, -500, -0.004, 0, 0.004, 250.75]) {
      for (const size of ['sm', 'md']) {
        for (const showLabel of [true, false]) {
          const wrapper = await mountOperational(FolioBalance, {
            props: { balance, currency: 'QAR', size, showLabel },
          })

          expect(wrapper.html()).not.toMatch(CHECKOUT_WORDING)
        }
      }
    }
  })

  it('exposes no checkout-shaped prop', async () => {
    const props = Object.keys(FolioBalance.props || {})

    expect(props).toEqual(['balance', 'currency', 'size', 'showLabel'])
    expect(props.join(' ')).not.toMatch(/checkout|check_out|canCheckOut|ready|depart/i)
  })

  it('uses Arabic wording and no physical direction utilities in an Arabic session', async () => {
    useArabic()

    const wrapper = await mountOperational(FolioBalance, {
      props: { balance: 250.75, currency: 'QAR', size: 'md' },
    })

    expect(wrapper.text()).toContain('رصيد مستحق')
    expect(wrapper.text()).toContain('ر.ق')
    expect(wrapper.html()).not.toMatch(PHYSICAL_CLASSES)
    expect(wrapper.html()).toContain('text-start')
  })

  it('uses logical utilities in every state', async () => {
    setDirection('rtl')

    for (const balance of [null, 0, 12.5, -12.5]) {
      for (const size of ['sm', 'md']) {
        const wrapper = await mountOperational(FolioBalance, {
          props: { balance, currency: 'QAR', size },
        })

        expect(wrapper.html()).not.toMatch(PHYSICAL_CLASSES)
      }
    }
  })
})
