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
  // Deliberately the same fill, text and glyph as `out_of_service`: both are
  // "parked, cannot be given to a guest", and the palette above was validated as
  // an ordered set, so a sixth hue would need the same measurement rather than a
  // guess. What a blocked room does not share is the *word* - it is not out of
  // service, and the chip says so through ROOM_STATE_LABEL_KEY below.
  blocked: { fill: '#EDEDED', text: '#525252', ring: '#D6D6D6', dot: '#9A9A9A', glyph: 'slash' },
  other: { fill: '#F3F3F3', text: '#525252', ring: '#E2E2E2', dot: '#C7C7C7' },
}

/**
 * Inventory states that stop a sale.
 *
 * Mirrors `services.rooms.BLOCKING_INVENTORY`. Exported because the room
 * attention queue asks the same question about the same three values, and two
 * copies of a server constant are two chances to fall behind it.
 */
export const BLOCKING_INVENTORY = new Set(['Blocked', 'Not Assignable', 'Stop Sell'])

/**
 * Which chip a room gets, from the four independent status dimensions.
 *
 * Ordered by what stops the desk first, following `_blocking_reason` on the
 * server (`api/rooms`): maintenance, then inventory, then occupancy, then
 * housekeeping — so the board, the legend and the room detail dialog never
 * disagree about why a room cannot be sold. An inactive room is unsellable
 * whatever else it says, and is checked with the maintenance states it reads as.
 *
 * Inventory is the dimension this used to skip, and skipping it was a defect
 * with a price: a vacant, clean, Stop Sell room came out `vacant_clean` — solid
 * green, "Vacant clean" in the legend — for a room the availability service
 * refuses to sell. Blocked, Not Assignable and Stop Sell now read as the parked,
 * slash-marked state they operationally are.
 */
export function roomStateKey(room) {
  if (!room) return 'other'

  const maintenance = room.maintenance_status
  if (maintenance === 'Out of Order') return 'out_of_order'
  if (maintenance === 'Out of Service' || maintenance === 'Under Maintenance') return 'out_of_service'

  if (!room.is_active) return 'out_of_service'

  if (BLOCKING_INVENTORY.has(room.inventory_status)) return 'blocked'

  const occupancy = room.occupancy_status
  if (occupancy === 'Occupied' || occupancy === 'Due Out' || occupancy === 'House Use') return 'occupied'
  if (occupancy === 'Reserved' || occupancy === 'Due In') return 'reserved'

  const housekeeping = room.housekeeping_status
  if (housekeeping === 'Clean' || housekeeping === 'Inspected') return 'vacant_clean'

  return 'vacant_dirty'
}

/**
 * Legend order: occupancy first, then housekeeping, then what is unsellable.
 *
 * A visual key, so it has one row per distinct *appearance*. `blocked` is absent
 * on purpose — it draws exactly like `out_of_service`, and two identical swatches
 * with two different words is a legend that has stopped explaining anything.
 */
export const ROOM_STATE_LEGEND = [
  { key: 'occupied', labelKey: 'page.dashboard.board.occupied' },
  { key: 'vacant_clean', labelKey: 'page.dashboard.board.vacant_clean' },
  { key: 'vacant_dirty', labelKey: 'page.dashboard.board.vacant_dirty' },
  { key: 'reserved', labelKey: 'page.dashboard.board.reserved' },
  { key: 'out_of_order', labelKey: 'page.dashboard.board.out_of_order' },
  { key: 'out_of_service', labelKey: 'page.dashboard.board.out_of_service' },
]

/**
 * The icon each state is summarised with, from the app's own Feather set.
 *
 * Kept beside the colour and the label rather than in the board, for the reason
 * at the top of this file: a state that is amber in the grid and orange in its
 * counter is a state the desk has to think about twice, and the same goes for
 * its glyph. Feather has no bed and no broom, so an occupied room is marked by
 * the person in it and a dirty one by the housekeeping task it becomes — which
 * is also the icon the Open work panel already uses for housekeeping.
 *
 * `blocked` takes the slash its chip already carries, so the counter and the
 * corner glyph on the tile say the same thing.
 */
export const ROOM_STATE_ICON = {
  occupied: 'user',
  vacant_clean: 'check-circle',
  vacant_dirty: 'clipboard',
  reserved: 'calendar',
  out_of_order: 'alert-triangle',
  out_of_service: 'tool',
  blocked: 'slash',
  other: 'help-circle',
}

/**
 * What each state is *called*, which is not the same list as the legend.
 *
 * A room chip names its own state in its tooltip and its accessible label, and
 * that name has to be true per room rather than true per swatch: a Stop Sell room
 * shares the parked appearance of an out-of-service room but is not out of
 * service, and telling the desk it is would be a new inaccuracy introduced by
 * fixing an old one. Colour is never the only channel here, and now neither is
 * the legend.
 */
export const ROOM_STATE_LABEL_KEY = {
  ...Object.fromEntries(ROOM_STATE_LEGEND.map((entry) => [entry.key, entry.labelKey])),
  blocked: 'page.dashboard.blocked',
}
