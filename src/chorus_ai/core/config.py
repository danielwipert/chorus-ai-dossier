from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from chorus_ai.core.errors import ChorusFatalError


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ChorusFatalError("CONFIG_NOT_FOUND", "Config file not found", {"path": str(path)})

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ChorusFatalError("CONFIG_INVALID_JSON", "Config file is not valid JSON", {"path": str(path), "error": str(e)})


def canonicalize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    For Step A we keep this minimal. Later we can enforce a Config schema.
    Canonicalization here means: ensure it's a plain JSON-serializable dict.
    """
    if not isinstance(cfg, dict):
        raise ChorusFatalError("CONFIG_NOT_OBJECT", "Config must be a JSON object", {"type": str(type(cfg))})
    return cfg


def load_and_canonicalize_config(path: Path) -> Dict[str, Any]:
    return canonicalize_config(load_config(path))


def load_run_config(run_root: Path) -> Dict[str, Any]:
    """Load the canonicalized config stored inside a run folder."""
    return load_and_canonicalize_config(run_root / "00_meta" / "config.canonical.json")
