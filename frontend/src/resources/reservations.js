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
