/**
 * ActionDrawer — the shell for contextual operational detail beside a board.
 *
 * The behaviour under test is almost entirely behaviour a screenshot cannot
 * show: where focus goes when the panel opens, where it goes back to when it
 * closes, that Tab cannot walk out of it, and that nothing in the markup assumes
 * the panel is on the right. Those are the things that quietly break.
 *
 * The panel teleports to `document.body`, so assertions query the document
 * rather than the wrapper.
 */
import { describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'

import ActionDrawer from '@/components/operational/ActionDrawer.vue'
import { flush, mountOperational, useArabic } from '../helpers'

const PANEL = '[data-drawer-panel]'
const OVERLAY = '[data-drawer-overlay]'
const CONTENT = '[data-drawer-content]'

function panelEl() {
  return document.body.querySelector(PANEL)
}

function contentEl() {
  return document.body.querySelector(CONTENT)
}

async function open(props = {}, slots = {}) {
  const wrapper = await mountOperational(ActionDrawer, {
    props: { modelValue: true, title: 'Ms Al Sayed · Room 412', ...props },
    slots,
  })

  await flush(wrapper)

  return wrapper
}

function press(key, options = {}) {
  const target = panelEl() || document.body

  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...options }))
}

describe('ActionDrawer', () => {
  it('renders nothing while closed and the panel once opened', async () => {
    const wrapper = await mountOperational(ActionDrawer, {
      props: { modelValue: false, title: 'Ms Al Sayed' },
    })

    expect(panelEl()).toBeNull()
    expect(document.body.querySelector(OVERLAY)).toBeNull()

    await wrapper.setProps({ modelValue: true })
    await flush(wrapper)

    expect(panelEl()).not.toBeNull()
    expect(document.body.querySelector(OVERLAY)).not.toBeNull()
  })

  it('renders the title, the subtitle and the contextual content', async () => {
    await open(
      { subtitle: 'Arriving today · 2 nights' },
      { default: '<p>Folio balance QAR 1,240.00</p>' },
    )

    const panel = panelEl()

    expect(panel.textContent).toContain('Ms Al Sayed · Room 412')
    expect(panel.textContent).toContain('Arriving today · 2 nights')
    expect(contentEl().textContent).toContain('Folio balance QAR 1,240.00')
  })

  it('renders footer actions and lets them be clicked', async () => {
    const clicks = []

    await open(
      {},
      {
        footer: () =>
          h(
            'button',
            { type: 'button', 'data-test': 'check-in', onClick: () => clicks.push('check-in') },
            'Check in',
          ),
      },
    )

    const action = document.body.querySelector('[data-test="check-in"]')

    expect(action).not.toBeNull()

    action.click()

    expect(clicks).toEqual(['check-in'])
  })

  it('closes on Escape', async () => {
    const wrapper = await open()

    press('Escape')
    await flush(wrapper)

    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('ignores Escape when closeOnEscape is false', async () => {
    const wrapper = await open({ closeOnEscape: false })

    press('Escape')
    await flush(wrapper)

    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('closes on an overlay click', async () => {
    const wrapper = await open()

    document.body.querySelector(OVERLAY).click()
    await flush(wrapper)

    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('ignores an overlay click when closeOnOverlay is false', async () => {
    const wrapper = await open({ closeOnOverlay: false })

    document.body.querySelector(OVERLAY).click()
    await flush(wrapper)

    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('moves focus into the panel on open', async () => {
    await open({}, { default: '<input data-test="reason" />' })

    expect(panelEl().contains(document.activeElement)).toBe(true)
  })

  it('falls back to the close button when the content has nothing focusable', async () => {
    await open({}, { default: '<p>Nothing to focus here.</p>' })

    expect(document.activeElement).toBe(document.body.querySelector('[data-drawer-close]'))
  })

  /**
   * The whole point of the return-focus contract: a keyboard user who opened the
   * panel from a row action must land back on that row action.
   */
  it('returns focus to the triggering element on close', async () => {
    const Harness = defineComponent({
      components: { ActionDrawer },
      setup() {
        return { drawerOpen: ref(false) }
      },
      template: `
        <div>
          <button type="button" data-test="trigger" @click="drawerOpen = true">Open</button>
          <ActionDrawer v-model="drawerOpen" title="Ms Al Sayed · Room 412">
            <p>Detail</p>
          </ActionDrawer>
        </div>
      `,
    })

    const wrapper = await mountOperational(Harness)
    const trigger = wrapper.get('[data-test="trigger"]').element

    trigger.focus()
    expect(document.activeElement).toBe(trigger)

    trigger.click()
    await flush(wrapper)
    await nextTick()

    expect(panelEl()).not.toBeNull()
    expect(panelEl().contains(document.activeElement)).toBe(true)

    document.body.querySelector('[data-drawer-close]').click()
    await flush(wrapper)

    expect(panelEl()).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })

  it('wraps focus at both ends of the panel', async () => {
    const wrapper = await open(
      {},
      {
        default: '<input data-test="reason" />',
        footer: '<button type="button" data-test="confirm">Confirm</button>',
      },
    )

    const focusable = Array.from(
      panelEl().querySelectorAll('button, input, a[href], select, textarea, [tabindex]:not([tabindex="-1"])'),
    )
    const first = focusable[0]
    const last = focusable[focusable.length - 1]

    expect(first).toBe(document.body.querySelector('[data-drawer-close]'))
    expect(last).toBe(document.body.querySelector('[data-test="confirm"]'))

    last.focus()
    press('Tab')
    await flush(wrapper)

    expect(document.activeElement).toBe(first)

    first.focus()
    press('Tab', { shiftKey: true })
    await flush(wrapper)

    expect(document.activeElement).toBe(last)
  })

  it('pins itself to the logical end and uses no physical direction classes', async () => {
    useArabic()

    await open({}, { footer: '<button type="button">Confirm</button>' })

    const panel = panelEl()

    expect(panel.className).toContain('end-0')
    expect(panel.className).toContain('inset-y-0')
    expect(panel.className).toContain('border-s')

    // The whole rendered panel, not just the root: a physical class anywhere in
    // it breaks the Arabic layout, and this is the assertion that catches it.
    const html = document.body.querySelector('.fixed.inset-0').outerHTML
    const physical = html.match(/class="[^"]*"/g).join(' ')

    expect(physical).not.toMatch(/(^|[\s"])(ml-|mr-|pl-|pr-|left-|right-)/)
    expect(physical).not.toMatch(/text-(left|right)\b/)
  })

  it('is full width on a phone and constrained from sm up, per the width prop', async () => {
    const wrapper = await open({ width: 'lg' })

    expect(panelEl().className).toContain('w-full')
    expect(panelEl().className).toContain('sm:max-w-lg')

    await wrapper.setProps({ width: 'sm' })
    await flush(wrapper)

    expect(panelEl().className).toContain('sm:max-w-sm')
    expect(panelEl().className).not.toContain('sm:max-w-lg')

    // An unknown width falls back rather than rendering an unconstrained panel.
    await wrapper.setProps({ width: 'enormous' })
    await flush(wrapper)

    expect(panelEl().className).toContain('sm:max-w-md')
  })

  it('shows the loading state in the content area, with the header still usable', async () => {
    await open({ loading: true }, { default: '<p data-test="detail">Detail</p>' })

    expect(contentEl().textContent).toContain('Loading')
    expect(contentEl().querySelector('[data-test="detail"]')).toBeNull()
    expect(document.body.querySelector('[data-drawer-close]')).not.toBeNull()
  })

  it('shows a normalised error in the content area', async () => {
    await open({ error: { status: 403 } }, { default: '<p data-test="detail">Detail</p>' })

    expect(contentEl().textContent).toContain('Not permitted')
    expect(contentEl().textContent).toContain('permission')
    expect(contentEl().querySelector('[data-test="detail"]')).toBeNull()
    expect(document.body.querySelector('[data-drawer-close]')).not.toBeNull()
  })

  it('is a labelled modal dialog', async () => {
    await open()

    const panel = panelEl()

    expect(panel.getAttribute('role')).toBe('dialog')
    expect(panel.getAttribute('aria-modal')).toBe('true')

    const labelId = panel.getAttribute('aria-labelledby')

    expect(labelId).toBeTruthy()
    expect(panel.querySelector(`#${labelId}`).textContent).toContain('Ms Al Sayed · Room 412')
  })

  it('locks page scroll while open and releases it on close and on unmount', async () => {
    const wrapper = await open()

    expect(document.body.style.overflow).toBe('hidden')

    await wrapper.setProps({ modelValue: false })
    await flush(wrapper)

    expect(document.body.style.overflow).toBe('')

    const second = await open()

    expect(document.body.style.overflow).toBe('hidden')

    // Unmounted while still open — a board that navigated away — must not leave
    // the page unscrollable.
    second.unmount()

    expect(document.body.style.overflow).toBe('')
  })
})
