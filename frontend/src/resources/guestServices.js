import { apiResource } from '@/resources'

/** The guest services board: open requests and complaints for a property. */
export function guestServicesBoardResource() {
  return apiResource('guest_services.board', { method: 'GET' })
}

/** One guest request, with everything the detail dialog needs. */
export function guestRequestResource() {
  return apiResource('guest_services.get_request', { method: 'GET' })
}

/** Raise a guest request or complaint. */
export function createGuestRequestResource() {
  return apiResource('guest_services.create_request')
}

/** Assign a request and record its first response. */
export function assignGuestRequestResource() {
  return apiResource('guest_services.assign')
}

/** Start work on a request. */
export function startGuestRequestResource() {
  return apiResource('guest_services.start')
}

/** Complete a request with a resolution. */
export function completeGuestRequestResource() {
  return apiResource('guest_services.complete')
}

/** Escalate a request by one level. */
export function escalateGuestRequestResource() {
  return apiResource('guest_services.escalate')
}

/** Reopen a completed request the guest was not satisfied with. */
export function reopenGuestRequestResource() {
  return apiResource('guest_services.reopen')
}

/** Close a completed request. */
export function closeGuestRequestResource() {
  return apiResource('guest_services.close')
}

/** Compensate a guest; posts a discount to their folio when there is an amount. */
export function serviceRecoveryResource() {
  return apiResource('guest_services.apply_service_recovery')
}

/**
 * Select options, mirrored from the DocType (SAS section 3.15) so the create
 * form and filters cannot drift from what the server accepts. The server
 * still validates every value; this list is for rendering only.
 */
export const REQUEST_TYPE_OPTIONS = ['Request', 'Complaint']

export const CATEGORY_OPTIONS = [
  'Housekeeping',
  'Maintenance',
  'Front Office',
  'Food and Beverage',
  'Transport',
  'Concierge',
  'IT and Network',
  'Billing',
  'Other',
]

export const PRIORITY_OPTIONS = ['Low', 'Normal', 'High', 'Urgent']

export const RECOVERY_TYPE_OPTIONS = [
  'Apology',
  'Discount',
  'Complimentary Service',
  'Room Upgrade',
  'Folio Adjustment',
  'Loyalty Points',
  'Other',
]

/**
 * Which action ends a request in which status, mirrored from the service's
 * transition table (Workflow Matrix section 9) purely to decide which buttons
 * to offer. The server remains the only authority on whether a transition is
 * actually allowed; an offer that is no longer valid comes back as a normal
 * error for `normaliseError` to surface.
 */
export const REQUEST_ACTION_VISIBILITY = {
  assign: ['Open', 'Assigned', 'Escalated', 'Reopened'],
  start: ['Open', 'Assigned', 'Escalated', 'Reopened'],
  complete: ['In Progress', 'Escalated'],
  escalate: ['Open', 'Assigned', 'In Progress', 'Escalated', 'Reopened'],
  reopen: ['Completed', 'Closed'],
  close: ['Completed'],
}

export function canOffer(action, status) {
  return (REQUEST_ACTION_VISIBILITY[action] || []).includes(status)
}

/** Badge theme per request status, so a request reads at a glance. */
export const REQUEST_STATUS_THEME = {
  Open: 'gray',
  Assigned: 'blue',
  'In Progress': 'blue',
  Completed: 'green',
  Closed: 'gray',
  Escalated: 'red',
  Cancelled: 'gray',
  Reopened: 'orange',
}

export function requestStatusTheme(status) {
  return REQUEST_STATUS_THEME[status] || 'gray'
}

/** Badge theme per priority. */
export const PRIORITY_THEME = {
  Low: 'gray',
  Normal: 'blue',
  High: 'orange',
  Urgent: 'red',
}

export function priorityTheme(priority) {
  return PRIORITY_THEME[priority] || 'gray'
}

/**
 * How far a request is from (or past) its SLA due time, for display only.
 * `is_breached` on the record is only ever stamped once the request completes,
 * so an open request's live position against its clock has to be worked out
 * from `due_by` and the current time here.
 */
export function slaStatus(dueBy, now = new Date()) {
  if (!dueBy) return { overdue: false, minutes: null }

  const due = new Date(dueBy)
  if (Number.isNaN(due.getTime())) return { overdue: false, minutes: null }

  const diffMinutes = Math.round((due.getTime() - now.getTime()) / 60000)

  return { overdue: diffMinutes < 0, minutes: Math.abs(diffMinutes) }
}
