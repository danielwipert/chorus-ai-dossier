"""Tests for CLI failure artifact — failure.json written on ChorusFatalError."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from chorus_ai.cli import main
from chorus_ai.tests.conftest import TEST_PDF


@pytest.mark.skipif(not TEST_PDF.exists(), reason="test.pdf not present")
class TestFailureArtifact:
    def test_failure_json_written_on_stage_error(self, tmp_path, monkeypatch):
        """A ChorusFatalError mid-pipeline writes failure.json to 00_meta/."""
        from chorus_ai.llm.client import LLMClient

        # Make extraction blow up
        monkeypatch.setattr(
            LLMClient, "_call_anthropic",
            lambda self, **kw: (_ for _ in ()).throw(RuntimeError("injected failure"))
        )

        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({
                "pipeline_version": "v1",
                "models": {
                    "fact_finder": "claude-haiku-4-5-20251001",
                    "summarizer_a": "claude-haiku-4-5-20251001",
                    "summarizer_b": "claude-haiku-4-5-20251001",
                    "summarizer_c": "claude-haiku-4-5-20251001",
                    "compiler": "claude-sonnet-4-6",
                    "contextualizer_a": "claude-sonnet-4-6",
                    "contextualizer_b": "claude-sonnet-4-6",
                },
                "verification": {"pass_threshold": 0.75, "max_retries": 1},
                "ingestion": {"min_chars_per_page": 50},
            }),
            encoding="utf-8",
        )

        runs_dir = tmp_path / "runs"
        ret = main([str(TEST_PDF), "--config", str(config_path), "--runs-dir", str(runs_dir)])

        assert ret == 2  # CLI returns error code

        # Find the run folder (there should be exactly one)
        run_folders = list(runs_dir.glob("dossier_*"))
        assert len(run_folders) == 1
        run_root = run_folders[0]

        failure_path = run_root / "00_meta" / "failure.json"
        assert failure_path.exists(), "failure.json must be written on fatal error"

        failure = json.loads(failure_path.read_text())
        assert failure["ok"] is False
        assert "error" in failure
        assert "message" in failure
        assert "failed_at" in failure

    def test_cli_success_no_failure_json(self, tmp_path, monkeypatch):
        """A successful run must NOT produce a failure.json."""
        from chorus_ai.llm.client import LLMClient
        from chorus_ai.tests.conftest import _fake_call_anthropic
        monkeypatch.setattr(LLMClient, "_call_anthropic", _fake_call_anthropic)

        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({
                "pipeline_version": "v1",
                "models": {
                    "fact_finder": "claude-haiku-4-5-20251001",
                    "summarizer_a": "claude-haiku-4-5-20251001",
                    "summarizer_b": "claude-haiku-4-5-20251001",
                    "summarizer_c": "claude-haiku-4-5-20251001",
                    "compiler": "claude-sonnet-4-6",
                    "contextualizer_a": "claude-sonnet-4-6",
                    "contextualizer_b": "claude-sonnet-4-6",
                },
                "verification": {"pass_threshold": 0.75, "max_retries": 1},
                "ingestion": {"min_chars_per_page": 50},
            }),
            encoding="utf-8",
        )

        runs_dir = tmp_path / "runs"
        ret = main([str(TEST_PDF), "--config", str(config_path), "--runs-dir", str(runs_dir)])

        assert ret == 0

        run_folders = list(runs_dir.glob("dossier_*"))
        assert len(run_folders) == 1
        run_root = run_folders[0]

        assert not (run_root / "00_meta" / "failure.json").exists()
