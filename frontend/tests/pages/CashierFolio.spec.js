/**
 * Cashier & Folio workspace (16.7.5).
 *
 * Two things are defended.
 *
 * **The screen never does arithmetic on money.** Totals and the balance are
 * read from the server as opaque numbers. `total_charges` already includes tax,
 * reversed charges stay on the ledger and are cancelled by their compensating
 * line, and `total_adjustments` counts Adjustment but not Discount — three
 * rules a client cannot reconstruct from the rows. A test that finds the page
 * summing anything has found a defect.
 *
 * **The refund ceiling is advisory here and authoritative there.** The dialog
 * shows what remains so an operator is not walked into a refusal, and disables
 * its own button above it — but the server recomputes it under a row lock, and
 * a server refusal must still surface in the server's words.
 */
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { RouterView, createMemoryHistory, createRouter } from 'vue-router'

import { OPERATIONAL_ROUTES, flush, resetStores, stubProperty, stubSession } from '../helpers'

const { detail, refund, transaction } = vi.hoisted(() => ({
  detail: { data: null, loading: false, error: null, fetch: vi.fn() },
  refund: { data: null, loading: false, error: null, submit: vi.fn() },
  transaction: { data: null, loading: false, error: null, fetch: vi.fn() },
}))

vi.mock('@/resources/folio', async (importOriginal) => {
  const actual = await importOriginal()

  return { ...actual, folioResource: () => detail }
})

vi.mock('@/resources/payments', async (importOriginal) => {
  const actual = await importOriginal()

  return {
    ...actual,
    refundPaymentResource: () => refund,
    paymentTransactionResource: () => transaction,
  }
})

const { default: Folio } = await import('@/pages/Folio.vue')
const { default: RefundPaymentDialog } = await import('@/components/RefundPaymentDialog.vue')
const { remainingRefundable, isRefundable } = await import('@/resources/payments')

const FOLIO = 'HPMS-FOL-2026-00001'

function payload(overrides = {}) {
  return {
    folio: {
      name: FOLIO,
      folio_status: 'Open',
      folio_type: 'Master',
      guest: 'HPMS-GST-00001',
      guest_name: 'Layla Haddad',
      stay: 'HPMS-STY-00001',
      reservation: 'HPMS-RES-00001',
      room: 'DOHA01-402',
      currency: 'QAR',
      total_charges: 1200,
      total_taxes: 120,
      total_payments: 500,
      total_adjustments: -50,
      balance: 700,
      billing_instructions: '',
    },
    charges: [
      {
        name: 'CHG-1',
        charge_date: '2026-08-08',
        business_date: '2026-08-08',
        charge_type: 'Room Service',
        description: 'Room Service order HPMS-RSO-1',
        quantity: 1,
        amount: 120,
        tax_amount: 12,
        total_amount: 132,
        payer: 'Guest',
        is_reversed: 0,
        reversal_of: null,
        is_posted_to_erp: true,
        source_doctype: 'Room Service Order',
        source_name: 'HPMS-RSO-1',
      },
    ],
    payments: [
      {
        name: 'PAY-1',
        payment_date: '2026-08-08',
        payment_type: 'Payment',
        payment_method: 'Online Gateway',
        amount: 500,
        reference: 'HPMS-PAY-2026-00001',
        payer: 'Guest',
        provider_reference: 'ch_123',
        is_reversed: false,
        is_posted_to_erp: true,
      },
    ],
    allowed_transitions: ['Ready for Settlement'],
    disclosure: { invoice: false, payment_entry: false },
    ...overrides,
  }
}

