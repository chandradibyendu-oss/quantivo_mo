import re

from app.core.errors import AppError

_E164 = re.compile(r"^\+91[6-9]\d{9}$")


def normalize_indian_mobile(raw: str) -> str:
    compact = re.sub(r"[\s\-()]", "", raw.strip())
    if compact.startswith("+"):
        candidate = compact
    elif compact.startswith("91") and len(compact) == 12:
        candidate = f"+{compact}"
    elif len(compact) == 10:
        candidate = f"+91{compact}"
    else:
        candidate = compact
    if not _E164.fullmatch(candidate):
        raise AppError(422, "invalid_phone", "Enter a valid Indian mobile number.")
    return candidate
