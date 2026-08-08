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
