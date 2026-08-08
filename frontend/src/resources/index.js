/**
 * Named wrappers around the Frappe resource layer.
 *
 * Pages and components never call `createResource` with a raw URL; they import
 * a wrapper from `src/resources/*` so an endpoint change is a one-line edit
 * (Frontend Standards section 5).
 */
import { createListResource, createResource } from 'frappe-ui'

const API_NAMESPACE = 'hospitality_pms.api'

/** Resolve a short name such as `session.get_session_context` to a full path. */
export function apiPath(method) {
  return method.includes('.') && method.startsWith(API_NAMESPACE) ? method : `${API_NAMESPACE}.${method}`
}

/**
 * A resource bound to a whitelisted Hospitality PMS method.
 *
 * @param {string} method  short method path, e.g. `rooms.get_room_rack`
 * @param {object} options passed through to frappe-ui's createResource
 */
export function apiResource(method, options = {}) {
  return createResource({
    url: apiPath(method),
    ...options,
  })
}

/**
 * A paginated list resource.
 *
 * Always pass the fields the screen actually renders: unbounded selects on
 * operational tables are the first thing to hurt at 500 rooms (SAD section 13).
 */
export function listResource(doctype, options = {}) {
  return createListResource({
    doctype,
    pageLength: 20,
    auto: false,
    ...options,
  })
}
