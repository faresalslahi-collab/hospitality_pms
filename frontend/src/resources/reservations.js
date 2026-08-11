import { apiResource } from '@/resources'

export function reservationListResource() {
  return apiResource('reservations.list_reservations', { method: 'GET' })
}

export function reservationResource() {
  return apiResource('reservations.get_reservation', { method: 'GET' })
}

export function quoteResource() {
  return apiResource('reservations.quote', { method: 'GET' })
}

export function createReservationResource() {
  return apiResource('reservations.create_reservation')
}

export function confirmReservationResource() {
  return apiResource('reservations.confirm')
}

export function guaranteeReservationResource() {
  return apiResource('reservations.guarantee')
}

export function cancelReservationResource() {
  return apiResource('reservations.cancel')
}

export function noShowResource() {
  return apiResource('reservations.mark_no_show')
}

export function assignRoomResource() {
  return apiResource('reservations.assign_room')
}

export function arrivalsResource() {
  return apiResource('reservations.arrivals', { method: 'GET' })
}

export function departuresResource() {
  return apiResource('reservations.departures', { method: 'GET' })
}

export function calendarResource() {
  return apiResource('reservations.calendar', { method: 'GET' })
}

/**
 * Reservation statuses and their badge themes.
 *
 * Mirrors the server's state machine for display only. Which transitions are
 * legal comes back from the server as `allowed_transitions` — the frontend
 * never decides that.
 */
export const RESERVATION_STATUS_THEME = {
  Draft: 'gray',
  Tentative: 'orange',
  Confirmed: 'blue',
  Guaranteed: 'green',
  Waitlisted: 'orange',
  'Checked In': 'green',
  'Checked Out': 'gray',
  Closed: 'gray',
  Cancelled: 'red',
  'No Show': 'red',
}

export function reservationStatusTheme(status) {
  return RESERVATION_STATUS_THEME[status] || 'gray'
}

/**
 * Roles the server accepts for recording a no-show.
 *
 * A visibility hint only: `services.reservations.mark_no_show` calls
 * `require_role(NO_SHOW_ROLES)` and enforces this regardless of what the
 * frontend offered.
 *
 * Mirrors `services/reservations.py: NO_SHOW_ROLES` exactly, and that list is
 * deliberately NOT `FRONT_DESK_ROLES`: a no-show is an end-of-day audit
 * judgement, so **Front Office Agent is excluded**. Offering the verb to an
 * agent by reusing the front-desk list would put a control on the board that
 * the server refuses every single time.
 */
export const NO_SHOW_ROLES = [
  'Night Auditor',
  'Front Office Manager',
  'Hotel Manager',
  'General Manager',
  'Hospitality Administrator',
  'System Manager',
]
