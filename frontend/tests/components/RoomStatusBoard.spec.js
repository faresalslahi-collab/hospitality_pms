/**
 * Room status board.
 *
 * The board's contract is that it agrees with itself and with the rest of the
 * system. Three invariants carry this file:
 *
 *   - the counters along the top and the tiles in the grid come from one pass
 *     over one list, so a room counted as occupied is drawn as occupied and no
 *     room is counted twice or missed;
 *   - a state is resolved by `theme.roomStateKey`, which mirrors the server's
 *     `api/rooms._blocking_reason` precedence. The board invents no precedence
 *     of its own, so a vacant, clean, Stop Sell room is never drawn sellable;
 *   - the grid is generated from whatever floors and rooms the property has.
 *     Nothing here assumes five floors, eight rooms, or numbers in the 100s.
 *
 * The blocked counter is tested on its own because it is the one place the board
 * says something its colours cannot: a blocked room draws exactly like an
 * out-of-service one, deliberately, and folding it into that counter would report
 * held rooms as broken ones.
 */
import { beforeEach, describe, expect, it } from 'vitest'

import { mountOperational, resetStores, stubProperty, stubSession, useArabic } from '../helpers'

const { default: RoomStatusBoard } = await import('@/components/dashboard/RoomStatusBoard.vue')

/** One rack room, shaped as `rooms.get_room_rack` sends it. */
function room(overrides = {}) {
  return {
    name: 'DOHA01-101',
    room_number: '101',
    room_type: 'DLX',
    room_type_name: 'Deluxe',
    floor: 'F1',
    floor_name: 'First',
    floor_level: 1,
    is_active: 1,
    occupancy_status: 'Vacant',
    housekeeping_status: 'Clean',
    maintenance_status: 'Operational',
    inventory_status: 'Available',
    ready: true,
    assignable: true,
    ...overrides,
  }
}

/** The `room_types` block, as one group unless a test needs more. */
function rack(rooms) {
  return [{ name: 'DLX', room_type_name: 'Deluxe', rooms }]
}

function mountBoard(rooms, props = {}) {
  return mountOperational(RoomStatusBoard, {
    props: { roomTypes: rack(rooms), ...props },
  })
}

/** The counter chips along the top, as `{ label: count }`. */
function counters(wrapper) {
  const entries = wrapper.find('header').findAll('span.rounded-lg')

  return Object.fromEntries(
    entries.map((chip) => {
      const text = chip.text().trim()
      const split = text.lastIndexOf(' ')

      return [text.slice(0, split), Number(text.slice(split + 1))]
    }),
  )
}

/** Every room tile in the grid, in document order. */
function tiles(wrapper) {
  return wrapper.findAll('tbody button')
}

/** The floor names down the first column, in the order they are drawn. */
function floorNames(wrapper) {
  return wrapper.findAll('tbody th').map((cell) => cell.text().trim())
}

/** The room positions on one floor row — the slack column is not one. */
function roomCells(row) {
  return row.findAll('[data-room-cell]')
}

beforeEach(() => {
  resetStores()
  stubProperty()
  stubSession(['Front Office Agent'])
})

