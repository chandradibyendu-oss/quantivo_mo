"""Six-digit TOTP codes. The secret stays in the server environment."""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
from datetime import datetime, timedelta


def totp_code(secret: str, moment: datetime) -> str:
    """Code for the 30-second window. A code about to roll uses the next window."""

    instant = moment
    if instant.second % 30 >= 27:
        instant = instant + timedelta(seconds=5)
    key = _key(secret)
    counter = int(instant.timestamp()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def _key(secret: str) -> bytes:
    cleaned = "".join(secret.split()).upper()
    padding = "=" * ((8 - len(cleaned) % 8) % 8)
    return base64.b32decode(cleaned + padding, casefold=True)
