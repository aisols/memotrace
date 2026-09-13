"""Exact normalized decimals without expanding an attacker-controlled exponent."""

import re
from dataclasses import dataclass
from decimal import MAX_EMAX, MIN_EMIN, Decimal, InvalidOperation, localcontext

NUMBER = re.compile(r"(-?)(0|[1-9][0-9]*)(?:\.([0-9]+))?(?:[eE]([+-]?[0-9]+))?\Z")


@dataclass(frozen=True)
class ExactDecimal:
    """Symbolic significand and decimal order, including enormous JSON exponents.

    The order itself is a Decimal integer: memory scales with the *written*
    exponent, never its value. Comparison uses order and normalized digit strings.
    """

    lexeme: str
    negative: bool
    digits: str
    order: Decimal

    @classmethod
    def parse(cls, token: str) -> "ExactDecimal":
        match = NUMBER.fullmatch(token)
        if match is None:
            raise ValueError("invalid decimal")
        sign, integer, fraction, exponent = match.groups()
        fraction = fraction or ""
        exponent = exponent or "0"
        digits = (integer + fraction).lstrip("0")
        if not digits:
            return cls(token, False, "", Decimal(0))
        with localcontext() as context:
            context.prec = max(len(exponent) + 20, 32)
            context.Emax, context.Emin = MAX_EMAX, MIN_EMIN
            order = Decimal(exponent) + (len(digits) - len(fraction) - 1)
        return cls(token, bool(sign), digits.rstrip("0"), order)

    def in_unit_interval(self) -> bool:
        return not self.negative and (
            not self.digits or self.order < 0 or (self.order == 0 and self.digits == "1")
        )

    def less_than(self, other: "ExactDecimal") -> bool:
        # Called only after both endpoints have been validated in [0,1].
        if not self.digits:
            return bool(other.digits)
        if not other.digits:
            return False
        return (self.order, self.digits) < (other.order, other.digits)

    def pixel(self, size: int, *, ceil: bool) -> int:
        if not 1 <= size <= 16384 or not self.in_unit_interval():
            raise ValueError("invalid pixel coordinate")
        if not self.digits:
            return 0
        # Any such positive value times the largest supported dimension is <1.
        if self.order < -5:
            return int(ceil)
        # Multiply the written significand by the small image dimension exactly.
        # Decimal precision is tied to input digits, not the possibly huge exponent.
        with localcontext() as context:
            context.prec = len(self.digits) + 6
            context.Emax, context.Emin = MAX_EMAX, MIN_EMIN
            product = Decimal(self.digits) * size
        product_digits = "".join(str(digit) for digit in product.as_tuple().digits)
        scale = int(self.order) - len(self.digits) + 1
        split = len(product_digits) + scale
        if split <= 0:
            return int(ceil)
        if split >= len(product_digits):
            return int(int(product_digits) * 10 ** (split - len(product_digits)))
        whole = int(product_digits[:split])
        remainder = any(digit != "0" for digit in product_digits[split:])
        return whole + int(ceil and remainder)


def parse_decimal(token: str) -> Decimal | ExactDecimal:
    """Normal JSON decimals use Decimal; exponent-overflow remains symbolic/exact."""
    try:
        return Decimal(token)
    except InvalidOperation:
        return ExactDecimal.parse(token)


def coordinate(value: int | float | Decimal | ExactDecimal) -> ExactDecimal:
    return value if isinstance(value, ExactDecimal) else ExactDecimal.parse(str(value))
