"""Tests for Stage 3 (Summarization) — three independent summaries, state, retry slots."""
import json

import pytest

from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.stages.summarize import run_summarize, generate_summary_for_slot
from chorus_ai.tests.conftest import (
    SOURCE_SHA, SAMPLE_FACTS, SAMPLE_SUMMARY_TEXT,
    make_run_dir, advance_to_extracted,
)


class TestRunSummarize:
    def test_wrong_state_raises(self, tmp_path):
        run_root = make_run_dir(tmp_path, state="INIT")
        with pytest.raises(ChorusFatalError, match="BAD_RUN_STATE"):
            run_summarize(str(run_root))

    def test_creates_three_summary_files(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_extracted(run_root)
        run_summarize(str(run_root))

        for fname in ["summary_a.json", "summary_b.json", "summary_c.json"]:
            assert (run_root / "30_summarization" / fname).exists()

    def test_summary_content_structure(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_extracted(run_root)
        run_summarize(str(run_root))

        data = json.loads((run_root / "30_summarization" / "summary_a.json").read_text())
        assert data["schema_version"] == "v1"
        assert data["model_slot"] == "summarizer_a"
        assert data["source_doc_sha256"] == SOURCE_SHA
        assert data["fact_count"] == len(SAMPLE_FACTS)
        assert data["summary_text"] == SAMPLE_SUMMARY_TEXT
        assert "facts_path" in data["inputs"]

    def test_updates_status_summaries(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_extracted(run_root)
        paths = run_summarize(str(run_root))

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert len(status["summaries"]) == 3
        assert paths == status["summaries"]

    def test_advances_state(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_extracted(run_root)
        run_summarize(str(run_root))

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert status["state"] == "SUMMARIZED"

    def test_deterministic_summary_ids(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_extracted(run_root)
        run_summarize(str(run_root))

        data = json.loads((run_root / "30_summarization" / "summary_a.json").read_text())
        assert data["summary_id"] == f"SUM_SUMMARIZER_A_{SOURCE_SHA[:8]}"


class TestRetrySlots:
    def test_retry_only_regenerates_specified_slot(self, tmp_path, mock_llm):
        from chorus_ai.tests.conftest import advance_to_summarized
        run_root = make_run_dir(tmp_path)
        advance_to_summarized(run_root)

        # Record mtime of summary_a before retry
        path_a = run_root / "30_summarization" / "summary_a.json"
        mtime_a_before = path_a.stat().st_mtime

        # Retry only summarizer_b
        run_summarize(str(run_root), force=True, slots=["summarizer_b"])

        # summary_a must be untouched
        assert path_a.stat().st_mtime == mtime_a_before
        # summary_b must have been rewritten
        assert (run_root / "30_summarization" / "summary_b.json").exists()

    def test_retry_does_not_advance_state(self, tmp_path, mock_llm):
        from chorus_ai.tests.conftest import advance_to_summarized
        run_root = make_run_dir(tmp_path)
        advance_to_summarized(run_root)

        run_summarize(str(run_root), force=True, slots=["summarizer_c"])

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        # State should remain SUMMARIZED, not regress or double-advance
        assert status["state"] == "SUMMARIZED"
