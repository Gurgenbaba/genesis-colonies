"""Exact arithmetic helpers for unbounded gameplay integers.

Keep arbitrary-size economy / stock / score values out of IEEE-754. Floats may
still enter as bounded configuration factors; they are converted to decimal
text before touching a gameplay integer.
"""

from __future__ import annotations

from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    localcontext,
)
from typing import Any, Iterable, Tuple


def decimal_value(value: Any, default: str = "0") -> Decimal:
    try:
        out = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        out = Decimal(default)
    return out if out.is_finite() else Decimal(default)


def decimal_text(value: Any, default: str = "0") -> str:
    """Plain finite decimal text suitable for CAST(? AS NUMERIC)."""
    return format(decimal_value(value, default), "f")


def integer_precision(*values: Any, extra: int = 64) -> int:
    digits = 1
    for value in values:
        try:
            digits = max(digits, len(str(abs(int(value)))))
        except (TypeError, ValueError):
            continue
    return max(64, digits + max(16, int(extra)))


def scale_int(
    value: Any,
    *multipliers: Any,
    rounding: str = "floor",
) -> int:
    """Scale an integer by bounded factors without converting the integer to float."""
    base = int(value or 0)
    factors = [decimal_value(mult, "0") for mult in multipliers]
    if not factors:
        return base

    with localcontext() as ctx:
        ctx.prec = integer_precision(base, extra=96)
        result = Decimal(base)
        for factor in factors:
            result *= factor

        if rounding == "half_even":
            return int(result.to_integral_value(rounding=ROUND_HALF_EVEN))
        if rounding != "floor":
            raise ValueError(f"unsupported rounding mode: {rounding}")
        return int(result.to_integral_value(rounding=ROUND_FLOOR))


def sum_products_floor(terms: Iterable[Tuple[Any, Any]]) -> int:
    """floor(sum(integer_value * decimal_factor)) without float integer coercion."""
    pairs = [(int(value or 0), decimal_value(factor)) for value, factor in terms]
    if not pairs:
        return 0
    with localcontext() as ctx:
        ctx.prec = integer_precision(*(value for value, _ in pairs), extra=96)
        total = Decimal(0)
        for value, factor in pairs:
            total += Decimal(value) * factor
        return int(total.to_integral_value(rounding=ROUND_FLOOR))


def decimal_mul_div_floor(value: Any, numerator: Any, denominator: Any) -> int:
    """floor(decimal_value * integer numerator / integer denominator) with guard precision."""
    dec = decimal_value(value)
    num = int(numerator or 0)
    den = int(denominator or 0)
    if den == 0:
        raise ZeroDivisionError("denominator must not be zero")
    digits = max(1, len(dec.as_tuple().digits))
    with localcontext() as ctx:
        ctx.prec = max(96, digits + len(str(abs(num))) + len(str(abs(den))) + 64)
        out = dec * Decimal(num) / Decimal(den)
        return int(out.to_integral_value(rounding=ROUND_FLOOR))

def mul_div_floor(value: Any, numerator: Any, denominator: Any) -> int:
    """Exact floor(value * numerator / denominator) for integer operands."""
    v = int(value or 0)
    n = int(numerator or 0)
    d = int(denominator or 0)
    if d == 0:
        raise ZeroDivisionError("denominator must not be zero")
    return (v * n) // d


def bounded_ratio_float(
    numerator: Any,
    denominator: Any,
    *,
    minimum: Any = "0",
    maximum: Any = "1",
) -> float:
    """Divide huge integers exactly, clamp, then convert the bounded result to float."""
    num = int(numerator or 0)
    den = int(denominator or 0)
    lo = decimal_value(minimum)
    hi = decimal_value(maximum, "1")
    if hi < lo:
        lo, hi = hi, lo
    if den == 0:
        return float(hi if num > 0 else lo)

    with localcontext() as ctx:
        ctx.prec = integer_precision(num, den, extra=96)
        ratio = Decimal(num) / Decimal(den)
        ratio = max(lo, min(hi, ratio))
    return float(ratio)


def scale_ratio_power_int(
    base: Any,
    numerator: Any,
    denominator: Any,
    exponent: Any,
    *multipliers: Any,
    rounding: str = "floor",
    cap: Any | None = None,
) -> int:
    """Scale base * (numerator/denominator)**exponent without huge-int floats.

    With a cap, astronomically large inputs saturate before constructing the
    full Decimal power. The cap/threshold math only uses bounded config values.
    """
    base_int = max(0, int(base or 0))
    num = max(0, int(numerator or 0))
    den = max(1, int(denominator or 1))
    exp = decimal_value(exponent)
    factors = [decimal_value(mult, "0") for mult in multipliers]
    cap_int = max(0, int(cap or 0)) if cap is not None else None

    if base_int <= 0:
        return 0
    if any(factor <= 0 for factor in factors):
        return 0
    if exp < 0:
        raise ValueError("negative ratio exponents are not supported")

    if exp == 0:
        out = scale_int(base_int, *factors, rounding=rounding)
        return min(cap_int, out) if cap_int is not None and cap_int > 0 else out

    factor_product = Decimal("1")
    for factor in factors:
        factor_product *= factor

    if cap_int is not None and cap_int > 0 and factor_product > 0:
        with localcontext() as ctx:
            ctx.prec = 96
            needed = Decimal(cap_int) / (Decimal(base_int) * factor_product)
            if needed <= 1:
                threshold_ratio = Decimal("1")
            else:
                threshold_ratio = ctx.power(needed, Decimal("1") / exp)
            threshold_num = (
                Decimal(den) * threshold_ratio
            ).to_integral_value(rounding=ROUND_FLOOR)
            if num > int(threshold_num):
                return cap_int

    with localcontext() as ctx:
        ctx.prec = integer_precision(base_int, num, den, extra=128)
        ratio = Decimal(num) / Decimal(den)
        result = Decimal(base_int) * ctx.power(ratio, exp)
        result *= factor_product
        if rounding == "half_even":
            out = int(result.to_integral_value(rounding=ROUND_HALF_EVEN))
        elif rounding == "floor":
            out = int(result.to_integral_value(rounding=ROUND_FLOOR))
        else:
            raise ValueError(f"unsupported rounding mode: {rounding}")

    if cap_int is not None and cap_int > 0:
        return min(cap_int, out)
    return out

def sqrt_scaled_int(value: Any, multiplier: Any) -> int:
    """floor(sqrt(value) * multiplier), safe far beyond binary-float range."""
    base = max(0, int(value or 0))
    if base <= 0:
        return 0
    factor = decimal_value(multiplier)
    if factor <= 0:
        return 0

    with localcontext() as ctx:
        ctx.prec = integer_precision(base, extra=96)
        out = Decimal(base).sqrt() * factor
        return int(out.to_integral_value(rounding=ROUND_FLOOR))
