"""Tests for the LLM client — JSON parsing, provider routing, and fallback."""
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


class TestAnthropicRouting:
    def test_claude_model_routes_to_anthropic(self, monkeypatch):
        called = {}

        def fake_anthropic(self, *, model, system, user, max_tokens, temperature):
            called["model"] = model
            return "ok"

        monkeypatch.setattr(LLMClient, "_call_anthropic", fake_anthropic)
        client = LLMClient({})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = client.complete(model="claude-haiku-4-5-20251001", system="s", user="u")
        assert result == "ok"
        assert called["model"] == "claude-haiku-4-5-20251001"
        assert len(w) == 0  # no warnings for a known Anthropic model

    def test_claude_sonnet_routes_to_anthropic(self, monkeypatch):
        called = {}

        def fake_anthropic(self, *, model, system, user, max_tokens, temperature):
            called["model"] = model
            return "ok"

        monkeypatch.setattr(LLMClient, "_call_anthropic", fake_anthropic)
        client = LLMClient({})
        client.complete(model="claude-sonnet-4-6", system="s", user="u")
        assert called["model"] == "claude-sonnet-4-6"


class TestHuggingFaceRouting:
    def test_hf_model_routes_to_huggingface(self, monkeypatch):
        called = {}

        def fake_hf(self, *, model, system, user, max_tokens, temperature):
            called["model"] = model
            return "hf response"

        monkeypatch.setattr(LLMClient, "_call_huggingface", fake_hf)
        client = LLMClient({})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = client.complete(model="meta-llama/Llama-3.1-8B-Instruct", system="s", user="u")
        assert result == "hf response"
        assert called["model"] == "meta-llama/Llama-3.1-8B-Instruct"
        assert len(w) == 0  # no warnings for a known HF model

    def test_qwen_model_routes_to_huggingface(self, monkeypatch):
        called = {}

        def fake_hf(self, *, model, system, user, max_tokens, temperature):
            called["model"] = model
            return "ok"

        monkeypatch.setattr(LLMClient, "_call_huggingface", fake_hf)
        client = LLMClient({})
        client.complete(model="Qwen/Qwen2.5-7B-Instruct", system="s", user="u")
        assert called["model"] == "Qwen/Qwen2.5-7B-Instruct"

    def test_llama_70b_routes_to_huggingface(self, monkeypatch):
        called = {}

        def fake_hf(self, *, model, system, user, max_tokens, temperature):
            called["model"] = model
            return "ok"

        monkeypatch.setattr(LLMClient, "_call_huggingface", fake_hf)
        client = LLMClient({})
        client.complete(model="meta-llama/Llama-3.1-70B-Instruct", system="s", user="u")
        assert called["model"] == "meta-llama/Llama-3.1-70B-Instruct"

    def test_hf_does_not_call_anthropic(self, monkeypatch):
        monkeypatch.setattr(LLMClient, "_call_huggingface", lambda self, **kw: "hf ok")

        anthropic_called = []
        monkeypatch.setattr(
            LLMClient, "_call_anthropic", lambda self, **kw: anthropic_called.append(1) or "x"
        )
        client = LLMClient({})
        client.complete(model="meta-llama/Llama-3.1-8B-Instruct", system="s", user="u")
        assert len(anthropic_called) == 0


class TestUnknownModelFallback:
    def test_unknown_model_warns(self, monkeypatch):
        monkeypatch.setattr(LLMClient, "_call_anthropic", lambda self, **kw: "response")
        client = LLMClient({})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            client.complete(model="some-unknown-model", system="sys", user="usr")
        assert len(w) == 1
        assert "some-unknown-model" in str(w[0].message)
        assert "claude-haiku" in str(w[0].message)

    def test_unknown_model_falls_back_to_haiku(self, monkeypatch):
        called_with = {}

        def fake_call(self, *, model, system, user, max_tokens, temperature):
            called_with["model"] = model
            return "ok"

        monkeypatch.setattr(LLMClient, "_call_anthropic", fake_call)
        client = LLMClient({})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            client.complete(model="some-unknown-model", system="s", user="u")
        assert called_with["model"] == "claude-haiku-4-5-20251001"
