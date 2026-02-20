"""Tests for Stage 7 (Export) — all 6 required sections, audit trail, state advancement."""
import json

import pytest

from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.stages.export import run_export
from chorus_ai.tests.conftest import SOURCE_SHA, make_run_dir, advance_to_compiled

REQUIRED_SECTIONS = [
    "executive_overview",
    "key_claims",
    "compiled_summary",
    "contextual_analysis",
    "risks_and_limitations",
    "audit_trail",
]


class TestRunExport:
    def test_wrong_state_raises(self, tmp_path):
        run_root = make_run_dir(tmp_path, state="INIT")
        with pytest.raises(ChorusFatalError, match="BAD_RUN_STATE"):
            run_export(str(run_root))

    def test_produces_final_dossier(self, tmp_path):
        run_root = make_run_dir(tmp_path)
        advance_to_compiled(run_root)
        result = run_export(str(run_root))

        assert result["ok"] is True
        assert (run_root / "70_export" / "final_dossier.json").exists()

    def test_all_six_sections_present(self, tmp_path):
        run_root = make_run_dir(tmp_path)
        advance_to_compiled(run_root)
        run_export(str(run_root))

        dossier = json.loads((run_root / "70_export" / "final_dossier.json").read_text())
        sections = dossier["sections"]
        for section in REQUIRED_SECTIONS:
            assert section in sections, f"Missing required section: {section}"

    def test_dossier_schema_fields(self, tmp_path):
        run_root = make_run_dir(tmp_path)
        advance_to_compiled(run_root)
        run_export(str(run_root))

        dossier = json.loads((run_root / "70_export" / "final_dossier.json").read_text())
        assert dossier["schema_version"] == "v1"
        assert dossier["dossier_id"] == f"DOS_{SOURCE_SHA[:12]}"
        assert dossier["source_doc_sha256"] == SOURCE_SHA
        assert isinstance(dossier["export_paths"], list)
        assert dossier["run_status"] == "complete"

    def test_audit_trail_contents(self, tmp_path):
        run_root = make_run_dir(tmp_path)
        advance_to_compiled(run_root)
        run_export(str(run_root))

        dossier = json.loads((run_root / "70_export" / "final_dossier.json").read_text())
        audit = dossier["sections"]["audit_trail"]
        assert audit["source_doc_sha256"] == SOURCE_SHA
        assert audit["fact_count"] == 2
        assert "verification" in audit
        assert "compilation" in audit

    def test_advances_state_to_finalized(self, tmp_path):
        run_root = make_run_dir(tmp_path)
        advance_to_compiled(run_root)
        run_export(str(run_root))

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert status["state"] == "FINALIZED"

    def test_key_claims_are_list(self, tmp_path):
        run_root = make_run_dir(tmp_path)
        advance_to_compiled(run_root)
        run_export(str(run_root))

        dossier = json.loads((run_root / "70_export" / "final_dossier.json").read_text())
        assert isinstance(dossier["sections"]["key_claims"], list)

    def test_produces_pdf(self, tmp_path):
        run_root = make_run_dir(tmp_path)
        advance_to_compiled(run_root)
        result = run_export(str(run_root))

        pdf_path = run_root / "70_export" / "final_dossier.pdf"
        assert pdf_path.exists(), "final_dossier.pdf must be produced"
        assert pdf_path.stat().st_size > 0
        assert pdf_path.read_bytes()[:4] == b"%PDF"
        assert result["pdf"] is not None

    def test_pdf_path_in_export_paths(self, tmp_path):
        run_root = make_run_dir(tmp_path)
        advance_to_compiled(run_root)
        run_export(str(run_root))

        dossier = json.loads((run_root / "70_export" / "final_dossier.json").read_text())
        assert any("pdf" in p for p in dossier["export_paths"])

    def test_contextual_section_notes_absence_when_missing(self, tmp_path):
        run_root = make_run_dir(tmp_path)
        advance_to_compiled(run_root)

        # Remove contextual analyses from status
        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        status["contextual_analyses"] = []
        (run_root / "00_meta" / "status.json").write_text(json.dumps(status), encoding="utf-8")

        run_export(str(run_root))

        dossier = json.loads((run_root / "70_export" / "final_dossier.json").read_text())
        ctx = dossier["sections"]["contextual_analysis"]
        assert "No contextual analysis" in ctx
