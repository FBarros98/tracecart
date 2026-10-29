import re

_CPF_FORMAT = re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$")


def _check_digit(digits: str) -> str:
    weight = len(digits) + 1
    total = sum(int(digit) * (weight - index) for index, digit in enumerate(digits))
    remainder = (total * 10) % 11
    return "0" if remainder == 10 else str(remainder)


def normalize_cpf(value: str) -> str:
    value = value.strip()
    if not _CPF_FORMAT.fullmatch(value):
        raise ValueError("CPF must be formatted as 00000000000 or 000.000.000-00")
    digits = re.sub(r"\D", "", value)
    if digits == digits[0] * 11:
        raise ValueError("CPF is invalid")
    first = _check_digit(digits[:9])
    second = _check_digit(digits[:9] + first)
    if digits[9:] != first + second:
        raise ValueError("CPF check digits are invalid")
    return digits
