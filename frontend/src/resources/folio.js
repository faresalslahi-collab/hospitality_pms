import { apiResource } from '@/resources'

/** One folio with its charges, payments, balance and reachable statuses. */
export function folioResource() {
  return apiResource('folio.get_folio', { method: 'GET' })
}

export function postChargeResource() {
  return apiResource('folio.post_charge')
}

export function postPaymentResource() {
  return apiResource('folio.post_payment')
}

/** A correction is a reversal, never an edit: it posts a compensating line. */
export function reverseChargeResource() {
  return apiResource('folio.reverse_charge')
}

export function postAdjustmentResource() {
  return apiResource('folio.post_adjustment')
}

/** Move selected charges onto a new folio, e.g. for company-pay separation. */
export function splitFolioResource() {
  return apiResource('folio.split_folio')
}

export function folioTransitionResource() {
  return apiResource('folio.transition')
}

/**
 * Select options mirrored from the DocType, for rendering only. The server
 * remains authoritative about which value is legal in a given state.
 */
export const CHARGE_TYPE_OPTIONS = [
  'Room Charge',
  'Service Charge',
  'Tax',
  'Tourism Fee',
  'Municipality Fee',
  'Room Service',
  'Minibar',
  'Laundry',
  'Transport',
  'Telephone',
  'Miscellaneous',
  'Adjustment',
  'Discount',
]

export const PAYMENT_TYPE_OPTIONS = ['Deposit', 'Payment', 'Refund', 'Credit']

export const PAYMENT_METHOD_OPTIONS = [
  'Cash',
  'Credit Card',
  'Debit Card',
  'Bank Transfer',
  'Cheque',
  'City Ledger',
  'Voucher',
  'Online Gateway',
]

export const PAYER_OPTIONS = ['Guest', 'Company', 'Travel Agent']

/** Folio status state machine, mirrored from the server for display only. */
export const FOLIO_STATUS_THEME = {
  Open: 'blue',
  'Under Review': 'orange',
  Disputed: 'red',
  'Ready for Settlement': 'orange',
  'Partially Settled': 'orange',
  Settled: 'green',
  Closed: 'gray',
}

export function folioStatusTheme(status) {
  return FOLIO_STATUS_THEME[status] || 'gray'
}
