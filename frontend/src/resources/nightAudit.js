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
 * The seven steps, in the order they run, each named for the evidence that
 * proves it happened.
 *
 * `evidence` is a field on the audit record the *server* stamps when the step
 * completes. A step reads as done when its stamp is present and never otherwise.
 * This replaces deriving completion from `audit_status`, which was wrong in a
 * way an auditor could act on: one status covers more than one step, so a rail
 * keyed on status ticked "Mark No-shows" as complete the moment charges posted,
 * whether or not the sweep had ever run.
 *
 * `action` is what the button says. Never "Run" — an auditor at 3am should be
 * able to read the button and know what is about to happen to the day.
 */
export const AUDIT_STEPS = [
  { key: 'start', evidence: 'started_on', action: 'page.night_audit.action.start' },
  { key: 'review', evidence: 'review_completed_on', action: 'page.night_audit.action.review' },
  { key: 'mark_no_shows', evidence: 'no_shows_completed_on', action: 'page.night_audit.action.no_shows' },
  { key: 'post_room_charges', evidence: 'posting_completed_on', action: 'page.night_audit.action.post_charges' },
  { key: 'mark_due_outs', evidence: 'due_outs_completed_on', action: 'page.night_audit.action.due_outs' },
  { key: 'reconcile', evidence: 'reconciliation_completed_on', action: 'page.night_audit.action.reconcile' },
  { key: 'close', evidence: 'closed_on', action: 'page.night_audit.action.close' },
]

/** The one status from which the server will accept a close. */
export const READY_TO_CLOSE = 'Ready to Close'

/**
 * Each step's presentation state, and which one the auditor is on.
 *
 * Presentation only. Every endpoint re-checks its own transition, so this
 * decides what to *show*, never what is permitted: `close` is offered on the
 * server's own `audit_status` and `blocking_count` and this file re-derives
 * neither.
 *
 * The first step without evidence is the current one. A step after it is
 * pending. `close` additionally reads as blocked — visible, named, not
 * actionable — whenever the server has not put the audit in Ready to Close or
 * has reported blocking exceptions.
 *
 * @param {object|null} audit the `audit` block of `night_audit.get_current`
 * @param {number} blockingCount the server's own `blocking_count`
 */
export function auditStepStates(audit, blockingCount = 0) {
  const record = audit || {}
  let currentSeen = false

  return AUDIT_STEPS.map((step, index) => {
    const done = Boolean(record[step.evidence])
    let state = 'pending'

    if (done) {
      // Complete, but *after* the step the operator is on. The server's evidence
      // is not hidden or softened - the stamp is real and the step did run - but
      // presenting it in the same green as the steps behind the marker reads as
      // "you have been through this", which the operator has not. A close is a
      // sequence, and a later step carrying an earlier stamp is worth noticing
      // rather than smoothing over: it usually means a previous run got that far
      // before the day was reopened.
      state = currentSeen ? 'recorded' : 'done'
    } else if (!currentSeen) {
      currentSeen = true
      state = 'current'
    }

    if (step.key === 'close' && state === 'current' && !canCloseNow(record, blockingCount)) {
      state = 'blocked'
    }

    return { ...step, index, position: index + 1, state, completedOn: record[step.evidence] || null }
  })
}

/**
 * Whether the server is currently in a state that accepts a close.
 *
 * Both halves are the server's own words — the status it set and the count it
 * reported. Nothing here re-implements the blocking-severity rule that
 * `night_audit.close()` enforces, and a `true` from this function is still only
 * a prediction: the close endpoint decides.
 */
export function canCloseNow(audit, blockingCount = 0) {
  return Boolean(audit) && audit.audit_status === READY_TO_CLOSE && !blockingCount
}

/** How many steps the server has evidence for. */
export function completedStepCount(audit) {
  return AUDIT_STEPS.filter((step) => Boolean((audit || {})[step.evidence])).length
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
