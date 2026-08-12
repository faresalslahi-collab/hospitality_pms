import { apiResource } from '@/resources'

/**
 * Payment transactions: gateway initiation, status and refunds.
 *
 * Bound to the frontend for the first time in 16.7.5. The endpoints existed and
 * were role-gated; nothing called them, so a refund could only be issued from
 * Desk.
 *
 * The server owns every decision here. It owns the state graph (a transition
 * this file does not know about is still legal; one it thinks it knows is still
 * refused), it owns the refundable ceiling, and it owns whether a repeated
 * submit is the same operation or a new one.
 */

/** Start a gateway payment against a folio. */
export function initiatePaymentResource() {
  return apiResource('payments.initiate')
}

/** One payment transaction. */
export function paymentTransactionResource() {
  return apiResource('payments.get_transaction', { method: 'GET' })
}

/**
 * Ask the provider what actually happened.
 *
 * The recovery path for a callback that never arrived. It is a live call to the
 * gateway on every invocation, so it belongs behind an explicit operator
 * action, never a poll.
 */
export function syncPaymentStatusResource() {
  return apiResource('payments.sync_status')
}

/**
 * Refund all or part of a captured payment.
 *
 * `idempotency_key` is **required** since 16.7.5. Without one the server
 * derived `refund:{transaction}:{amount}`, which is a content hash — and a
 * content hash cannot tell two goodwill refunds of the same amount from one
 * refund sent twice. The second one silently refunded nothing and reported
 * success. Mint one key per operator decision and reuse it across retries of
 * that decision; `useOperationKey` does exactly this.
 */
export function refundPaymentResource() {
  return apiResource('payments.refund')
}

/**
 * Payment states, mirrored from the server for rendering only.
 *
 * The server's `ALLOWED_TRANSITIONS` is authoritative. This list exists to pick
 * a badge colour, never to decide what may happen next — a screen that computed
 * transitions would be a second state machine, and the two would drift.
 */
export const PAYMENT_STATE_THEME = {
  Initiated: 'gray',
  Pending: 'orange',
  Authorised: 'blue',
  Captured: 'green',
  Failed: 'red',
  Cancelled: 'gray',
  'Partially Refunded': 'orange',
  Refunded: 'gray',
}

export function paymentStateTheme(state) {
  return PAYMENT_STATE_THEME[state] || 'gray'
}

/**
 * States the server will consider refunding.
 *
 * Mirrors `services.payments.REFUNDABLE_STATES`. `Refunded` is deliberately
 * absent: it is terminal. Used only to decide whether to offer the control —
 * the server re-checks under a lock, and its answer is the one that counts.
 */
export const REFUNDABLE_STATES = ['Captured', 'Partially Refunded']

export function isRefundable(state) {
  return REFUNDABLE_STATES.includes(state)
}

/**
 * What is still refundable on a transaction.
 *
 * Advisory only. The server recomputes this under a row lock and refuses
 * anything above it, which is what stops two concurrent partial refunds from
 * together exceeding the capture. Displaying it saves the operator a refusal;
 * it does not enforce anything.
 */
export function remainingRefundable(transaction) {
  if (!transaction) return null

  const amount = Number(transaction.amount)
  const refunded = Number(transaction.refunded_amount || 0)

  if (Number.isNaN(amount)) return null

  return Math.max(amount - refunded, 0)
}
