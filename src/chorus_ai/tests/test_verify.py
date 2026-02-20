"""Tests for Stage 4 (Verification) — structural checks, semantic scoring, pass rule, retry."""
import json
from unittest.mock import patch

import pytest

from chorus_ai.core.verification.verify_summary_v1 import verify_summary_v1, _structural_check
from chorus_ai.stages.verify import run_verify
from chorus_ai.tests.conftest import (
    SOURCE_SHA, SAMPLE_FACTS, SAMPLE_SUMMARY_TEXT,
    make_run_dir, advance_to_summarized,
)


# ---------------------------------------------------------------------------
# Unit tests for verify_summary_v1 (core logic)
# ---------------------------------------------------------------------------

def _make_summary(text=SAMPLE_SUMMARY_TEXT, fact_count=2, slot="summarizer_a"):
    return {
        "schema_version": "v1",
        "summary_id": f"SUM_{slot.upper()}_{SOURCE_SHA[:8]}",
        "model_slot": slot,
        "source_doc_sha256": SOURCE_SHA,
        "created_at": "2026-01-01T00:00:00+00:00",
        "summary_text": text,
        "fact_count": fact_count,
        "inputs": {"facts_path": "20_extraction/fact_list.json"},
    }


class TestStructuralCheck:
    def test_valid_summary_passes(self):
        result = _structural_check(_make_summary(), fact_count=2)
        assert result["status"] == "pass"

    def test_missing_summary_text_fails(self):
        s = _make_summary()
        del s["summary_text"]
        result = _structural_check(s, fact_count=2)
        assert result["status"] == "fail"

    def test_wrong_fact_count_fails(self):
        result = _structural_check(_make_summary(fact_count=99), fact_count=2)
        assert result["status"] == "fail"

    def test_empty_summary_text_fails(self):
        result = _structural_check(_make_summary(text=""), fact_count=2)
        assert result["status"] == "fail"


class TestVerifySummaryV1:
    def test_no_llm_all_structural_pass(self):
        summaries = [_make_summary(slot=s) for s in
                     ["summarizer_a", "summarizer_b", "summarizer_c"]]
        report = verify_summary_v1(facts=SAMPLE_FACTS, summaries=summaries, llm_client=None)
        assert report["status"] == "pass"
        assert all(r["status"] == "pass" for r in report["summary_results"])

    def test_pass_rule_requires_two(self):
        """Only 1 good summary → fail (need ≥ 2)."""
        good = _make_summary(slot="summarizer_a")
        bad1 = _make_summary(text="", slot="summarizer_b")   # empty text → structural fail
        bad2 = _make_summary(text="", slot="summarizer_c")
        report = verify_summary_v1(
            facts=SAMPLE_FACTS, summaries=[good, bad1, bad2], llm_client=None
        )
        assert report["status"] == "fail"

    def test_two_pass_is_sufficient(self):
        good_a = _make_summary(slot="summarizer_a")
        good_b = _make_summary(slot="summarizer_b")
        bad = _make_summary(text="", slot="summarizer_c")
        report = verify_summary_v1(
            facts=SAMPLE_FACTS, summaries=[good_a, good_b, bad], llm_client=None
        )
        assert report["status"] == "pass"

    def test_semantic_scoring_applied(self, mock_llm):
        from chorus_ai.llm.client import LLMClient
        llm = LLMClient({})
        summaries = [_make_summary(slot=s) for s in
                     ["summarizer_a", "summarizer_b", "summarizer_c"]]
        report = verify_summary_v1(
            facts=SAMPLE_FACTS, summaries=summaries,
            llm_client=llm, pass_threshold=0.75,
        )
        assert report["status"] == "pass"
        for r in report["summary_results"]:
            assert r["coverage_score"] == 0.9  # from mock response

    def test_below_threshold_fails(self, monkeypatch):
        from chorus_ai.llm.client import LLMClient
        low_score_response = json.dumps({
            "total_facts": 2, "covered_facts": 1, "coverage_score": 0.5,
            "unsupported_claims": [], "fact_coverage": [],
        })
        monkeypatch.setattr(
            LLMClient, "_call_anthropic", lambda self, **kw: low_score_response
        )
        llm = LLMClient({})
        summaries = [_make_summary(slot=s) for s in
                     ["summarizer_a", "summarizer_b", "summarizer_c"]]
        report = verify_summary_v1(
            facts=SAMPLE_FACTS, summaries=summaries,
            llm_client=llm, pass_threshold=0.75,
        )
        assert report["status"] == "fail"

    def test_zero_facts_auto_pass(self, mock_llm):
        from chorus_ai.llm.client import LLMClient
        llm = LLMClient({})
        summaries = [_make_summary(fact_count=0, slot=s) for s in
                     ["summarizer_a", "summarizer_b", "summarizer_c"]]
        report = verify_summary_v1(facts=[], summaries=summaries, llm_client=llm)
        assert report["status"] == "pass"
        for r in report["summary_results"]:
            assert r["coverage_score"] == 1.0


# ---------------------------------------------------------------------------
# Integration tests for run_verify (stage-level)
# ---------------------------------------------------------------------------

class TestRunVerify:
    def test_wrong_state_raises(self, tmp_path):
        from chorus_ai.core.errors import ChorusFatalError
        run_root = make_run_dir(tmp_path, state="INIT")
        with pytest.raises(ChorusFatalError, match="BAD_RUN_STATE"):
            run_verify(str(run_root))

    def test_produces_verification_report(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_summarized(run_root)
        result = run_verify(str(run_root))

        assert result["ok"] is True
        report_path = run_root / "40_verification" / "verification_report.json"
        assert report_path.exists()

    def test_advances_state_on_pass(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_summarized(run_root)
        run_verify(str(run_root))

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert status["state"] == "VERIFIED"

    def test_passing_summaries_stored_in_status(self, tmp_path, mock_llm):
        run_root = make_run_dir(tmp_path)
        advance_to_summarized(run_root)
        run_verify(str(run_root))

        status = json.loads((run_root / "00_meta" / "status.json").read_text())
        assert len(status["passing_summaries"]) >= 2

    def test_retry_regenerates_failed_summaries(self, tmp_path, monkeypatch):
        """When < 2 pass on first attempt, retry regenerates failed slots."""
        from chorus_ai.llm.client import LLMClient

        call_count = {"n": 0}
        passing_response = json.dumps({
            "total_facts": 2, "covered_facts": 2, "coverage_score": 0.9,
            "unsupported_claims": [], "fact_coverage": [],
        })
        failing_response = json.dumps({
            "total_facts": 2, "covered_facts": 0, "coverage_score": 0.1,
            "unsupported_claims": [], "fact_coverage": [],
        })

        def fake_call(self, *, model, system, user, max_tokens, temperature):
            call_count["n"] += 1
            if "verification expert" in system.lower():
                # First two verify calls fail, then pass after retry
                if call_count["n"] <= 3:
                    return failing_response
                return passing_response
            return SAMPLE_SUMMARY_TEXT  # summarizer calls

        monkeypatch.setattr(LLMClient, "_call_anthropic", fake_call)

        run_root = make_run_dir(tmp_path)
        advance_to_summarized(run_root)
        result = run_verify(str(run_root))

        report_path = run_root / "40_verification" / "verification_report.json"
        report = json.loads(report_path.read_text())
        assert report["retries_used"] >= 1
