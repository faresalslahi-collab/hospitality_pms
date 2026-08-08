import { apiResource } from '@/resources'

/** Current state of every room in a property, grouped by room type. */
export function roomRackResource() {
  return apiResource('rooms.get_room_rack', { method: 'GET' })
}

/** One room with its recent status history. */
export function roomResource() {
  return apiResource('rooms.get_room', { method: 'GET' })
}

/** Move one status dimension. The server decides whether it is allowed. */
export function setRoomStatusResource() {
  return apiResource('rooms.set_room_status')
}

/**
 * Status dimensions and their values, mirrored from SAS section 3.2.
 *
 * Kept in one place so badges, filters and dropdowns cannot drift apart
 * (Frontend Standards section 2). The server remains authoritative about which
 * transitions are legal — this list is for rendering, not for deciding.
 */
export const ROOM_DIMENSIONS = {
  Occupancy: ['Vacant', 'Reserved', 'Occupied', 'Due In', 'Due Out', 'House Use'],
  Housekeeping: [
    'Clean',
    'Dirty',
    'In Progress',
    'Inspection Pending',
    'Inspected',
    'DND',
    'Service Refused',
  ],
  Maintenance: ['Operational', 'Required', 'Under Maintenance', 'Out of Service', 'Out of Order'],
  Inventory: ['Available', 'Blocked', 'Not Assignable', 'Stop Sell'],
}

/** Badge theme per status, so a room reads at a glance across every screen. */
export const STATUS_THEME = {
  // Occupancy
  Vacant: 'green',
  Reserved: 'blue',
  Occupied: 'orange',
  'Due In': 'blue',
  'Due Out': 'orange',
  'House Use': 'gray',
  // Housekeeping
  Clean: 'green',
  Inspected: 'green',
  Dirty: 'red',
  'In Progress': 'blue',
  'Inspection Pending': 'orange',
  DND: 'gray',
  'Service Refused': 'gray',
  // Maintenance
  Operational: 'green',
  Required: 'orange',
  'Under Maintenance': 'orange',
  'Out of Service': 'red',
  'Out of Order': 'red',
  // Inventory
  Available: 'green',
  Blocked: 'red',
  'Not Assignable': 'red',
  'Stop Sell': 'orange',
}

export function statusTheme(status) {
  return STATUS_THEME[status] || 'gray'
}
