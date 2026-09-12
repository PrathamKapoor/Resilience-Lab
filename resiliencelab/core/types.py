"""Custom pydantic types for experiment configuration."""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BeforeValidator


def _parse_duration(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("duration cannot be a boolean")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().lower()
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|us|s|m|h)?", text)
        if not match:
            raise ValueError(f"invalid duration string: {value!r}")
        number = float(match.group(1))
        unit = match.group(2) or "s"
        factors = {"ms": 0.001, "us": 0.000001, "s": 1.0, "m": 60.0, "h": 3600.0}
        return number * factors[unit]
    raise ValueError(f"invalid duration value: {value!r}")


Duration = Annotated[float, BeforeValidator(_parse_duration)]
