import { apiResource } from '@/resources'

/** The in-house board for a property. */
export function inHouseResource() {
  return apiResource('stays.in_house', { method: 'GET' })
}

/** One stay with its companions, notes and room move history. */
export function stayResource() {
  return apiResource('stays.get_stay', { method: 'GET' })
}

/** Check a reservation room line into a room. */
export function checkInResource() {
  return apiResource('stays.check_in')
}

export function changeRoomResource() {
  return apiResource('stays.change_room')
}

export function extendStayResource() {
  return apiResource('stays.extend_stay')
}

export function shortenStayResource() {
  return apiResource('stays.shorten_stay')
}

export function addStayNoteResource() {
  return apiResource('stays.add_note')
}

/**
 * Note types, mirrored from the Stay Note record.
 *
 * Shift Handover is first because it is what the note field is most used for:
 * the thing the next shift has to know about this guest.
 */
export const STAY_NOTE_TYPES = [
  'Shift Handover',
  'Operational',
  'Guest Request',
  'Complaint',
  'Alert',
]

/** Badge theme per stay status, so a stay reads the same on every screen. */
export const STAY_STATUS_THEME = {
  Expected: 'blue',
  'In House': 'green',
  'Due Out': 'orange',
  'Checked Out': 'gray',
  Closed: 'gray',
}

export function stayStatusTheme(status) {
  return STAY_STATUS_THEME[status] || 'gray'
}

/**
 * Roles the server accepts for changing a stay — moving a room, extending,
 * shortening or noting. Mirrored only to decide whether to offer the controls;
 * the server enforces it regardless (Stay write permission).
 */
export const STAY_OPERATION_ROLES = [
  'Front Office Agent',
  'Front Office Manager',
  'Guest Relations Officer',
  'Hotel Manager',
  'General Manager',
  'Hospitality Administrator',
  'System Manager',
]

/**
 * Roles the server accepts for a Vacant Dirty (unready room) check-in
 * override. Mirrored here only to decide whether to bother showing the
 * override control; the server enforces the role and the reason regardless.
 */
export const READINESS_OVERRIDE_ROLES = [
  'Front Office Manager',
  'Hotel Manager',
  'General Manager',
  'Hospitality Administrator',
  'System Manager',
]