describe('Room status board summary', () => {
  it('counts every one of the six states, from the rooms it is drawing', async () => {
    const wrapper = await mountBoard([
      room({ name: 'R1', room_number: '101', occupancy_status: 'Occupied' }),
      room({ name: 'R2', room_number: '102', occupancy_status: 'Occupied' }),
      room({ name: 'R3', room_number: '103' }),
      room({ name: 'R4', room_number: '104', housekeeping_status: 'Dirty' }),
      room({ name: 'R5', room_number: '105', occupancy_status: 'Reserved' }),
      room({ name: 'R6', room_number: '106', maintenance_status: 'Out of Order' }),
      room({ name: 'R7', room_number: '107', maintenance_status: 'Out of Service' }),
    ])

    expect(counters(wrapper)).toEqual({
      Occupied: 2,
      'Vacant clean': 1,
      'Vacant dirty': 1,
      Reserved: 1,
      'Out of order': 1,
      'Out of service': 1,
    })
  })

  it('sits against the title, not at the far edge of the card', async () => {
    const wrapper = await mountBoard([room()])
    const titleGroup = wrapper.find('header > div:first-child')

    expect(titleGroup.text()).toContain('Rooms Status Board')
    expect(titleGroup.text()).toContain('Occupied')
  })

  it('shows a state at zero rather than leaving it out', async () => {
    // "Out of order 0" is a sentence about the house. An absent counter is the
    // reader having to notice something that is not there.
    const wrapper = await mountBoard([room()])

    expect(counters(wrapper)['Out of order']).toBe(0)
    expect(Object.keys(counters(wrapper))).toHaveLength(6)
  })

  it('never disagrees with the grid: every tile is counted exactly once', async () => {
    const rooms = [
      room({ name: 'R1', room_number: '101', occupancy_status: 'Occupied' }),
      room({ name: 'R2', room_number: '102', inventory_status: 'Stop Sell' }),
      room({ name: 'R3', room_number: '201', floor: 'F2', floor_name: 'Second', floor_level: 2 }),
      room({ name: 'R4', room_number: '202', floor: 'F2', floor_name: 'Second', floor_level: 2, housekeeping_status: 'Dirty' }),
    ]

    const wrapper = await mountBoard(rooms)
    const counted = Object.values(counters(wrapper)).reduce((sum, count) => sum + count, 0)

    expect(tiles(wrapper)).toHaveLength(rooms.length)
    expect(counted).toBe(rooms.length)
  })

  it('counts a stopped room as blocked, not as out of service', async () => {
    // It draws exactly like an out-of-service room on purpose. It is not one:
    // reporting a held room as broken is a claim about the estate that is false.
    const wrapper = await mountBoard([
      room({ name: 'R1', room_number: '101', inventory_status: 'Stop Sell' }),
      room({ name: 'R2', room_number: '102', maintenance_status: 'Out of Service' }),
    ])

    expect(counters(wrapper)).toMatchObject({ Blocked: 1, 'Out of service': 1 })
  })

  it('keeps the blocked counter out of sight when nothing is blocked', async () => {
    const wrapper = await mountBoard([room()])

    expect(counters(wrapper).Blocked).toBeUndefined()
  })

  it('never reads a vacant, clean, Stop Sell room as sellable', async () => {
    const wrapper = await mountBoard([room({ inventory_status: 'Stop Sell' })])

    expect(counters(wrapper)['Vacant clean']).toBe(0)
    expect(tiles(wrapper)[0].attributes('title')).toContain('Blocked')
  })
})

