"""Compare numeric evidence by value across common English scientific notations."""

import re


_WORD_SCALES = {
    'thousand': 1e3, 'million': 1e6, 'billion': 1e9, 'trillion': 1e12,
    'kilobase': 1e3, 'kilobases': 1e3, 'megabase': 1e6, 'megabases': 1e6,
    'gigabase': 1e9, 'gigabases': 1e9,
}
_UNIT_SCALES = {'k': 1e3, 'm': 1e6, 'g': 1e9, 't': 1e12}
_SUFFIX_SCALES = {'k': 1e3, 'm': 1e6, 'b': 1e9, 't': 1e12}
_TOKEN = re.compile(
    r'(?<![\w.])(\d[\d,]*(?:\.\d+)?)([-\s]*)'
    r'((?:thousand|million|billion|trillion|kilobases?|megabases?|gigabases?)\b'
    r'|[kMGT][bB]p?\b|[KMBT](?![A-Za-z0-9]))?',
    re.IGNORECASE,
)
_WORD_NUMBERS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
    'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13,
    'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18,
    'nineteen': 19, 'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
    'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90, 'hundred': 100,
}
_TENS = {word: value for word, value in _WORD_NUMBERS.items() if 20 <= value < 100}
_ONES = {word: value for word, value in _WORD_NUMBERS.items() if value < 10}
_WORD_MULTIPLIERS = {**_WORD_SCALES, 'hundred': 100.0}
_WORD_NUMBER = re.compile(
    rf"\b(?:({'|'.join(_TENS)})[-\s]({'|'.join(_ONES)})|({'|'.join(_WORD_NUMBERS)}))"
    rf"(?:[-\s]+({'|'.join(_WORD_MULTIPLIERS)}))?\b",
    re.IGNORECASE,
)
_MIDDLE_DOT = re.compile(r'(?<=\d)(?:\{middle dot\}|·)(?=\d)')
_LATEX_COMMAND = re.compile(r'\\[A-Za-z]+')


def _token_value(digits: str, separator: str, scale: str) -> float | None:
    try:
        value = float(digits.replace(',', ''))
    except ValueError:
        return None
    key = scale.lower()
    if len(key) > 1 and key.endswith(('b', 'bp')):
        return value * _UNIT_SCALES[key[0]]
    # A spaced single letter is a unit ("3 T" MRI), not a count suffix.
    factor = _WORD_SCALES.get(key, 1) if separator else (
        _WORD_SCALES.get(key) or _SUFFIX_SCALES.get(key, 1)
    )
    return value * factor


def values(text: str) -> list[float]:
    """Read digit and word numbers in text order, resolving their scales."""
    text = _LATEX_COMMAND.sub(' ', _MIDDLE_DOT.sub('.', text)).replace('$', ' ')
    found = []
    for match in _TOKEN.finditer(text):
        digits, separator, scale = match.groups()
        value = _token_value(digits, separator, scale or '')
        if value is not None:
            found.append((match.start(), value))
    for match in _WORD_NUMBER.finditer(text):
        tens, ones, single, scale = match.groups()
        value = (_WORD_NUMBERS[single.lower()] if single else
                 _TENS[tens.lower()] + _ONES[ones.lower()])
        found.append((match.start(), float(value * _WORD_MULTIPLIERS.get((scale or '').lower(), 1))))
    return [value for _, value in sorted(found)]


def unsupported(
    text: str, source: str, *, tolerance: float = 0.02, min_value: float = 10,
) -> list[float]:
    """Return distinct unsupported values, excluding small counts and whole years."""
    source_values = values(source)
    unknown = []
    for value in values(text):
        if value < min_value or (1900 <= value <= 2100 and value.is_integer()):
            continue
        if value not in unknown and not any(
            abs(value - other) <= tolerance * max(abs(value), abs(other)) for other in source_values
        ):
            unknown.append(value)
    return unknown
