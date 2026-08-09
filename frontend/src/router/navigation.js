/**
 * Operational navigation.
 *
 * One entry per implemented section, added as its build lands, so the sidebar
 * never shows a link that goes nowhere.
 *
 * Entries are ordered and grouped to follow the shift, not the data model:
 * the front desk group reads down the page in the order the day happens —
 * dashboard, arrivals, in house, departures. Check-in, folio and checkout are
 * the steps between them and are reached from those boards, because each one
 * needs a reservation or a stay before it means anything.
 *
 * `roles` filters what a user sees. This is a usability filter only — the
 * server decides what a user may actually do (Roles Matrix section 2). An
 * entry with no `roles` is visible to every authenticated user.
 *
 * An entry has either `to` (a Vue route) or `href` (an external target such as
 * a Desk workspace), never both.
 */
const ADMIN_ROLES = ['Hospitality Administrator', 'System Manager']

const GUEST_FACING_ROLES = [
  'Front Office Agent',
  'Front Office Manager',
  'Guest Relations Officer',
  'Hotel Manager',
  'General Manager',
  'Hospitality Administrator',
  'System Manager',
]

const FRONT_DESK_ROLES = [
  'Front Office Agent',
  'Front Office Manager',
  'Hotel Manager',
  'General Manager',
  'Hospitality Administrator',
  'System Manager',
]

/** Group order in the sidebar. An item's `group` must appear here. */
export const NAVIGATION_GROUPS = [
  { key: 'front_desk', labelKey: 'nav.group.front_desk' },
  { key: 'bookings', labelKey: 'nav.group.bookings' },
  { key: 'rooms', labelKey: 'nav.group.rooms' },
  { key: 'guests', labelKey: 'nav.group.guests' },
  { key: 'administration', labelKey: 'nav.group.administration' },
]

export const navigation = [
  {
    key: 'dashboard',
    labelKey: 'nav.dashboard',
    to: { name: 'Dashboard' },
    icon: 'home',
    group: 'front_desk',
  },
  {
    key: 'arrivals',
    labelKey: 'nav.arrivals',
    to: { name: 'Arrivals' },
    icon: 'log-in',
    group: 'front_desk',
  },
  {
    key: 'in_house',
    labelKey: 'nav.in_house',
    to: { name: 'InHouse' },
    icon: 'users',
    group: 'front_desk',
  },
  {
    key: 'departures',
    labelKey: 'nav.departures',
    to: { name: 'Departures' },
    icon: 'log-out',
    group: 'front_desk',
  },
  {
    key: 'reservations',
    labelKey: 'nav.reservations',
    to: { name: 'Reservations' },
    icon: 'book-open',
    group: 'bookings',
  },
  {
    key: 'reservation_new',
    labelKey: 'nav.reservation_new',
    to: { name: 'ReservationNew' },
    icon: 'plus-circle',
    roles: FRONT_DESK_ROLES,
    group: 'bookings',
  },
  {
    key: 'calendar',
    labelKey: 'nav.calendar',
    to: { name: 'Calendar' },
    icon: 'calendar',
    group: 'bookings',
  },
  {
    key: 'availability',
    labelKey: 'nav.availability',
    to: { name: 'Availability' },
    icon: 'search',
    group: 'bookings',
  },
  {
    key: 'guests',
    labelKey: 'nav.guests',
    to: { name: 'Guests' },
    icon: 'user',
    roles: GUEST_FACING_ROLES,
    group: 'guests',
  },
  {
    key: 'rooms',
    labelKey: 'nav.rooms',
    to: { name: 'RoomRack' },
    icon: 'grid',
    group: 'rooms',
  },
  {
    key: 'guest_services',
    labelKey: 'nav.guest_services',
    to: { name: 'GuestServices' },
    icon: 'life-buoy',
    roles: GUEST_FACING_ROLES,
    group: 'guests',
  },
  {
    key: 'night_audit',
    labelKey: 'nav.night_audit',
    to: { name: 'NightAudit' },
    icon: 'moon',
    roles: [
      'Night Auditor',
      'Finance Manager',
      'Hotel Manager',
      'General Manager',
      'Hospitality Administrator',
      'System Manager',
    ],
    group: 'administration',
  },
  {
    key: 'housekeeping',
    labelKey: 'nav.housekeeping',
    to: { name: 'Housekeeping' },
    icon: 'clipboard',
    roles: [
      'Room Attendant',
      'Housekeeping Supervisor',
      'Housekeeping Manager',
      'Front Office Manager',
      'Hotel Manager',
      'General Manager',
      'Hospitality Administrator',
      'System Manager',
    ],
    group: 'rooms',
  },
  {
    key: 'maintenance',
    labelKey: 'nav.maintenance',
    to: { name: 'Maintenance' },
    icon: 'tool',
    roles: [
      'Maintenance Technician',
      'Maintenance Manager',
      'Hotel Manager',
      'General Manager',
      'Hospitality Administrator',
      'System Manager',
    ],
    group: 'rooms',
  },
  {
    key: 'setup',
    labelKey: 'nav.setup',
    // Frappe v16 serves Desk at /desk; /app only 301-redirects there.
    href: '/desk/hospitality-pms',
    icon: 'settings',
    roles: ADMIN_ROLES,
    group: 'administration',
    // Configuration lives in Desk by design (Frontend Standards section 9);
    // this is a signpost, not a duplicated workflow.
    external: true,
  },
]

/** Sections the given session may see. */
export function visibleNavigation(session) {
  return navigation.filter((item) => {
    if (item.external && !session.state.hasDeskAccess) return false
    if (!item.roles?.length) return true

    return session.hasRole(item.roles)
  })
}

/**
 * The same sections, arranged into groups for the sidebar.
 *
 * A group with nothing left in it after the role filter is dropped rather than
 * rendered as an empty heading — a housekeeper should not be shown a "Front
 * desk" label with no links under it.
 */
export function visibleNavigationGroups(session) {
  const items = visibleNavigation(session)

  return NAVIGATION_GROUPS.map((group) => ({
    ...group,
    items: items.filter((item) => (item.group || 'front_desk') === group.key),
  })).filter((group) => group.items.length)
}