describe('Room status board grid', () => {
  it('builds its columns from the busiest floor, whatever the property has', async () => {
    const wrapper = await mountBoard([
      room({ name: 'R1', room_number: '101' }),
      room({ name: 'R2', room_number: '102' }),
      room({ name: 'R3', room_number: '103' }),
      room({ name: 'R4', room_number: '201', floor: 'F2', floor_name: 'Second', floor_level: 2 }),
    ])

    // Every floor is laid out on the widest floor's three positions, so room N
    // on one floor sits directly above room N on the next.
    for (const row of wrapper.findAll('tbody tr')) expect(roomCells(row)).toHaveLength(3)
  })

  it('heads the grid with the word alone, and numbers no column', async () => {
    const wrapper = await mountBoard([room({ room_number: '101' }), room({ name: 'R2', room_number: '102' })])
    const head = wrapper.find('thead')

    expect(head.text().trim()).toBe('Floor')
    // The tile says which room it is. A position number above it named nothing.
    expect(head.text()).not.toMatch(/\d/)
  })

  it('packs the rooms against their floor, giving the slack to a trailing cell', async () => {
    const wrapper = await mountBoard([room({ room_number: '101' })])
    const row = wrapper.findAll('tbody tr')[0]

    // One floor heading, one room position, one slack cell — and the slack cell
    // is last, so nothing stretches the tiles across a wide card.
    const cells = row.findAll('td')

    expect(cells).toHaveLength(2)
    expect(cells[1].attributes('data-room-cell')).toBeUndefined()
    expect(cells[1].classes()).toContain('w-full')
  })

  it('leaves a shorter floor short rather than borrowing another floor position', async () => {
    const wrapper = await mountBoard([
      room({ name: 'R1', room_number: '101' }),
      room({ name: 'R2', room_number: '102' }),
      room({ name: 'R3', room_number: '201', floor: 'F2', floor_name: 'Second', floor_level: 2 }),
    ])

    const rows = wrapper.findAll('tbody tr')
    const second = rows.find((row) => row.text().includes('Second'))

    expect(second.findAll('button')).toHaveLength(1)
    expect(roomCells(second)).toHaveLength(2)
    expect(tiles(wrapper)).toHaveLength(3)
  })

  it('runs the floors as a lift would, top of the building first', async () => {
    const wrapper = await mountBoard([
      room({ name: 'R1', room_number: '101', floor: 'F1', floor_name: 'First', floor_level: 1 }),
      room({ name: 'R2', room_number: '501', floor: 'F5', floor_name: 'Fifth', floor_level: 5 }),
      room({ name: 'R3', room_number: '301', floor: 'F3', floor_name: 'Third', floor_level: 3 }),
    ])

    expect(floorNames(wrapper)).toEqual(['Fifth', 'Third', 'First'])
  })

  it('gathers unfloored rooms last rather than dropping them', async () => {
    const wrapper = await mountBoard([
      room({ name: 'R1', room_number: '101' }),
      room({ name: 'R2', room_number: 'A1', floor: null, floor_name: null, floor_level: null }),
    ])

    expect(floorNames(wrapper)).toEqual(['First', 'No floor'])
    expect(tiles(wrapper)).toHaveLength(2)
  })

  it('orders rooms on a floor numerically, so 10 follows 9', async () => {
    const wrapper = await mountBoard([
      room({ name: 'R10', room_number: '10' }),
      room({ name: 'R9', room_number: '9' }),
      room({ name: 'R2', room_number: '2' }),
    ])

    expect(tiles(wrapper).map((tile) => tile.text().trim())).toEqual(['2', '9', '10'])
  })

  it('draws whatever numbering the property uses', async () => {
    // Nothing here parses a room number into a floor. A property numbering its
    // rooms "GF-A" gets its rooms.
    const wrapper = await mountBoard([
      room({ name: 'R1', room_number: 'GF-A', floor: 'GF', floor_name: 'Ground', floor_level: 0 }),
    ])

    expect(tiles(wrapper)[0].text().trim()).toBe('GF-A')
    expect(floorNames(wrapper)).toEqual(['Ground'])
  })

  it('reports an unconfigured property as empty rather than as a broken board', async () => {
    const wrapper = await mountBoard([])

    expect(wrapper.text()).toContain('No rooms have been set up for this property yet.')
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('says it is loading before the rack answers', async () => {
    const wrapper = await mountOperational(RoomStatusBoard, {
      props: { roomTypes: [], loading: true },
    })

    expect(wrapper.text()).toContain('Loading')
  })
})

describe('Room status board interaction', () => {
  it('hands the clicked room back whole, for the dialog that owns it', async () => {
    const target = room({ name: 'DOHA01-102', room_number: '102' })
    const wrapper = await mountBoard([room(), target])

    await tiles(wrapper)[1].trigger('click')

    expect(wrapper.emitted('select')).toHaveLength(1)
    expect(wrapper.emitted('select')[0][0]).toMatchObject({ name: 'DOHA01-102', room_number: '102' })
  })

  it('gives every tile the same fixed width, filled or empty', async () => {
    // The slack cell asks for 100%, and a table column in auto layout yields to
    // it down to its content's minimum — which, with a tile that only asked for
    // `w-full`, was the width of three digits. The tile carries the width now,
    // and the empty positions carry it too, or a short floor would pull the
    // floors above and below it out of step.
    const wrapper = await mountBoard([
      room({ name: 'R1', room_number: '101' }),
      room({ name: 'R2', room_number: '102' }),
      room({ name: 'R3', room_number: '201', floor: 'F2', floor_name: 'Second', floor_level: 2 }),
    ])

    for (const tile of tiles(wrapper)) expect(tile.classes()).toContain('w-[4.5rem]')

    const spacers = wrapper.findAll('[data-room-cell] span[aria-hidden="true"]')

    expect(spacers).toHaveLength(1)
    expect(spacers[0].classes()).toContain('w-[4.5rem]')
  })

  it('keeps every tile one size, focused or not', async () => {
    // An outset focus ring paints four pixels around the box, which reads as the
    // focused room having grown while its neighbours have not. Drawn inside, the
    // indicator is just as visible and the row stays even.
    const wrapper = await mountBoard([room()])
    const classes = tiles(wrapper)[0].classes().join(' ')

    expect(classes).toContain('focus-visible:shadow-[inset_0_0_0_2px_#ffffff,inset_0_0_0_4px_#171717]')
    expect(classes).not.toMatch(/focus-visible:shadow-\[0_0_0/)
    // Nothing in the hover state changes the footprint either.
    expect(classes).not.toMatch(/hover:(scale|h-|w-|p-)/)
  })

  it('names every tile for a reader who cannot see its colour', async () => {
    const wrapper = await mountBoard([room({ occupancy_status: 'Occupied' })])

    expect(tiles(wrapper)[0].attributes('aria-label')).toBe('101 · Occupied')
  })
})

describe('Room status board in Arabic', () => {
  beforeEach(() => useArabic())

  it('translates the floor heading and the counters', async () => {
    const wrapper = await mountBoard([room({ occupancy_status: 'Occupied' })])

    expect(wrapper.find('thead').text()).toContain('الطابق')
    expect(wrapper.find('header').text()).toContain('مشغولة')
  })

  it('expresses the pinned floor column and the tile glyph logically', async () => {
    // `start-*` and `end-*`, never `left-*`/`right-*`: the floor column pins to
    // the reading edge and the unsellable glyph sits in the reading-far corner,
    // both of which swap under RTL.
    const wrapper = await mountBoard([room({ inventory_status: 'Stop Sell' })])
    const html = wrapper.html()

    expect(html).toContain('start-0')
    expect(html).toContain('end-1')
    expect(html).not.toMatch(/\bleft-0\b|\bright-1\b/)
  })
})
