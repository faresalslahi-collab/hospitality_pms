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
 * Drop parameters the caller did not actually supply.
 *
 * frappe-ui serialises GET parameters with `URLSearchParams.append`, which
 * stringifies whatever it is given: `{ query: undefined }` leaves the browser
 * as `?query=undefined`, and the server then searches for the literal text
 * "undefined". Omitting the key is the only way to say "not supplied" over a
 * query string, so it is done once here rather than at every call site.
 */
export function omitEmptyParams(params) {
  if (!params || typeof params !== 'object' || Array.isArray(params)) return params

  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null),
  )
}

/**
 * A resource bound to a whitelisted Hospitality PMS method.
 *
 * @param {string} method  short method path, e.g. `rooms.get_room_rack`
 * @param {object} options passed through to frappe-ui's createResource
 */
export function apiResource(method, options = {}) {
  const { makeParams, ...rest } = options

  return createResource({
    url: apiPath(method),
    ...rest,
    // Runs before every fetch, including the resource's own `params` option.
    makeParams(params) {
      return omitEmptyParams(makeParams ? makeParams.call(this, params) : params)
    },
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
