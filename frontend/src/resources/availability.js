import { apiResource } from '@/resources'

/** Availability search across room types for a date range. */
export function availabilitySearchResource() {
  return apiResource('availability.search', { method: 'GET' })
}

/** Whether one specific request can be sold. */
export function availabilityCheckResource() {
  return apiResource('availability.check', { method: 'GET' })
}

/** Specific rooms assignable for a whole stay. */
export function assignableRoomsResource() {
  return apiResource('availability.assignable_rooms', { method: 'GET' })
}
