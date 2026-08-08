import { apiResource } from '@/resources'

/** The housekeeping board for a property and day. */
export function housekeepingBoardResource() {
  return apiResource('housekeeping.board', { method: 'GET' })
}

/** One housekeeping task. */
export function housekeepingTaskResource() {
  return apiResource('housekeeping.get_task', { method: 'GET' })
}

/** Assign a task to a room attendant. The server decides who may be assigned. */
export function assignHousekeepingTaskResource() {
  return apiResource('housekeeping.assign')
}

/** Start cleaning. */
export function startHousekeepingTaskResource() {
  return apiResource('housekeeping.start')
}

/** Finish cleaning. */
export function completeHousekeepingTaskResource() {
  return apiResource('housekeeping.complete')
}

/** Supervisor sign-off on a cleaned room. */
export function inspectHousekeepingTaskResource() {
  return apiResource('housekeeping.inspect')
}

/** Record DND or a refused service against a task. */
export function setDoNotDisturbResource() {
  return apiResource('housekeeping.set_do_not_disturb')
}

/**
 * Task priorities, mirrored from the DocType select for rendering and sort
 * order only. The server remains authoritative about the value itself.
 */
export const TASK_PRIORITIES = ['Urgent', 'High', 'Normal', 'Low']

/** Rank used to sort the board by priority (most urgent first), then room. */
export function priorityRank(priority) {
  const index = TASK_PRIORITIES.indexOf(priority)
  return index === -1 ? TASK_PRIORITIES.length : index
}

/** Badge theme per task status, so a task reads at a glance across the board. */
export const TASK_STATUS_THEME = {
  Pending: 'gray',
  Assigned: 'blue',
  'In Progress': 'orange',
  'Inspection Pending': 'orange',
  Completed: 'green',
  Cancelled: 'gray',
  'Service Refused': 'gray',
  DND: 'gray',
}

export function taskStatusTheme(status) {
  return TASK_STATUS_THEME[status] || 'gray'
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
