from __future__ import annotations

import json
import math
from dataclasses import asdict, is_dataclass
from pathlib import Path


def to_json_ready(value):
    if is_dataclass(value):
        return to_json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_ready(item) for item in value]
    if isinstance(value, float):
        if math.isinf(value):
            return "inf"
        if math.isnan(value):
            return None
    return value


def dump_json_file(path: str | Path, payload) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(to_json_ready(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
