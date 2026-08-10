"""The fixed cast of the demo hotel.

Everything here is invented. The names are constructed for a demo and belong to
nobody; the phone numbers sit in documentation ranges; the e-mail addresses are
on ``example.com``, which exists precisely so that nothing sent to them can
reach a real person.

The lists are ordered and the seed indexes into them, so the same run twice
produces the same hotel — a demo whose room 305 is a different guest every time
is a demo nobody can talk about.
"""

#: Room types, laid out as a small city hotel actually is: a cheap floor, two
#: mid floors, and the executive product upstairs.
ROOM_TYPES = [
	{
		"code": "STD",
		"name": "Standard King",
		"base_occupancy": 2,
		"max_occupancy": 2,
		"max_adults": 2,
		"max_children": 1,
		"rate": 380.0,
		"order": 10,
	},
	{
		"code": "DLX",
		"name": "Deluxe King",
		"base_occupancy": 2,
		"max_occupancy": 3,
		"max_adults": 2,
		"max_children": 2,
		"rate": 500.0,
		"order": 20,
	},
	{
		"code": "DLXT",
		"name": "Deluxe Twin",
		"base_occupancy": 2,
		"max_occupancy": 4,
		"max_adults": 3,
		"max_children": 2,
		"rate": 520.0,
		"order": 30,
	},
	{
		"code": "EXK",
		"name": "Executive King",
		"base_occupancy": 2,
		"max_occupancy": 3,
		"max_adults": 3,
		"max_children": 2,
		"rate": 720.0,
		"order": 40,
	},
	{
		"code": "FAM",
		"name": "Family Suite",
		"base_occupancy": 4,
		"max_occupancy": 6,
		"max_adults": 4,
		"max_children": 3,
		"rate": 950.0,
		"order": 50,
	},
]

#: The building the demo rooms hang off. `Hotel Room.building` is a Link, so
#: this has to exist as a record before a room can name it.
BUILDING = {"code": "Main Tower", "name": "Main Tower"}

#: 40 rooms over five floors.
#:
#: `Hotel Room.floor` is a Link to Floor, and both the room rack and the
#: dashboard's status board group on the stored link value — which is the
#: Floor's own `floor_code`, because that is what Floor is named by. The codes
#: are therefore written the way a lift panel reads rather than as an internal
#: abbreviation: a floor code is the property's to choose, and choosing one
#: that displays correctly is cheaper than teaching three screens to resolve
#: the link.
FLOORS = [
	{"floor": "1st Floor", "level": 1, "zone": "Zone 1", "numbers": range(101, 109)},
	{"floor": "2nd Floor", "level": 2, "zone": "Zone 2", "numbers": range(201, 209)},
	{"floor": "3rd Floor", "level": 3, "zone": "Zone 3", "numbers": range(301, 309)},
	{"floor": "4th Floor", "level": 4, "zone": "Zone 4", "numbers": range(401, 409)},
	{"floor": "5th Floor", "level": 5, "zone": "Zone 5", "numbers": range(501, 509)},
]

#: Which type each room number is. Rooms 101-104 already exist on the local
#: site as Deluxe King and keep that type, so the first floor is deliberately
#: mixed — which is also how a real refurbished floor ends up.
ROOM_TYPE_BY_NUMBER = {
	**{n: "DLX" for n in range(101, 105)},
	**{n: "STD" for n in range(105, 109)},
	**{n: "STD" for n in range(201, 209)},
	**{n: "DLXT" for n in range(301, 309)},
	**{n: "EXK" for n in range(401, 409)},
	**{n: "EXK" for n in range(501, 505)},
	**{n: "FAM" for n in range(505, 509)},
}

VIEW_BY_FLOOR = {
	"1st Floor": "City",
	"2nd Floor": "City",
	"3rd Floor": "Courtyard",
	"4th Floor": "Sea",
	"5th Floor": "Sea",
}

