/**
 * Normalises errors coming back from Frappe so every screen reports failures
 * the same way (Frontend Standards section 13).
 *
 * The distinction that matters operationally is: can the user retry, do they
 * need someone with more permission, or is the record in a state that forbids
 * the action.
 */
import { t } from '@/utils/i18n'

export const ErrorKind = {
  PERMISSION: 'permission',
  VALIDATION: 'validation',
  CONFLICT: 'conflict',
  NETWORK: 'network',
  SERVER: 'server',
}

const PERMISSION_TYPES = ['PermissionError', 'PermissionDeniedError', 'PropertyAccessError']
const CONFLICT_TYPES = [
  'InvalidStateTransitionError',
  'AvailabilityError',
  'DuplicateRequestError',
  // A database deadlock is a contention outcome, not a fault: two operations
  // reached for the same inventory and InnoDB rolled one of them back so the
  // other could finish. Retrying is exactly the right response, which is what
  // makes it a conflict rather than a server error — the same category as an
  // availability clash, and for the same reason.
  //
  // 16.7.2 made this reachable in one narrow case (HPMS-QA-16.7.2-C): the
  // availability count on a commit path is now a current read, which locks every
  // row the optimiser examines, so a room-type change racing a confirmation for
  // the last room of a type can deadlock. That trade was taken deliberately — a
  // deadlock refuses one caller loudly, where the snapshot read it replaced sold
  // the same room twice in silence.
  'QueryDeadlockError',
]

/** @returns {{kind: string, title: string, message: string, retryable: boolean}} */
export function normaliseError(error) {
  if (!error) {
    return kindOf(ErrorKind.SERVER, t('state.error_message'))
  }

  // fetch() rejects with a TypeError when the server cannot be reached at all.
  if (error instanceof TypeError || error.name === 'TypeError') {
    return kindOf(ErrorKind.NETWORK, t('state.offline_message'), t('state.offline_title'))
  }

  const status = error.status || error.statusCode
  const excType = error.exc_type || error.excType || ''
  const message = extractMessage(error)

  if (status === 403 || PERMISSION_TYPES.includes(excType)) {
    return kindOf(ErrorKind.PERMISSION, message || t('state.denied_message'), t('state.denied_title'))
  }

  if (status === 409 || CONFLICT_TYPES.includes(excType)) {
    return kindOf(ErrorKind.CONFLICT, message || t('state.error_message'))
  }

  if (status >= 500) {
    return kindOf(ErrorKind.SERVER, message || t('state.error_message'))
  }

  return kindOf(ErrorKind.VALIDATION, message || t('state.error_message'))
}

/** Pull the human-readable text out of a Frappe error payload. */
function extractMessage(error) {
  if (typeof error === 'string') return stripHtml(error)

  if (Array.isArray(error.messages) && error.messages.length) {
    return stripHtml(error.messages.join('\n'))
  }

  if (error._server_messages) {
    try {
      const parsed = JSON.parse(error._server_messages)
      const first = typeof parsed[0] === 'string' ? JSON.parse(parsed[0]) : parsed[0]
      if (first?.message) return stripHtml(first.message)
    } catch {
      // fall through to the generic message below
    }
  }

  return stripHtml(error.message || '')
}

function stripHtml(value) {
  return String(value)
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function kindOf(kind, message, title) {
  return {
    kind,
    title: title || t('state.error_title'),
    message,
    // A conflict means the operational state moved on; reloading and retrying
    // is meaningful. A permission failure is not retryable by this user.
    retryable: kind === ErrorKind.NETWORK || kind === ErrorKind.SERVER || kind === ErrorKind.CONFLICT,
  }
}
