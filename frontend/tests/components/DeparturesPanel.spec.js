/**
 * Departures, and the action a blocked row is allowed to offer.
 *
 * The panel showed "Cannot check out" in the badge and, right beside it, the
 * same solid "Check out" button every ready row carries. The server refused
 * either way — the checkout screen renders the blockers first and disables its
 * own button while any remain — so nothing was ever bypassed. What was wrong is
 * that a desk scanning the list could not tell a ready row from a blocked one,
 * which is the one thing a departures list is for.
 *
 * The rule these tests pin: readiness is the server's `can_check_out`, and the
 * row's action follows it. Both actions open the same screen, because that
 * screen *is* the blocker workflow.
 */

import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DeparturesPanel from '@/components/dashboard/DeparturesPanel.vue'
import { resetStores, stubProperty, stubSession } from '../helpers'

const push = vi.fn()

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')

  return { ...actual, useRouter: () => ({ push }) }
})

function departure(overrides = {}) {
  return {
    stay: 'HPMS-STAY-2026-00001',
    guest_name: 'Amal Haddad',
    room_number: '101',
    folio: 'HPMS-FOL-2026-00001',
    balance: 0,
    related_folios: 0,
    is_checked_out: false,
    can_check_out: true,
    ...overrides,
  }
}

function mountPanel(rows) {
  return mount(DeparturesPanel, {
    props: { departures: rows, loading: false },
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

/** The row's action button, whatever it currently says. */
function action(wrapper, index = 0) {
  return wrapper.findAll('tbody tr')[index].findAll('button').at(-1)
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Agent'])
  push.mockClear()
})

describe('Departures readiness', () => {
  it('offers the ready row the action that runs', () => {
    const wrapper = mountPanel([departure()])

    expect(wrapper.text()).toContain('Ready to check out')
    expect(action(wrapper).text()).toBe('Check out')
  })

  it('does not offer a blocked row the same ready-to-execute action', () => {
    // The regression. "Cannot check out" beside "Check out" is the screen
    // contradicting itself.
    const wrapper = mountPanel([departure({ can_check_out: false, balance: 250 })])

    expect(wrapper.text()).toContain('Cannot check out')
    expect(action(wrapper).text()).toBe('Review checkout')
    expect(action(wrapper).text()).not.toBe('Check out')
  })

  it('sends both rows to the same screen, which is where the guards are', () => {
    const wrapper = mountPanel([
      departure({ stay: 'READY-1' }),
      departure({ stay: 'BLOCKED-1', can_check_out: false }),
    ])

    // Blocked rows sort first, so the panel's own ranking decides the order.
    for (const [index, row] of wrapper.findAll('tbody tr').entries()) {
      void row
      push.mockClear()
      action(wrapper, index).trigger('click')

      expect(push).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Checkout', params: expect.objectContaining({ stay: expect.any(String) }) }),
      )
    }
  })

  it('leaves a checked-out row on its own secondary action', () => {
    const wrapper = mountPanel([departure({ is_checked_out: true, can_check_out: false })])

    expect(wrapper.text()).toContain('Checked out')
    expect(action(wrapper).text()).toBe('Open folio')
  })

  it('reads readiness from the server, never from the balance', () => {
    // A zero balance is not permission to leave: the server weighs the stay's
    // status and every related folio, and this panel repeats its answer.
    const wrapper = mountPanel([departure({ can_check_out: false, balance: 0 })])

    expect(action(wrapper).text()).toBe('Review checkout')
  })
})
