import { apiResource } from '@/resources'

/** The audit this property is currently working on, or its last closed one. */
export function nightAuditCurrentResource() {
  return apiResource('night_audit.get_current', { method: 'GET' })
}

/** Recent audits for the property, most recent business date first. */
export function nightAuditHistoryResource() {
  return apiResource('night_audit.history', { method: 'GET' })
}

/** Open (or resume) the audit for a business date. */
export function startNightAuditResource() {
  return apiResource('night_audit.start')
}

/** Rebuild the day's exceptions and figures. */
export function reviewNightAuditResource() {
  return apiResource('night_audit.review')
}

/** Mark one exception row as dealt with. */
export function resolveExceptionResource() {
  return apiResource('night_audit.resolve_exception')
}

/** Turn today's unresolved arrivals into no-shows. */
export function markNoShowsResource() {
  return apiResource('night_audit.mark_no_shows')
}

/** Post one night's room charge for every in-house stay. */
export function postRoomChargesResource() {
  return apiResource('night_audit.post_room_charges')
}

/** Flag tomorrow's departures for the morning shift. */
export function markDueOutsResource() {
  return apiResource('night_audit.mark_due_outs')
}

/** Check the subledger against ERPNext before a close is possible. */
export function reconcileNightAuditResource() {
  return apiResource('night_audit.reconcile')
}

/** Close the business date and roll the property forward. */
export function closeNightAuditResource() {
  return apiResource('night_audit.close')
}

/** Reopen a closed business date. Manager exception only (service-enforced). */
export function reopenNightAuditResource() {
  return apiResource('night_audit.reopen')
}

/**
 * Night Audit state machine, mirrored from Workflow Matrix section 7 for
 * display only (the ordered-steps rail, and which step reads as "done" or
 * "current"). Whether a given step may actually run is always the server's
 * call — every step endpoint re-checks its own transition.
 */
export const AUDIT_STATUS_THEME = {
  Open: 'gray',
  Reviewing: 'blue',
  Posting: 'blue',
  'Ready to Close': 'green',
  Closed: 'gray',
}

export function auditStatusTheme(status) {
  return AUDIT_STATUS_THEME[status] || 'gray'
}

/** Badge theme per exception severity. Blocking must always read as urgent. */
export const SEVERITY_THEME = {
  Info: 'gray',
  Warning: 'orange',
  Blocking: 'red',
}

export function severityTheme(severity) {
  return SEVERITY_THEME[severity] || 'gray'
}
