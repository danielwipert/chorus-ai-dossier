"""Tests for Stage 2 (Extraction) — LLM fact extraction, validation, error handling."""
import json

import pytest

from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.stages.extract import run_extract, _validate_facts
from chorus_ai.tests.conftest import SOURCE_SHA, SAMPLE_FACTS, make_run_dir, advance_to_ingested


class TestValidateFacts:
    def test_valid_facts_pass_through(self):
        result = _validate_facts(SAMPLE_FACTS)
        assert len(result) == len(SAMPLE_FACTS)
        assert result[0]["fact_id"] == "F001"

    def test_non_dict_entries_skipped(self):
        result = _validate_facts([SAMPLE_FACTS[0], "not a dict", 42])
        assert len(result) == 1

    def test_empty_claim_skipped(self):
        bad = [{"fact_id": "F001", "claim": "", "type": "empirical_claim",
                "source_location": {"page": 1, "paragraph": 1}, "confidence": 0.9}]
        assert _validate_facts(bad) == []

    def test_invalid_type_normalized(self):
        fact = {**SAMPLE_FACTS[0], "type": "totally_invalid_type"}
        result = _validate_facts([fact])
        assert result[0]["type"] == "empirical_claim"

    def test_confidence_clamped(self):
        fact = {**SAMPLE_FACTS[0], "confidence": 999.0}
        result = _validate_facts([fact])
        assert result[0]["confidence"] == 1.0

    def test_missing_source_location_defaults(self):
        fact = {**SAMPLE_FACTS[0]}
        del fact["source_location"]
        result = _validate_facts([fact])
        assert result[0]["source_location"] == {"page": 1, "paragraph": 1}


class TestRunExtract:
    def test_wrong_state_raises(self, tmp_path):
        run_root = make_run_dir(tmp_path, state="INIT")
        with pytest.raises(ChorusFatalError, match="BAD_RUN_STATE"):
            run_extract(run_root)

    def test_produces_fact_list(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_ingested(run_root)
        run_extract(run_root)

        path = run_root / "20_extraction" / "fact_list.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["schema_version"] == "v1"
        assert data["source_doc_sha256"] == SOURCE_SHA
        assert isinstance(data["facts"], list)
        assert len(data["facts"]) == len(SAMPLE_FACTS)

    def test_advances_state(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_ingested(run_root)
        run_extract(run_root)

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert status["state"] == "EXTRACTED"

    def test_bad_llm_json_raises(self, tmp_path, monkeypatch):
        from chorus_ai.llm.client import LLMClient
        monkeypatch.setattr(
            LLMClient, "_call_anthropic", lambda self, **kw: "not json at all!!!"
        )
        run_root = make_run_dir(tmp_path)
        advance_to_ingested(run_root)
        with pytest.raises(ChorusFatalError, match="LLM_BAD_JSON"):
            run_extract(run_root)
