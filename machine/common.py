from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path


class MachineError(ValueError):
    """An actionable validation or governance failure."""


def require(condition, message):
    if not condition:
        raise MachineError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def number(value, name, minimum=None, maximum=None):
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), f"{name} must be a finite number")
    require(minimum is None or value >= minimum, f"{name} must be >= {minimum}")
    require(maximum is None or value <= maximum, f"{name} must be <= {maximum}")
    return value


def leaves(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out.update(leaves(v, f"{prefix}.{k}" if prefix else k))
        return out
    return {prefix: value}


def differences(a, b):
    a, b = leaves(a), leaves(b)
    return [k for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k) or (k in a) != (k in b)]


def source_manifest():
    root = Path(__file__).parent
    return {p.name: file_hash(p) for p in sorted(root.glob("*.py"))}
