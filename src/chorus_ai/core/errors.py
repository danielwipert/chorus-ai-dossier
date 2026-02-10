from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ChorusFatalError(Exception):
    """
    Fatal error that halts the pipeline immediately.
    All non-recoverable failures MUST raise this type.
    """
    code: str
    message: str
    details: Dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
