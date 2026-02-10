from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from chorus_ai.core.errors import ChorusFatalError


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ChorusFatalError("FILE_MISSING", "Required file is missing", {"path": str(path)})
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ChorusFatalError("FILE_INVALID_JSON", "File is not valid JSON", {"path": str(path), "error": str(e)})


def write_json(path: Path, obj: Dict[str, Any], force: bool = False) -> None:
    if path.exists() and not force:
        raise ChorusFatalError("OVERWRITE_REFUSED", "Refusing to overwrite existing output (use --force)", {"path": str(path)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