#: Invented guests. `kind` drives the reservation type and the booking source
#: the seed gives their stay, so the mix on the dashboard is a consequence of
#: who is in the hotel rather than a number typed into a chart.
GUESTS = [
	# first, last, kind, nationality, language, vip
	("Ahmed", "Al-Kuwari", "individual", "Qatar", "ar", "Repeat Guest"),
	("Sara", "Hassan", "individual", "Egypt", "ar", ""),
	("John", "Whitfield", "corporate", "United Kingdom", "en", ""),
	("Khalid", "Al-Saeed", "individual", "Saudi Arabia", "ar", "VIP"),
	("Maria", "Fernandes", "individual", "Portugal", "en", ""),
	("Rajesh", "Menon", "corporate", "India", "en", ""),
	("Fatima", "Noor", "family", "Pakistan", "en", ""),
	("David", "Brown", "individual", "United States", "en", ""),
	("Abdullah", "Al-Marri", "corporate", "Qatar", "ar", "VVIP"),
	("Elena", "Petrova", "individual", "Bulgaria", "en", ""),
	("Yusuf", "Demir", "family", "Turkey", "en", ""),
	("Claire", "Dubois", "individual", "France", "en", ""),
	("Omar", "Al-Balushi", "individual", "Oman", "ar", ""),
	("Hannah", "Lindqvist", "individual", "Sweden", "en", ""),
	("Ibrahim", "Kamara", "individual", "Sierra Leone", "en", ""),
	("Priya", "Raghavan", "corporate", "India", "en", "Repeat Guest"),
	("Marco", "Bellini", "individual", "Italy", "en", ""),
	("Noura", "Al-Thani", "family", "Qatar", "ar", ""),
	("Thomas", "Keller", "corporate", "Germany", "en", ""),
	("Aisha", "Rahman", "individual", "Bangladesh", "en", ""),
	("Peter", "Nowak", "individual", "Poland", "en", ""),
	("Layla", "Haddad", "family", "Lebanon", "ar", ""),
	("Samuel", "Okonkwo", "corporate", "Nigeria", "en", ""),
	("Mei", "Lin", "individual", "China", "en", ""),
	("Hamad", "Al-Dosari", "individual", "Qatar", "ar", "Repeat Guest"),
	("Grace", "Mwangi", "individual", "Kenya", "en", ""),
	("Andres", "Morales", "corporate", "Spain", "en", ""),
	("Zainab", "Farooq", "family", "Pakistan", "en", ""),
	("Lukas", "Meyer", "individual", "Switzerland", "en", ""),
	("Reem", "Al-Ansari", "individual", "United Arab Emirates", "ar", ""),
	("Daniel", "O'Sullivan", "individual", "Ireland", "en", ""),
	("Nadia", "Aziz", "corporate", "Jordan", "ar", ""),
	("Carlos", "Ribeiro", "individual", "Brazil", "en", ""),
	("Amira", "Zaki", "family", "Egypt", "ar", ""),
	("Stefan", "Novak", "individual", "Czech Republic", "en", ""),
	("Joanne", "Baxter", "individual", "Australia", "en", ""),
]

#: Guest kind -> (Guest.guest_type, Reservation.reservation_type).
KIND_TO_TYPES = {
	"individual": ("Individual", "Individual"),
	"corporate": ("Corporate Guest", "Corporate"),
	"family": ("Individual", "Individual"),
}

#: Booking sources, and the reservation type each implies. The dashboard's
#: source mix is counted from `Reservation.booking_source`, which is free text
#: on the DocType, so these are the values the demo hotel actually trades on.
BOOKING_SOURCES = [
	("Direct", "Direct Website"),
	("OTA", "OTA"),
	("Corporate", "Corporate"),
	("Walk-In", "Walk In"),
	("Travel Agent", "Travel Agent"),
]

#: The share each source takes of a run of reservations, as a repeating pattern
#: rather than a random draw, so the donut is the same shape on every reseed.
#: Roughly 40 / 30 / 15 / 10 / 5.
SOURCE_PATTERN = [
	"Direct", "OTA", "Direct", "Corporate", "OTA",
	"Direct", "Walk-In", "OTA", "Direct", "Travel Agent",
	"Direct", "OTA", "Corporate", "Direct", "OTA",
	"Direct", "Walk-In", "Corporate", "Direct", "OTA",
]

