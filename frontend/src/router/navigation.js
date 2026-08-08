/**
 * Operational navigation.
 *
 * One entry per implemented section, added as its build lands, so the sidebar
 * never shows a link that goes nowhere.
 *
 * `roles` filters what a user sees. This is a usability filter only — the
 * server decides what a user may actually do (Roles Matrix section 2). An
 * entry with no `roles` is visible to every authenticated user.
 *
 * An entry has either `to` (a Vue route) or `href` (an external target such as
 * a Desk workspace), never both.
 */
const ADMIN_ROLES = ['Hospitality Administrator', 'System Manager']

export const navigation = [
  {
    key: 'dashboard',
    labelKey: 'nav.dashboard',
    to: { name: 'Dashboard' },
    icon: 'home',
  },
  {
    key: 'reservations',
    labelKey: 'nav.reservations',
    to: { name: 'Reservations' },
    icon: 'book-open',
  },
  {
    key: 'reservation_new',
    labelKey: 'nav.reservation_new',
    to: { name: 'ReservationNew' },
    icon: 'plus-circle',
    roles: [
      'Front Office Agent',
      'Front Office Manager',
      'Hotel Manager',
      'General Manager',
      'Hospitality Administrator',
      'System Manager',
    ],
  },
  {
    key: 'in_house',
    labelKey: 'nav.in_house',
    to: { name: 'InHouse' },
    icon: 'users',
  },
  {
    key: 'guests',
    labelKey: 'nav.guests',
    to: { name: 'Guests' },
    icon: 'user',
    roles: [
      'Front Office Agent',
      'Front Office Manager',
      'Guest Relations Officer',
      'Hotel Manager',
      'General Manager',
      'Hospitality Administrator',
      'System Manager',
    ],
  },
  {
    key: 'rooms',
    labelKey: 'nav.rooms',
    to: { name: 'RoomRack' },
    icon: 'grid',
  },
  {
    key: 'availability',
    labelKey: 'nav.availability',
    to: { name: 'Availability' },
    icon: 'calendar',
  },
  {
    key: 'guest_services',
    labelKey: 'nav.guest_services',
    to: { name: 'GuestServices' },
    icon: 'life-buoy',
    roles: [
      'Front Office Agent',
      'Front Office Manager',
      'Guest Relations Officer',
      'Hotel Manager',
      'General Manager',
      'Hospitality Administrator',
      'System Manager',
    ],
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
  },
  {
    key: 'setup',
    labelKey: 'nav.setup',
    // Frappe v16 serves Desk at /desk; /app only 301-redirects there.
    href: '/desk/hospitality-pms',
    icon: 'settings',
    roles: ADMIN_ROLES,
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
