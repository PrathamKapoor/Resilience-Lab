"""Provenance capture and cryptographic artifact hashing."""

from __future__ import annotations

import hashlib
import json
import platform
import sys

from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.metrics.collector import Record


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_bytes(data: bytes) -> str:
    return _sha256(data)


def hash_text(text: str) -> str:
    return _sha256(text.encode("utf-8"))


def hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_config(experiment: ExperimentSpec) -> str:
    return json.dumps(experiment.model_dump(mode="json"), sort_keys=True)


def hash_config(experiment: ExperimentSpec) -> str:
    return hash_text(canonical_config(experiment))


def hash_records(records: list[Record]) -> str:
    return hash_text(json.dumps(records, sort_keys=True, default=str))


def capture_environment() -> dict[str, str]:
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
