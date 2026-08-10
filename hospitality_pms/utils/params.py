"""Normalisation for values arriving from an HTTP query string.

A GET request has no notion of "absent": every parameter reaches the server as
a string. A frontend that serialises a JavaScript `undefined` into the query
string sends the literal text ``undefined``, and a Python endpoint that treats
it as a real value silently searches for it. That is a whole class of bug
(HPMS: guest search returning nothing on first load), so the coercion lives in
one place rather than being re-invented per endpoint.
"""

#: Placeholder texts that mean "no value was supplied", not a value to match.
EMPTY_TOKENS = frozenset({"undefined", "null", "none", "nan"})


def clean_str(value) -> str | None:
	"""A trimmed string, or ``None`` when the caller supplied nothing real.

	Returns ``None`` for an empty string and for the JavaScript/JSON
	placeholders that survive query-string serialisation.
	"""
	if value is None:
		return None

	text = str(value).strip()

	if not text or text.lower() in EMPTY_TOKENS:
		return None

	return text


def clean_int(value, default: int | None = None) -> int | None:
	"""An int, or `default` when the caller supplied nothing usable."""
	text = clean_str(value)

	if text is None:
		return default

	try:
		return int(float(text))
	except (TypeError, ValueError):
		return default


def clean_bool(value, default: bool = False) -> bool:
	"""A boolean from the several shapes a checkbox reaches the server as."""
	text = clean_str(value)

	if text is None:
		return default

	return text.lower() in ("1", "true", "yes", "on")
