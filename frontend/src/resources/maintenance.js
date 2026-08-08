import { apiResource } from '@/resources'

/** The maintenance board for a property. */
export function maintenanceBoardResource() {
  return apiResource('maintenance.board', { method: 'GET' })
}

/** One maintenance ticket with its work log. */
export function maintenanceTicketResource() {
  return apiResource('maintenance.get_ticket', { method: 'GET' })
}

/** Raise a maintenance ticket. */
export function createMaintenanceTicketResource() {
  return apiResource('maintenance.create_ticket')
}

/** Assign a ticket to a technician. The server decides who may be assigned. */
export function assignMaintenanceTicketResource() {
  return apiResource('maintenance.assign')
}

/** Start work on a ticket. */
export function startMaintenanceWorkResource() {
  return apiResource('maintenance.start_work')
}

/** Append an entry to a ticket's work log. */
export function logMaintenanceWorkResource() {
  return apiResource('maintenance.log_work')
}

/** Remove a room from sale for maintenance. The server enforces who may do this. */
export function takeOutOfServiceResource() {
  return apiResource('maintenance.take_out_of_service')
}

/** Technician finishes work; the room still awaits verification. */
export function completeMaintenanceWorkResource() {
  return apiResource('maintenance.complete_work')
}

/** Verify completed work and, if it passed, release the room back to sale. */
export function verifyAndReleaseResource() {
  return apiResource('maintenance.verify_and_release')
}

/**
 * Ticket classification values, mirrored from the DocType selects for
 * rendering only. The server remains authoritative about the value itself.
 */
export const TICKET_CATEGORIES = [
  'Electrical',
  'Plumbing',
  'HVAC',
  'Furniture',
  'Appliance',
  'IT and Network',
  'Safety',
  'Structural',
  'Other',
]

export const TICKET_TYPES = ['Corrective', 'Preventive', 'Inspection', 'Improvement']

export const TICKET_PRIORITIES = ['Urgent', 'High', 'Normal', 'Low']

export const OUT_OF_SERVICE_STATUSES = ['Out of Service', 'Out of Order']

/** Rank used to sort the board by priority (most urgent first), then room. */
export function priorityRank(priority) {
  const index = TICKET_PRIORITIES.indexOf(priority)
  return index === -1 ? TICKET_PRIORITIES.length : index
}

/** Badge theme per ticket status, so a ticket reads at a glance across the board. */
export const TICKET_STATUS_THEME = {
  Open: 'gray',
  'In Progress': 'orange',
  Verification: 'blue',
  Completed: 'green',
  Cancelled: 'gray',
}

export function ticketStatusTheme(status) {
  return TICKET_STATUS_THEME[status] || 'gray'
}

/** Badge theme per priority. */
export const PRIORITY_THEME = {
  Urgent: 'red',
  High: 'orange',
  Normal: 'blue',
  Low: 'gray',
}

export function priorityTheme(priority) {
  return PRIORITY_THEME[priority] || 'gray'
}
