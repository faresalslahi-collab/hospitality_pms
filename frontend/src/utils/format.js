/**
 * Locale-aware presentation helpers.
 *
 * Formatting is presentation only. Amounts, taxes and totals are always
 * calculated on the server; these helpers must never round a value that will be
 * sent back for posting.
 */
import { locale } from '@/utils/i18n'

/** Intl locale tag for the active UI language. */
function tag() {
  return locale.value === 'ar' ? 'ar' : 'en-GB'
}

/** `2026-08-08` -> `08 Aug 2026` in the active locale. */
export function formatDate(value, options = {}) {
  if (!value) return ''

  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  return new Intl.DateTimeFormat(tag(), {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    ...options,
  }).format(date)
}

/** Date plus time, for audit trails and shift handover. */
export function formatDateTime(value) {
  return formatDate(value, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Number formatting with an explicit precision. */
export function formatNumber(value, precision = 2) {
  if (value === null || value === undefined || value === '') return ''

  return new Intl.NumberFormat(tag(), {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  }).format(Number(value))
}

/**
 * Currency formatting.
 *
 * The currency code always comes from the property or the document; it is never
 * assumed, because a bench may run several companies with different currencies.
 */
export function formatCurrency(value, currency, precision = 2) {
  if (value === null || value === undefined || value === '') return ''

  if (!currency) return formatNumber(value, precision)

  return new Intl.NumberFormat(tag(), {
    style: 'currency',
    currency,
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  }).format(Number(value))
}

/** `2026-08-08` for sending to the server; never locale formatted. */
export function toServerDate(date) {
  if (!date) return null

  const value = date instanceof Date ? date : new Date(date)
  if (Number.isNaN(value.getTime())) return null

  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')

  return `${value.getFullYear()}-${month}-${day}`
}