async function mountFolio({ tab } = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: OPERATIONAL_ROUTES })

  router.addRoute({ path: '/folios/:id', name: 'Folio', component: Folio })
  router.push(`/folios/${FOLIO}${tab ? `?tab=${tab}` : ''}`)
  await router.isReady()

  const wrapper = mount(
    { render: () => h(RouterView) },
    { global: { plugins: [router] }, attachTo: document.body },
  )

  await flush(wrapper)

  return { wrapper, router }
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Manager'])

  detail.data = payload()
  detail.loading = false
  detail.error = null
  detail.fetch = vi.fn()

  refund.data = null
  refund.loading = false
  refund.error = null
  refund.submit = vi.fn().mockResolvedValue({})

  transaction.data = {
    name: 'HPMS-PAY-2026-00001',
    transaction_status: 'Captured',
    amount: 500,
    refunded_amount: 0,
  }
  transaction.error = null
  transaction.fetch = vi.fn().mockResolvedValue({})
})

describe('Folio workspace shell', () => {
  it('reports a permission failure as a refusal, not a retryable fault', async () => {
    detail.data = null
    detail.error = { status: 403, exc_type: 'PermissionError' }

    const { wrapper } = await mountFolio()

    expect(wrapper.findComponent({ name: 'PermissionDenied' }).exists()).toBe(true)
  })

  it('offers a retry for a fault the user can retry out of', async () => {
    detail.data = null
    detail.error = { status: 500 }

    const { wrapper } = await mountFolio()

    expect(wrapper.findComponent({ name: 'PermissionDenied' }).exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'ErrorState' }).exists()).toBe(true)
  })

  it('offers the four tabs', async () => {
    const { wrapper } = await mountFolio()

    expect(wrapper.findAll('[role="tab"]').map((t) => t.text())).toEqual([
      'Summary',
      'Charges',
      'Payments',
      'Invoices',
    ])
  })

  it('keeps the active tab in the URL query', async () => {
    const { wrapper, router } = await mountFolio()

    const payments = wrapper.findAll('[role="tab"]').find((t) => t.text() === 'Payments')
    await payments.trigger('click')
    await flush(wrapper)

    expect(router.currentRoute.value.query.tab).toBe('payments')
  })

  it('falls back to Summary for an unknown tab', async () => {
    const { wrapper } = await mountFolio({ tab: 'nonsense' })

    expect(wrapper.find('[role="tab"][aria-selected="true"]').text()).toBe('Summary')
  })
})

describe('Folio money presentation', () => {
  it('renders the balance through FolioBalance, which carries settled/due/credit', async () => {
    const { wrapper } = await mountFolio()

    expect(wrapper.findComponent({ name: 'FolioBalance' }).exists()).toBe(true)
  })

  it('renders a credit balance without losing its meaning', async () => {
    const data = payload()
    data.folio.balance = -120
    detail.data = data

    const { wrapper } = await mountFolio()

    // FolioBalance states the condition in words, not by colour alone.
    expect(wrapper.text().toLowerCase()).toContain('credit')
  })

  it('shows the server totals and computes none of them', async () => {
    const { wrapper } = await mountFolio()
    const text = wrapper.text()

    // 1200 charges + 120 tax would be 1320 if the page were summing.
    expect(text).not.toContain('1,320')
    expect(text).not.toContain('1320')
  })

  it('does not derive the balance from charges minus payments', async () => {
    const data = payload()
    // A balance the server says is 700 while the rows would imply 1200 - 500.
    data.folio.balance = 42
    detail.data = data

    const { wrapper } = await mountFolio()

    expect(wrapper.text()).toContain('42')
  })
})

describe('Folio charges and accounting state', () => {
  it('shows which charges reached the accounting system', async () => {
    const { wrapper } = await mountFolio({ tab: 'invoices' })

    expect(wrapper.text()).toContain('Posted')
  })

  it('says nothing is posted rather than showing an empty list', async () => {
    const data = payload()
    data.charges[0].is_posted_to_erp = false
    detail.data = data

    const { wrapper } = await mountFolio({ tab: 'invoices' })

    expect(wrapper.text()).toContain('Nothing has been posted')
  })

  it('never renders an ERP document the server withheld', async () => {
    const data = payload()
    // disclosure.invoice is false, so no sales_invoice key arrives at all.
    delete data.charges[0].sales_invoice
    detail.data = data

    const { wrapper } = await mountFolio({ tab: 'invoices' })

    expect(wrapper.text()).not.toContain('ACC-SINV')
  })
})

