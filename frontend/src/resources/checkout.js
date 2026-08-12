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

/**
 * ERP posting and reconciliation.
 *
 * Bound in 16.7.5. All four endpoints existed and were gated on
 * `RECONCILIATION_ROLES` — Finance Manager, Accounts User, Night Auditor,
 * Hotel Manager, General Manager and the administrators. Front Office is
 * deliberately absent from that list and must stay absent: the posting-service
 * identity lets a front-desk checkout *execute* a posting, it does not let
 * anyone read the accounting documents behind it.
 */

/** One folio compared against what actually reached ERPNext. */
export function reconcileFolioResource() {
  return apiResource('checkout.reconcile_folio', { method: 'GET' })
}

/** The property's failed postings, with operator-safe messages. */
export function reconciliationResource() {
  return apiResource('checkout.reconciliation', { method: 'GET' })
}

/**
 * Retry one failed posting under its original key.
 *
 * Offer this only where the server said `can_retry`. A posting whose outcome is
 * unknown is deliberately not retryable — repeating it could double-post — and
 * pressing it anyway raises rather than acts.
 */
export function retryPostingResource() {
  return apiResource('checkout.retry_posting')
}

/** Push a folio's unposted charges to ERPNext now. */
export function postFolioResource() {
  return apiResource('checkout.post_folio')
}

/**
 * Operator-facing categories the server returns for a failed posting.
 *
 * Mirrored for badge colour only. The server derives the category and
 * `can_retry`; this file never decides either.
 */
export const POSTING_CATEGORY_THEME = {
  'Retry Available': 'orange',
  'Accounting Configuration': 'orange',
  'Reconciliation Required': 'red',
  'Needs Finance Review': 'red',
  'Posting Failed': 'red',
}

export function postingCategoryTheme(category) {
  return POSTING_CATEGORY_THEME[category] || 'gray'
}
