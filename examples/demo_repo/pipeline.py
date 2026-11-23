"""Order enrichment pipeline.

This module is intentionally small: it exists so the crashlens examples have a
real repository to blame.  enrich() is the entry point the HTTP layer calls.
"""

from __future__ import annotations

import json
from typing import Any


def decode(raw: str) -> dict[str, Any]:
    """Parse the JSON body a partner sent us."""
    return json.loads(raw)


def pick_sku(document: dict[str, Any]) -> str:
    """Return the sku of the first line item."""
    items = document["items"]
    if not items:
        return ""
    return items[0]["sku"]


def enrich(raw: str) -> dict[str, Any]:
    """Decode and normalise one checkout payload."""
    try:
        document = decode(raw)
        return {"sku": pick_sku(document), "source": "checkout"}
    except ValueError as exc:
        raise RuntimeError("order enrichment failed for checkout") from exc
