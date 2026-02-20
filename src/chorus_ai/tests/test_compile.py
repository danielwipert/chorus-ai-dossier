"""Tests for Stage 6 (Compilation) — LLM synthesis, artifact structure, error handling."""
import json

import pytest

from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.llm.client import LLMClient
from chorus_ai.stages.compile import run_compile
from chorus_ai.tests.conftest import SOURCE_SHA, make_run_dir, advance_to_contextualized


class TestRunCompile:
    def test_wrong_state_raises(self, tmp_path):
        run_root = make_run_dir(tmp_path, state="INIT")
        with pytest.raises(ChorusFatalError, match="BAD_RUN_STATE"):
            run_compile(str(run_root))

    def test_produces_compiled_summary(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_contextualized(run_root)
        result = run_compile(str(run_root))

        assert result["ok"] is True
        path = run_root / "60_compilation" / "compiled_summary.json"
        assert path.exists()

    def test_compiled_artifact_structure(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_contextualized(run_root)
        run_compile(str(run_root))

        data = json.loads((run_root / "60_compilation" / "compiled_summary.json").read_text())
        assert data["schema_version"] == "v1"
        assert data["compiled_id"] == f"COMP_{SOURCE_SHA[:12]}"
        assert data["source_doc_sha256"] == SOURCE_SHA
        assert data["executive_overview"]
        assert isinstance(data["key_claims"], list)
        assert data["compiled_summary_text"]
        assert data["risks_and_limitations"]

    def test_advances_state(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_contextualized(run_root)
        run_compile(str(run_root))

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert status["state"] == "COMPILED"

    def test_bad_llm_json_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            LLMClient, "_call_anthropic",
            lambda self, **kw: "definitely not json"
        )
        run_root = make_run_dir(tmp_path)
        advance_to_contextualized(run_root)
        with pytest.raises(ChorusFatalError, match="LLM_CALL_FAILED"):
            run_compile(str(run_root))

    def test_lineage_recorded(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_contextualized(run_root)
        run_compile(str(run_root))

        data = json.loads((run_root / "60_compilation" / "compiled_summary.json").read_text())
        assert isinstance(data["section_lineage"], dict)

    def test_inputs_recorded(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_contextualized(run_root)
        run_compile(str(run_root))

        data = json.loads((run_root / "60_compilation" / "compiled_summary.json").read_text())
        assert "passing_summary_paths" in data["inputs"]
        assert "facts_path" in data["inputs"]
