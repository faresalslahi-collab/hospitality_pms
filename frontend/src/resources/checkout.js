import { apiResource } from '@/resources'

/** What the guest owes and anything blocking departure. Read-only. */
export function checkoutSummaryResource() {
  return apiResource('checkout.summary', { method: 'GET' })
}

/** Settle, post and release the room. */
export function checkOutResource() {
  return apiResource('checkout.check_out')
}

/** Undo a checkout. Requires front office and finance authority, and a reason. */
export function reverseCheckoutResource() {
  return apiResource('checkout.reverse_checkout')
}
