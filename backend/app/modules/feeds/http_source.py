"""GET a feed URL. The secret, when one is named, stays in the request header."""

import json
from decimal import Decimal
from urllib.request import Request, urlopen

_TIMEOUT_SECONDS = 20


def fetch_json(url: str, headers: dict) -> dict:
    request = Request(
        url,
        headers={**headers, "Accept": "application/json", "User-Agent": "Quantivo/1.0"},
        method="GET",
    )
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        body = response.read()
    payload = json.loads(body.decode("utf-8"), parse_float=Decimal)
    if not isinstance(payload, dict):
        raise ValueError("Feed response must be an object.")
    return payload
