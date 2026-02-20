"""Unified LLM API wrapper for Chorus AI.

Supported providers (routing is automatic from the model name):
  - Anthropic: any model starting with "claude-"
  - Together AI: any model starting with "together:" (e.g. "together:mistralai/Mixtral-8x7B-Instruct-v0.1")
  - HuggingFace Inference API: any model containing "/" (e.g. "Qwen/Qwen2.5-72B-Instruct")
  - Unknown models: fall back to Anthropic haiku with a warning (same as before)

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
_HF_BASE_URL = "https://router.huggingface.co/v1/"
_TOGETHER_BASE_URL = "https://api.together.xyz/v1"
_TOGETHER_PREFIX = "together:"


def _is_anthropic(model: str) -> bool:
    return model.startswith("claude-")


def _is_together(model: str) -> bool:
    """Together AI models are prefixed with 'together:' (e.g. 'together:mistralai/Mixtral-8x7B-Instruct-v0.1')."""
    return model.startswith(_TOGETHER_PREFIX)


def _is_huggingface(model: str) -> bool:
    """HuggingFace model names contain a slash but no provider prefix."""
    return "/" in model and not _is_together(model)


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
        """Route to the correct provider based on model name and return response text."""
        if _is_anthropic(model):
            return self._call_anthropic(
                model=model,
                system=system,
                user=user,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        if _is_together(model):
            return self._call_together(
                model=model,
                system=system,
                user=user,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        if _is_huggingface(model):
            return self._call_huggingface(
                model=model,
                system=system,
                user=user,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        # Unknown model — fall back to haiku with a warning
        warnings.warn(
            f"Unknown model '{model}' is not Anthropic, Together AI, or HuggingFace; "
            f"falling back to '{_FALLBACK_MODEL}'.",
            UserWarning,
            stacklevel=2,
        )
        return self._call_anthropic(
            model=_FALLBACK_MODEL,
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

    def _call_huggingface(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            ) from exc

        api_key = os.environ.get("HF_TOKEN")
        if not api_key:
            raise RuntimeError("HF_TOKEN environment variable is not set.")

        client = OpenAI(base_url=_HF_BASE_URL, api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError(f"HuggingFace model '{model}' returned an empty response.")
        return content

    def _call_together(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            ) from exc

        api_key = os.environ.get("TOGETHER_API_KEY")
        if not api_key:
            raise RuntimeError("TOGETHER_API_KEY environment variable is not set.")

        # Strip the "together:" prefix before sending to the API
        model_id = model[len(_TOGETHER_PREFIX):]

        client = OpenAI(base_url=_TOGETHER_BASE_URL, api_key=api_key)
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError(f"Together AI model '{model_id}' returned an empty response.")
        return content