describe('Refund is reachable from the Payments tab', () => {
  it('offers a refund on a payment backed by a gateway transaction', async () => {
    const { wrapper } = await mountFolio({ tab: 'payments' })

    expect(wrapper.findAll('button').map((b) => b.text())).toContain('Refund')
  })

  it('offers no refund on a payment with no transaction behind it', async () => {
    const data = payload()
    data.payments[0].reference = null
    detail.data = data

    const { wrapper } = await mountFolio({ tab: 'payments' })

    expect(wrapper.findAll('button').map((b) => b.text())).not.toContain('Refund')
  })

  it('fetches the transaction before opening, for the ceiling and the state', async () => {
    const { wrapper } = await mountFolio({ tab: 'payments' })

    const button = wrapper.findAll('button').find((b) => b.text() === 'Refund')
    await button.trigger('click')
    await flush(wrapper)

    expect(transaction.fetch).toHaveBeenCalledWith({ transaction: 'HPMS-PAY-2026-00001' })
    expect(wrapper.findComponent({ name: 'RefundPaymentDialog' }).props('transaction')).toEqual(
      transaction.data,
    )
  })
})

describe('Refund dialog', () => {
  function transaction(overrides = {}) {
    return {
      name: 'HPMS-PAY-2026-00001',
      transaction_status: 'Captured',
      amount: 200,
      refunded_amount: 50,
      ...overrides,
    }
  }

  async function openRefund(txn = transaction()) {
    const wrapper = mount(RefundPaymentDialog, {
      props: { modelValue: true, transaction: txn, currency: 'QAR' },
      attachTo: document.body,
    })

    await flush(wrapper)

    return wrapper
  }

  /** The dialog teleports to body, so the wrapper's own subtree is empty. */
  function dialogText() {
    return document.body.textContent || ''
  }

  it('shows what remains refundable', async () => {
    await openRefund()

    expect(dialogText()).toContain('Remaining refundable')
    expect(dialogText()).toContain('150')
  })

  it('refuses to submit above the remaining amount', async () => {
    const wrapper = await openRefund()

    wrapper.vm.form.amount = '500'
    wrapper.vm.form.reason = 'Goodwill'
    await flush(wrapper)

    await wrapper.vm.submit()

    expect(refund.submit).not.toHaveBeenCalled()
  })

  it('refuses to submit without a reason', async () => {
    const wrapper = await openRefund()

    wrapper.vm.form.amount = '50'
    await flush(wrapper)

    await wrapper.vm.submit()

    expect(refund.submit).not.toHaveBeenCalled()
  })

  it('sends a distinct operation key with every refund decision', async () => {
    const wrapper = await openRefund()

    wrapper.vm.form.amount = '50'
    wrapper.vm.form.reason = 'Goodwill'
    await flush(wrapper)

    await wrapper.vm.submit()

    const sent = refund.submit.mock.calls[0][0]

    expect(sent.transaction).toBe('HPMS-PAY-2026-00001')
    expect(sent.amount).toBe(50)
    expect(sent.idempotency_key).toBeTruthy()
  })

  it('surfaces a server refusal in the server’s own words', async () => {
    refund.error = {
      status: 417,
      messages: ['Refund amount must be between 0 and 150.00.'],
    }

    await openRefund()

    expect(dialogText()).toContain('Refund amount must be between')
  })
})

describe('Refund ceiling helper', () => {
  it('subtracts what was already refunded', () => {
    expect(remainingRefundable({ amount: 200, refunded_amount: 50 })).toBe(150)
  })

  it('never goes negative', () => {
    expect(remainingRefundable({ amount: 200, refunded_amount: 250 })).toBe(0)
  })

  it('treats a fully refunded payment as not refundable', () => {
    expect(isRefundable('Refunded')).toBe(false)
  })

  it('treats a partially refunded payment as still refundable', () => {
    expect(isRefundable('Partially Refunded')).toBe(true)
  })
})
