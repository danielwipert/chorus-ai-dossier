"""Tests for Stage 1 (Ingestion) — PDF extraction, density gate, artifact structure."""
import json
from unittest.mock import patch, MagicMock

import pytest

from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.stages.ingest import run_ingest, _extract_pages, _build_document_text
from chorus_ai.tests.conftest import SOURCE_SHA, make_run_dir, TEST_PDF


class TestBuildDocumentText:
    def test_page_markers_present(self):
        pages = [
            {"page_num": 1, "char_count": 10, "paragraph_count": 1,
             "paragraphs": [{"para_idx": 0, "text": "Hello world."}]},
            {"page_num": 2, "char_count": 8, "paragraph_count": 1,
             "paragraphs": [{"para_idx": 0, "text": "Page two."}]},
        ]
        text = _build_document_text(pages)
        assert "[PAGE 1]" in text
        assert "[PAGE 2]" in text
        assert "Hello world." in text
        assert "Page two." in text

    def test_empty_pages_returns_empty(self):
        assert _build_document_text([]) == ""


class TestRunIngest:
    def test_wrong_state_raises(self, tmp_path):
        run_root = make_run_dir(tmp_path, state="INGESTED")
        with pytest.raises(ChorusFatalError, match="BAD_RUN_STATE"):
            run_ingest(run_root, SOURCE_SHA)

    def test_missing_pdf_raises(self, tmp_path):
        run_root = make_run_dir(tmp_path, state="INIT")
        (run_root / "00_input" / "input.pdf").unlink(missing_ok=True)
        with pytest.raises(ChorusFatalError, match="INPUT_PDF_MISSING"):
            run_ingest(run_root, SOURCE_SHA)

    def test_image_only_pdf_rejected(self, tmp_path):
        run_root = make_run_dir(tmp_path, state="INIT")
        # Mock _extract_pages to return 0 chars per page
        zero_density_pages = [
            {"page_num": 1, "char_count": 0, "paragraph_count": 0, "paragraphs": []}
        ]
        with patch("chorus_ai.stages.ingest._extract_pages", return_value=zero_density_pages):
            with pytest.raises(ChorusFatalError, match="PDF_INELIGIBLE"):
                run_ingest(run_root, SOURCE_SHA)

    @pytest.mark.skipif(not TEST_PDF.exists(), reason="test.pdf not present")
    def test_real_pdf_produces_artifacts(self, tmp_path):
        run_root = make_run_dir(tmp_path, state="INIT")
        run_ingest(run_root, SOURCE_SHA)

        record_path = run_root / "10_ingestion" / "ingestion_record.json"
        text_path = run_root / "10_ingestion" / "document_text.txt"

        assert record_path.exists()
        assert text_path.exists()

        record = json.loads(record_path.read_text())
        assert record["schema_version"] == "v1"
        assert record["source_doc_sha256"] == SOURCE_SHA
        assert record["page_count"] > 0
        assert record["total_chars"] > 0
        assert record["eligible"] is True

        text = text_path.read_text(encoding="utf-8")
        assert "[PAGE 1]" in text

    @pytest.mark.skipif(not TEST_PDF.exists(), reason="test.pdf not present")
    def test_real_pdf_advances_state(self, tmp_path):
        run_root = make_run_dir(tmp_path, state="INIT")
        run_ingest(run_root, SOURCE_SHA)

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert status["state"] == "INGESTED"

    @pytest.mark.skipif(not TEST_PDF.exists(), reason="test.pdf not present")
    def test_overwrite_refused_without_force(self, tmp_path):
        run_root = make_run_dir(tmp_path, state="INIT")
        run_ingest(run_root, SOURCE_SHA)
        # Reset state to INIT so require_state passes but output already exists
        from chorus_ai.runs.status import set_state
        set_state(run_root, "INGESTED")
        # Now reset to INIT to re-attempt
        from chorus_ai.runs.status import write_status, read_status
        s = read_status(run_root)
        s["state"] = "INIT"
        write_status(run_root, s, force=True)
        with pytest.raises(ChorusFatalError, match="STAGE_ALREADY_DONE"):
            run_ingest(run_root, SOURCE_SHA, force=False)
