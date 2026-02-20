"""Tests for Stage 5 (Contextual Analysis) — non-fatal behavior, artifact writing."""
import json

import pytest

from chorus_ai.llm.client import LLMClient
from chorus_ai.stages.contextualize import run_contextualize
from chorus_ai.tests.conftest import make_run_dir, advance_to_verified


class TestRunContextualize:
    def test_wrong_state_raises(self, tmp_path):
        from chorus_ai.core.errors import ChorusFatalError
        run_root = make_run_dir(tmp_path, state="INIT")
        with pytest.raises(ChorusFatalError, match="BAD_RUN_STATE"):
            run_contextualize(run_root)

    def test_succeeds_and_writes_artifacts(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_verified(run_root)
        result = run_contextualize(run_root)

        assert result["ok"] is True
        assert (run_root / "50_contextual" / "contextual_a.json").exists()

    def test_contextual_artifact_structure(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_verified(run_root)
        run_contextualize(run_root)

        data = json.loads((run_root / "50_contextual" / "contextual_a.json").read_text())
        assert data["schema_version"] == "v1"
        assert data["model_slot"] == "contextualizer_a"
        assert isinstance(data["sections"], list)
        assert len(data["sections"]) > 0

    def test_advances_state(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_verified(run_root)
        run_contextualize(run_root)

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert status["state"] == "CONTEXTUALIZED"

    def test_updates_status_contextual_analyses(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_verified(run_root)
        run_contextualize(run_root)

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert len(status["contextual_analyses"]) > 0

    def test_nonfatal_on_llm_failure(self, tmp_path, monkeypatch):
        """If the contextualizer model fails, stage still returns ok=True."""
        monkeypatch.setattr(
            LLMClient, "_call_anthropic",
            lambda self, **kw: (_ for _ in ()).throw(RuntimeError("API down"))
        )
        run_root = make_run_dir(tmp_path)
        advance_to_verified(run_root)
        result = run_contextualize(run_root)

        assert result["ok"] is True
        assert len(result["warnings"]) > 0

    def test_state_advances_even_on_llm_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            LLMClient, "_call_anthropic",
            lambda self, **kw: (_ for _ in ()).throw(RuntimeError("API down"))
        )
        run_root = make_run_dir(tmp_path)
        advance_to_verified(run_root)
        run_contextualize(run_root)

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert status["state"] == "CONTEXTUALIZED"
