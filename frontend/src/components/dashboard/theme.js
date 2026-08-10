/**
 * Colour for the dashboard's data marks.
 *
 * Kept out of the components so the same room state is the same colour in the
 * status board, its legend and anywhere else it is drawn — a room that is amber
 * on the board and orange in the legend is a room the desk has to think about
 * twice.
 *
 * Every value below was chosen against a white card surface and checked, not
 * eyeballed:
 *
 *   - the categorical slots clear the colour-vision-deficiency separation and
 *     normal-vision floors as an ordered set (worst adjacent pair ΔE 9.1 under
 *     protanopia, 22.9 with normal vision);
 *   - every room chip carries text on its own fill at 4.5:1 or better, so the
 *     room number stays readable at rack density;
 *   - five saturated hues cannot be told apart by hue alone in every direction,
 *     so the room states do not try to. Occupied and Reserved share the blue
 *     hue and separate by lightness (solid against tint); the two states nobody
 *     may sell — Out of Order and Out of Service — additionally carry a slash
 *     glyph, and every chip is individually named for assistive technology.
 *     Colour is never the only channel.
 */

/** Chart ink, in the order slots are assigned. Never cycled, never generated. */
export const SERIES_COLORS = ['#2A78D6', '#EB6834', '#1BAF7A', '#EDA100', '#8A7BD8', '#7C7C7C']

/** One hue for a magnitude, and the track it is drawn against. */
export const PROGRESS_COLOR = '#2A78D6'
export const TRACK_COLOR = '#E7ECF3'

/**
 * Room chip appearance per state.
 *
 * `solid` states are sold or unsellable and read loudest; `tint` states are
 * held or parked and deliberately recede. `glyph` marks the two states a room
 * cannot be given to a guest from, whatever its colour.
 */
export const ROOM_STATE_STYLE = {
  occupied: { fill: '#1F6AC2', text: '#FFFFFF', ring: 'transparent', dot: '#1F6AC2' },
  reserved: { fill: '#DCEAF9', text: '#16559C', ring: '#9EC5F4', dot: '#7FB2EE' },
  vacant_clean: { fill: '#0F7D59', text: '#FFFFFF', ring: 'transparent', dot: '#0F7D59' },
  vacant_dirty: { fill: '#D98A04', text: '#171717', ring: 'transparent', dot: '#D98A04' },
  out_of_order: { fill: '#B02020', text: '#FFFFFF', ring: 'transparent', dot: '#B02020', glyph: 'slash' },
  out_of_service: { fill: '#EDEDED', text: '#525252', ring: '#D6D6D6', dot: '#9A9A9A', glyph: 'slash' },
  other: { fill: '#F3F3F3', text: '#525252', ring: '#E2E2E2', dot: '#C7C7C7' },
}

/**
 * Which chip a room gets, from the four independent status dimensions.
 *
 * Ordered by what stops the desk first: a room that is out of order is out of
 * order whatever its housekeeping says, and an occupied room is occupied even
 * if it is also dirty. This mirrors the order `_blocking_reason` uses on the
 * server, so the board and the room detail dialog never disagree about why a
 * room cannot be sold.
 */
export function roomStateKey(room) {
  if (!room) return 'other'

  const maintenance = room.maintenance_status
  if (maintenance === 'Out of Order') return 'out_of_order'
  if (maintenance === 'Out of Service' || maintenance === 'Under Maintenance') return 'out_of_service'

  if (!room.is_active) return 'out_of_service'

  const occupancy = room.occupancy_status
  if (occupancy === 'Occupied' || occupancy === 'Due Out' || occupancy === 'House Use') return 'occupied'
  if (occupancy === 'Reserved' || occupancy === 'Due In') return 'reserved'

  const housekeeping = room.housekeeping_status
  if (housekeeping === 'Clean' || housekeeping === 'Inspected') return 'vacant_clean'

  return 'vacant_dirty'
}

/** Legend order: occupancy first, then housekeeping, then what is unsellable. */
export const ROOM_STATE_LEGEND = [
  { key: 'occupied', labelKey: 'page.dashboard.board.occupied' },
  { key: 'vacant_clean', labelKey: 'page.dashboard.board.vacant_clean' },
  { key: 'vacant_dirty', labelKey: 'page.dashboard.board.vacant_dirty' },
  { key: 'reserved', labelKey: 'page.dashboard.board.reserved' },
  { key: 'out_of_order', labelKey: 'page.dashboard.board.out_of_order' },
  { key: 'out_of_service', labelKey: 'page.dashboard.board.out_of_service' },
]
