/**
 * AlertBadge — existence, count, severity. Never content.
 *
 * The behavioural cases matter, but the security case is the reason the
 * component was specified separately: guest alert bodies and blacklist reasons
 * must not be renderable here, by any route. `get_guest_flags` on the server
 * sends the boards a boolean and a VIP string and no reason at all, and this
 * component has to be the client-side half of that boundary — not merely
 * "currently not passed a reason", but structurally unable to show one.
 */
import { describe, expect, it } from 'vitest'

import AlertBadge from '@/components/operational/AlertBadge.vue'
import { t } from '@/utils/i18n'

import { mountOperational, setDirection, useArabic } from '../helpers'

const PHYSICAL_CLASSES = /\b(?:text-left|text-right|ml-|mr-|pl-|pr-|left-|right-)/

describe('AlertBadge', () => {
  /**
   * Vue leaves a `<!--v-if-->` anchor where a false branch was, so "renders
   * nothing" is asserted as "no element and no text", not as an empty string.
   */
  function expectNothingRendered(wrapper) {
    expect(wrapper.find('div').exists()).toBe(false)
    expect(wrapper.find('span').exists()).toBe(false)
    expect(wrapper.html()).not.toMatch(/alert/i)
  }

  it('renders nothing for a record with no alerts', async () => {
    const wrapper = await mountOperational(AlertBadge, { props: {} })

    expectNothingRendered(wrapper)
  })

  it('renders nothing for an explicit zero count', async () => {
    const wrapper = await mountOperational(AlertBadge, { props: { count: 0 } })

    expectNothingRendered(wrapper)
  })

  it('renders nothing when a severity arrives with no alert', async () => {
    const wrapper = await mountOperational(AlertBadge, { props: { severity: 'high' } })

    expectNothingRendered(wrapper)
  })

  it('treats an explicit zero count as no alerts even alongside present', async () => {
    const wrapper = await mountOperational(AlertBadge, {
      props: { count: 0, present: true, showNone: true },
    })

    expect(wrapper.text()).toBe('No alerts')
  })

  it('renders an explicit no-alerts state when asked', async () => {
    const wrapper = await mountOperational(AlertBadge, { props: { showNone: true } })

    expect(wrapper.text()).toBe('No alerts')
    expect(wrapper.html()).toContain('gray')
    expect(wrapper.attributes('aria-label')).toBe('No alerts')
  })

  it('reads presence without a count as a single alert', async () => {
    const wrapper = await mountOperational(AlertBadge, { props: { present: true } })

    expect(wrapper.text()).toBe('1 alert')
  })

  it('uses the caller label for presence when one is supplied', async () => {
    const wrapper = await mountOperational(AlertBadge, {
      props: { present: true, label: 'Guest alerts' },
    })

    expect(wrapper.text()).toBe('Guest alerts')
  })

  it('renders a count', async () => {
    const wrapper = await mountOperational(AlertBadge, { props: { count: 3 } })

    expect(wrapper.text()).toBe('3 alerts')
  })

  it('reads a count of one as one alert, not "1 alerts"', async () => {
    const wrapper = await mountOperational(AlertBadge, { props: { count: 1 } })

    expect(wrapper.text()).toBe('1 alert')
    expect(wrapper.text()).not.toContain('1 alerts')
  })

  it('appends the severity word so severity is never colour-only', async () => {
    const cases = [
      ['high', 'High', 'red'],
      ['medium', 'Medium', 'amber'],
      ['low', 'Low', 'blue'],
    ]

    for (const [severity, word, colour] of cases) {
      const wrapper = await mountOperational(AlertBadge, {
        props: { count: 2, severity },
      })

      expect(wrapper.text()).toContain('2 alerts')
      expect(wrapper.text()).toContain(word)
      expect(wrapper.html()).toContain(colour)
      expect(wrapper.attributes('aria-label')).toBe(`2 alerts ${word}`)
    }
  })

  it('does not print the grade twice when the caller named the alert', async () => {
    const wrapper = await mountOperational(AlertBadge, {
      props: { present: true, severity: 'high', label: 'Blacklisted' },
    })

    // The chip reads as the caller wrote it, with no trailing grade word.
    expect(wrapper.text()).toBe('Blacklisted')
    expect(wrapper.text()).not.toContain('High')
    // The grade is not lost: it still picks the theme...
    expect(wrapper.html()).toContain('red')
    // ...and it is still in text, so it is colour-only for nobody.
    expect(wrapper.attributes('aria-label')).toBe('Blacklisted High')
    expect(wrapper.attributes('title')).toBe('Blacklisted High Details are shown only to authorised staff.')
  })

  it('still shows the grade visibly when there is no caller label', async () => {
    // Regression guard for the case above: a bare presence or a count has no
    // caller wording to lean on, so the grade must stay on screen.
    const presence = await mountOperational(AlertBadge, {
      props: { present: true, severity: 'high' },
    })

    expect(presence.text()).toContain('High')

    const counted = await mountOperational(AlertBadge, {
      props: { count: 4, severity: 'medium' },
    })

    expect(counted.text()).toContain('4 alerts')
    expect(counted.text()).toContain('Medium')
  })

  it('shows the grade for a graded count even when a label was passed', async () => {
    // A count outranks the label, so the chip was not named by the caller.
    const wrapper = await mountOperational(AlertBadge, {
      props: { count: 4, severity: 'high', label: 'Blacklisted' },
    })

    expect(wrapper.text()).toContain('4 alerts')
    expect(wrapper.text()).toContain('High')
    expect(wrapper.text()).not.toContain('Blacklisted')
  })

  it('renders the arrivals board call site as the board renders it today', async () => {
    // <AlertBadge present severity="high" :label="t('common.blacklisted')" />
    // Functional parity with Arrivals.vue: the word "Blacklisted", in red.
    const wrapper = await mountOperational(AlertBadge, {
      props: { present: true, severity: 'high', label: t('common.blacklisted') },
    })

    expect(wrapper.text()).toBe('Blacklisted')
    expect(wrapper.html()).toContain('red')
    expect(wrapper.attributes('aria-label')).toBe('Blacklisted High')
  })

  it('stays neutral when the server graded nothing', async () => {
    const wrapper = await mountOperational(AlertBadge, { props: { count: 2 } })

    expect(wrapper.html()).toContain('gray')
    expect(wrapper.html()).not.toMatch(/red|amber|blue/)
    expect(wrapper.attributes('aria-label')).toBe('2 alerts')
  })

  it('ignores a severity value the component does not know', async () => {
    const wrapper = await mountOperational(AlertBadge, {
      props: { count: 2, severity: 'catastrophic' },
    })

    expect(wrapper.text()).toBe('2 alerts')
    expect(wrapper.html()).toContain('gray')
  })

  it('carries an accessible name and a generic restricted-detail tooltip', async () => {
    const wrapper = await mountOperational(AlertBadge, {
      props: { count: 2, severity: 'high' },
    })

    expect(wrapper.attributes('aria-label')).toBe('2 alerts High')
    expect(wrapper.attributes('title')).toBe('2 alerts High Details are shown only to authorised staff.')
    // Generic: the sentence is identical for every record, so it discloses nothing.
    expect(wrapper.attributes('title')).toContain('Details are shown only to authorised staff.')
  })

  describe('privacy boundary', () => {
    const SENSITIVE = [
      'Fraud – card chargeback',
      'Refused to pay 2024 invoice',
      'Aggressive towards staff, police called',
      'Do not rent: previous damage to room 402',
    ]

    it('declares no prop through which alert detail could arrive', () => {
      const props = Object.keys(AlertBadge.props || {})

      expect(props).toEqual(['count', 'present', 'severity', 'label', 'showNone'])

      for (const key of props) {
        expect(key).not.toMatch(/reason|detail|note|body|message|comment|remark|text|description/i)
      }
    })

    it('drops every attribute that could carry alert text into the DOM', async () => {
      const wrapper = await mountOperational(AlertBadge, {
        props: { count: 2, severity: 'high' },
        attrs: {
          reason: SENSITIVE[0],
          reasons: SENSITIVE[1],
          detail: SENSITIVE[2],
          notes: SENSITIVE[3],
          blacklistReason: SENSITIVE[0],
          'blacklist-reason': SENSITIVE[1],
          'data-reason': SENSITIVE[2],
          'data-alert-detail': SENSITIVE[3],
          title: SENSITIVE[0],
          'aria-label': SENSITIVE[1],
          'aria-description': SENSITIVE[2],
          alt: SENSITIVE[3],
        },
      })

      const html = wrapper.html()

      for (const secret of SENSITIVE) {
        expect(html).not.toContain(secret)
      }

      // The component's own accessible text is untouched by the attempt.
      expect(wrapper.attributes('aria-label')).toBe('2 alerts High')
      expect(wrapper.attributes('title')).toBe('2 alerts High Details are shown only to authorised staff.')
    })

    it('has no slot through which alert text could be injected', async () => {
      const wrapper = await mountOperational(AlertBadge, {
        props: { count: 2 },
        slots: {
          default: `<span>${SENSITIVE[0]}</span>`,
          prefix: `<span>${SENSITIVE[1]}</span>`,
          suffix: `<span>${SENSITIVE[2]}</span>`,
          detail: `<span>${SENSITIVE[3]}</span>`,
        },
      })

      const html = wrapper.html()

      for (const secret of SENSITIVE) {
        expect(html).not.toContain(secret)
      }

      expect(wrapper.text()).toBe('2 alerts')
    })

    it('does not render alert text smuggled through the label prop as a reason', async () => {
      // `label` exists for wording such as "Guest alerts". A count outranks it,
      // so a caller cannot use it to append detail to a counted badge.
      const wrapper = await mountOperational(AlertBadge, {
        props: { count: 2, label: SENSITIVE[0] },
      })

      expect(wrapper.html()).not.toContain(SENSITIVE[0])
      expect(wrapper.text()).toBe('2 alerts')
    })

    it('makes no request of any kind', async () => {
      // A display component that fetched alert detail would defeat the boundary
      // no matter what it rendered. Nothing here may reach the network.
      const wrapper = await mountOperational(AlertBadge, {
        props: { count: 2, severity: 'high' },
      })

      expect(wrapper.text()).toContain('2 alerts')
      expect(wrapper.html()).not.toMatch(/http|api\/method/)
    })
  })

  it('uses Arabic wording and no physical direction utilities in an Arabic session', async () => {
    useArabic()

    const wrapper = await mountOperational(AlertBadge, {
      props: { present: true, severity: 'high' },
    })

    expect(wrapper.text()).toContain('تنبيه واحد')
    expect(wrapper.text()).toContain('عالية')
    expect(wrapper.attributes('title')).toContain('تُعرض التفاصيل للموظفين المصرح لهم فقط.')
    expect(wrapper.html()).not.toMatch(PHYSICAL_CLASSES)
  })

  it('reads as one Arabic phrase when the caller named the alert', async () => {
    useArabic()

    const wrapper = await mountOperational(AlertBadge, {
      props: { present: true, severity: 'high', label: t('common.blacklisted') },
    })

    // "مدرج بالقائمة السوداء", not "مدرج بالقائمة السوداء عالية".
    expect(wrapper.text()).toBe('مدرج بالقائمة السوداء')
    expect(wrapper.text()).not.toContain('عالية')
    // The grade is still spoken, and still in the tooltip, in Arabic.
    expect(wrapper.attributes('aria-label')).toBe('مدرج بالقائمة السوداء عالية')
    expect(wrapper.attributes('title')).toContain('عالية')
    expect(wrapper.html()).toContain('red')
    expect(wrapper.html()).not.toMatch(PHYSICAL_CLASSES)
  })

  it('uses logical utilities in every state', async () => {
    setDirection('rtl')

    const variants = [
      { showNone: true },
      { present: true },
      { count: 4 },
      { count: 4, severity: 'high' },
      { count: 1, severity: 'low' },
    ]

    for (const props of variants) {
      const wrapper = await mountOperational(AlertBadge, { props })

      expect(wrapper.html()).not.toMatch(PHYSICAL_CLASSES)
    }
  })
})
