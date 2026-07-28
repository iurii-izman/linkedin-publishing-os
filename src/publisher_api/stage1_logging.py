from __future__ import annotations

import json
import logging
from typing import Any

LOGGER = logging.getLogger("publisher_api.stage1")


def safe_log(event: str, **fields: Any) -> None:
    """Emit one JSON object containing only caller-selected safe fields."""
    payload = {"event": event, **fields}
    LOGGER.info(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
    )
