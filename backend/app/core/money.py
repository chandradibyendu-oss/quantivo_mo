from decimal import Decimal


def money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(Decimal(value).quantize(Decimal("0.01")), "f")
