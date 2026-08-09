/**
 * Kitchen, room service and minibar resources.
 *
 * The order board is read-only. Pricing and the folio charge are decided by
 * the server: `create_order` prices every line from the menu record whatever
 * the caller sends, and `deliver_order` posts the folio charge once under an
 * idempotency key. Nothing here recomputes either (HPMS-DEC-088).
 */
import { apiResource } from '@/resources'

/** Orders the kitchen still has to cook, oldest first. */
export function orderBoardResource() {
  return apiResource('kitchen.board', { method: 'GET' })
}

/** Menu items available to order. */
export function menuItemsResource() {
  return apiResource('kitchen.list_menu_items', { method: 'GET' })
}

/** One order with its priced lines. */
export function orderResource() {
  return apiResource('kitchen.get_order', { method: 'GET' })
}

/** Place an order against an in-house stay. The server prices it. */
export function createOrderResource() {
  return apiResource('kitchen.create_order')
}

/** Move an order through preparation. */
export function setOrderStatusResource() {
  return apiResource('kitchen.set_order_status')
}

/** Deliver, and charge the folio exactly once. */
export function deliverOrderResource() {
  return apiResource('kitchen.deliver_order')
}

/**
 * Order statuses in the order the kitchen works them.
 *
 * Delivered is deliberately absent from the "next step" list: delivering
 * charges the guest, so it is its own confirmed action rather than one more
 * value in a dropdown.
 */
export const ORDER_STATUSES = ['Placed', 'Preparing', 'Ready', 'Delivered', 'Cancelled']

export const OPEN_ORDER_STATUSES = ['Placed', 'Preparing', 'Ready']

/** What a Placed order can become without going through delivery. */
export const NEXT_STATUS = {
  Placed: ['Preparing', 'Cancelled'],
  Preparing: ['Ready', 'Cancelled'],
  Ready: ['Preparing'],
}

export const ORDER_STATUS_THEME = {
  Placed: 'orange',
  Preparing: 'blue',
  Ready: 'green',
  Delivered: 'gray',
  Cancelled: 'red',
}

export function orderStatusTheme(status) {
  return ORDER_STATUS_THEME[status] || 'gray'
}

export const ORDER_TYPES = ['Room Service', 'Minibar', 'Restaurant']

/**
 * Roles the server accepts for delivering an order, which is the step that
 * posts money to the folio. Mirrored only to decide whether to offer the
 * control; the server re-checks it.
 */
export const KITCHEN_ROLES = [
  'Kitchen User',
  'Kitchen Manager',
  'Food and Beverage Manager',
  'Front Office Agent',
  'Front Office Manager',
  'Hotel Manager',
  'General Manager',
  'Hospitality Administrator',
  'System Manager',
]
