"""Tests for the LLM client — JSON parsing and non-Anthropic fallback."""
import json
import warnings

import pytest

from chorus_ai.llm.client import LLMClient, parse_json_response


class TestParseJsonResponse:
    def test_direct_json(self):
        obj = {"facts": [{"fact_id": "F001"}]}
        assert parse_json_response(json.dumps(obj)) == obj

    def test_markdown_fence_json(self):
        text = '```json\n{"key": "value"}\n```'
        assert parse_json_response(text) == {"key": "value"}

    def test_markdown_fence_no_lang(self):
        text = '```\n{"key": "value"}\n```'
        assert parse_json_response(text) == {"key": "value"}

    def test_embedded_json_in_prose(self):
        text = 'Here is the result: {"score": 0.9} as requested.'
        assert parse_json_response(text) == {"score": 0.9}

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Could not parse JSON"):
            parse_json_response("This is definitely not JSON at all.")

    def test_whitespace_stripped(self):
        assert parse_json_response('  {"a": 1}  ') == {"a": 1}


class TestNonAnthropicFallback:
    def test_non_anthropic_model_warns(self, monkeypatch):
        monkeypatch.setattr(
            LLMClient,
            "_call_anthropic",
            lambda self, **kw: "response",
        )
        client = LLMClient({})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            client.complete(model="gemini-1.5-flash", system="sys", user="usr")
        assert len(w) == 1
        assert "gemini-1.5-flash" in str(w[0].message)
        assert "claude-haiku" in str(w[0].message)

    def test_non_anthropic_falls_back_to_haiku(self, monkeypatch):
        called_with = {}

        def fake_call(self, *, model, system, user, max_tokens, temperature):
            called_with["model"] = model
            return "ok"

        monkeypatch.setattr(LLMClient, "_call_anthropic", fake_call)
        client = LLMClient({})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            client.complete(model="llama-3-8b", system="s", user="u")
        assert called_with["model"] == "claude-haiku-4-5-20251001"

    def test_anthropic_model_no_warning(self, monkeypatch):
        monkeypatch.setattr(LLMClient, "_call_anthropic", lambda self, **kw: "ok")
        client = LLMClient({})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            client.complete(model="claude-haiku-4-5-20251001", system="s", user="u")
        assert len(w) == 0
