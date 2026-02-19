"""Unified LLM API wrapper for Chorus AI.

Supports Anthropic (claude-* models) natively.
Non-Anthropic model names fall back to the Anthropic haiku model with a warning.
All calls use temperature=0 for determinism (per CLAUDE.md Core Design Rules).
"""
from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path
from typing import Any

_FALLBACK_MODEL = "claude-haiku-4-5-20251001"


def _is_anthropic(model: str) -> bool:
    return model.startswith("claude-")


def parse_json_response(text: str) -> Any:
    """Extract JSON from an LLM response, handling markdown code fences."""
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip ```json ... ``` or ``` ... ``` fences
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find the first complete {...} block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"Could not parse JSON from LLM response. First 300 chars: {text[:300]}"
    )


def load_prompt(name: str) -> str:
    """Load a prompt file from stages/prompts/<name>.txt"""
    prompts_dir = Path(__file__).parent.parent / "stages" / "prompts"
    path = prompts_dir / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


class LLMClient:
    """Thin, deterministic wrapper around LLM API calls."""

    def __init__(self, config: dict) -> None:
        self._config = config

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        """Call the LLM and return response text. Falls back for non-Anthropic models."""
        if not _is_anthropic(model):
            warnings.warn(
                f"Non-Anthropic model '{model}' not yet supported; "
                f"falling back to '{_FALLBACK_MODEL}'.",
                UserWarning,
                stacklevel=2,
            )
            model = _FALLBACK_MODEL

        return self._call_anthropic(
            model=model,
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def _call_anthropic(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from exc

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text  # type: ignore[index]
