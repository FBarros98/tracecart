import re

_CARD_FORMAT = re.compile(r"^\d{4}([ -]?)\d{4}\1\d{4}\1\d{1,7}$")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def normalize_card_number(value: str) -> str:
    """Validate a card number (format and Luhn checksum) and return its digits."""
    value = value.strip()
    if not _CARD_FORMAT.fullmatch(value):
        raise ValueError("Card number must have 13 to 19 digits, optionally grouped by spaces or hyphens")
    digits = re.sub(r"\D", "", value)
    if not 13 <= len(digits) <= 19 or not _luhn_valid(digits):
        raise ValueError("Card number is invalid")
    return digits