#: Ancillary spend posted onto in-house folios. Charge types are the Folio
#: Charge select values; nothing here invents a type the schema does not have.
EXTRAS = [
	("Room Service", "Room service - club sandwich and mineral water", 145.0),
	("Minibar", "Minibar consumption", 78.0),
	("Laundry", "Same-day laundry - 4 pieces", 120.0),
	("Transport", "Airport transfer - sedan", 180.0),
	("Room Service", "Room service - breakfast for two", 220.0),
	("Miscellaneous", "Business centre - printing and courier", 65.0),
	("Minibar", "Minibar - soft drinks", 42.0),
	("Laundry", "Pressing - 2 suits", 90.0),
]

#: Housekeeping work for the day, as task type and priority.
HOUSEKEEPING_PLAN = [
	("Departure Clean", "High"),
	("Departure Clean", "Normal"),
	("Stayover Clean", "Normal"),
	("Stayover Clean", "Normal"),
	("Turndown", "Low"),
	("Linen Change", "Normal"),
	("Deep Clean", "Low"),
	("Minibar Check", "Normal"),
	("Stayover Clean", "Normal"),
	("Departure Clean", "Urgent"),
]

#: Maintenance tickets. The last two take their room out of sale through the
#: maintenance service, which is what makes the room status board show a red
#: and a grey chip without anyone setting those fields by hand.
MAINTENANCE_PLAN = [
	("HVAC", "Normal", "Air conditioning not cooling", "Guest reports the room stays warm overnight; thermostat reads 18 but the air is not cold.", None),
	("Plumbing", "High", "Bathroom washbasin draining slowly", "Water stands in the basin for several minutes after use.", None),
	("IT and Network", "Low", "Television not receiving channels", "Screen shows no signal on all channels; set-top box may need reprovisioning.", None),
	("Electrical", "Normal", "Bedside lamp not working", "Left bedside lamp does not switch on; bulb replaced without effect.", None),
	("Furniture", "Low", "Wardrobe door off its runner", "Sliding wardrobe door jams halfway.", None),
	("Appliance", "Normal", "Minibar refrigerator warm", "Minibar not holding temperature; contents removed pending repair.", None),
	("Safety", "Urgent", "Door lock failing to read keycards", "Guests repeatedly locked out; lock reads cards intermittently.", None),
	("Plumbing", "Urgent", "Water leak from bathroom ceiling", "Active leak from the ceiling void above the bath. Room unusable.", "Out of Order"),
	("Structural", "High", "Balcony door seal damaged", "Wind and dust entering through the balcony door; seal to be replaced.", "Out of Order"),
	("HVAC", "Normal", "Planned fan coil unit service", "Scheduled preventive service of the fan coil unit.", "Out of Service"),
]

#: Guest requests. Category values are the Guest Request select options.
GUEST_REQUEST_PLAN = [
	("Housekeeping", "Normal", "Extra towels and pillows", "Guest asks for two extra bath towels and one extra pillow."),
	("Transport", "High", "Airport transfer for tomorrow 06:00", "Guest requests a sedan to Hamad International for an early flight."),
	("Front Office", "Normal", "Late checkout request", "Guest asks to keep the room until 16:00 on the day of departure."),
	("Housekeeping", "Normal", "Baby cot required", "Family travelling with an infant asks for a cot and bed rail."),
	("Housekeeping", "Low", "Laundry pickup", "Guest has laundry ready for collection from the room."),
	("Front Office", "Low", "Wake-up call at 05:30", "Guest asks for a wake-up call before an early meeting."),
	("Food and Beverage", "Normal", "Room service assistance", "Guest asks about a late-night menu and dietary options."),
	("Concierge", "Normal", "Restaurant reservation for four", "Guest asks for a table at a seafood restaurant for this evening."),
	("IT and Network", "High", "Wi-Fi not connecting on laptop", "Guest cannot join the guest network from a work laptop."),
	("Housekeeping", "Urgent", "Room not made up", "Guest returned to find the room had not been serviced."),
	("Billing", "Normal", "Query on minibar charge", "Guest queries a minibar line they say they did not consume."),
	("Maintenance", "High", "Shower running cold", "Guest reports no hot water in the shower this morning."),
]
