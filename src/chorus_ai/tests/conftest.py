"""
Shared fixtures and helpers for the Chorus AI test suite.

Key design:
- All LLM calls are mocked by patching LLMClient._call_anthropic at the class level.
- Run folders are built programmatically to avoid real API calls in unit tests.
- The real test.pdf is used for integration-level ingestion tests only.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from chorus_ai.llm.client import LLMClient

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # chorusai/
TEST_PDF = PROJECT_ROOT / "test.pdf"

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------
SAMPLE_CONFIG: Dict[str, Any] = {
    "pipeline_version": "v1",
    "models": {
        "summarizer_a": "claude-haiku-4-5-20251001",
        "summarizer_b": "claude-haiku-4-5-20251001",
        "summarizer_c": "claude-haiku-4-5-20251001",
        "fact_finder": "claude-haiku-4-5-20251001",
        "compiler": "claude-sonnet-4-6",
        "contextualizer_a": "claude-sonnet-4-6",
        "contextualizer_b": "claude-sonnet-4-6",
    },
    "verification": {"pass_threshold": 0.75, "max_retries": 1},
    "ingestion": {"min_chars_per_page": 50},
}

SOURCE_SHA = "a" * 64  # fake deterministic sha256

SAMPLE_FACTS: List[Dict[str, Any]] = [
    {
        "fact_id": "F001",
        "claim": "The document argues for X.",
        "type": "author_position",
        "source_location": {"page": 1, "paragraph": 1},
        "confidence": 0.9,
    },
    {
        "fact_id": "F002",
        "claim": "Evidence Y supports the argument.",
        "type": "empirical_claim",
        "source_location": {"page": 1, "paragraph": 2},
        "confidence": 0.85,
    },
]

SAMPLE_SUMMARY_TEXT = (
    "The document argues for X. Evidence Y supports the argument. "
    "The conclusion recommends Z."
)

# Canned LLM responses keyed by system-prompt keyword.
# ORDER MATTERS: more-specific keywords must come before substrings they contain.
# "synthesis expert" must precede "summarizer" because the compile system prompt
# references "summarizer_a" in its example JSON, which would otherwise match first.
_LLM_RESPONSES: Dict[str, str] = {
    "fact extractor": json.dumps({"facts": SAMPLE_FACTS}),
    "synthesis expert": json.dumps(
        {
            "executive_overview": "A concise overview of the document.",
            "key_claims": [
                {
                    "claim": "The document argues for X.",
                    "fact_ids": ["F001"],
                    "convergence": "all",
                    "source_summaries": ["summarizer_a", "summarizer_b", "summarizer_c"],
                }
            ],
            "compiled_summary_text": "Full compiled summary text here.",
            "risks_and_limitations": "Some limitations exist.",
            "section_lineage": {"executive_overview": ["summarizer_a"]},
            "warnings": [],
        }
    ),
    "fact-reporter": SAMPLE_SUMMARY_TEXT,
    "verification expert": json.dumps(
        {
            "total_facts": 2,
            "covered_facts": 2,
            "coverage_score": 0.9,
            "unsupported_claims": [],
            "fact_coverage": [
                {"fact_id": "F001", "covered": True, "note": "Covered directly."},
                {"fact_id": "F002", "covered": True, "note": "Covered directly."},
            ],
        }
    ),
    "contextual analyst": json.dumps(
        {
            "sections": [
                {
                    "lens": "historical_context",
                    "content": "Test historical context.",
                    "sources": ["Smith (2020). Test Book. Publisher."],
                }
            ],
            "limitations": "Limited external sources.",
            "warnings": [],
        }
    ),
}


def _fake_call_anthropic(
    self: Any, *, model: str, system: str, user: str, max_tokens: int, temperature: float
) -> str:
    """Deterministic fake that routes by system-prompt keyword."""
    system_lower = system.lower()
    for keyword, response in _LLM_RESPONSES.items():
        if keyword in system_lower:
            return response
    return "{}"


# ---------------------------------------------------------------------------
# Run folder builder helpers
# ---------------------------------------------------------------------------

def _write_status(run_root: Path, state: str, extra: Dict[str, Any] | None = None) -> None:
    data: Dict[str, Any] = {"state": state, "run_id": "test_run"}
    if extra:
        data.update(extra)
    (run_root / "00_meta" / "status.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def make_run_dir(tmp_path: Path, state: str = "INIT") -> Path:
    """Scaffold a minimal run folder at the given pipeline state."""
    run_root = tmp_path / "test_run"
    for d in [
        "00_meta", "00_input", "10_ingestion", "20_extraction",
        "30_summarization", "40_verification", "50_contextual",
        "60_compilation", "70_export",
    ]:
        (run_root / d).mkdir(parents=True, exist_ok=True)

    (run_root / "00_meta" / "config.canonical.json").write_text(
        json.dumps(SAMPLE_CONFIG, indent=2), encoding="utf-8"
    )
    _write_status(run_root, state)

    if TEST_PDF.exists():
        shutil.copy2(TEST_PDF, run_root / "00_input" / "input.pdf")

    return run_root


def advance_to_ingested(run_root: Path) -> Path:
    doc_text = "[PAGE 1]\nThe document argues for X.\n\nEvidence Y supports the argument.\n"
    (run_root / "10_ingestion" / "document_text.txt").write_text(doc_text, encoding="utf-8")
    record = {
        "schema_version": "v1",
        "source_doc_sha256": SOURCE_SHA,
        "text_path": "10_ingestion/document_text.txt",
        "page_count": 1,
        "total_chars": len(doc_text),
        "avg_chars_per_page": float(len(doc_text)),
        "pages": [{"page_num": 1, "char_count": len(doc_text), "paragraph_count": 2}],
        "eligible": True,
    }
    (run_root / "10_ingestion" / "ingestion_record.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    _write_status(run_root, "INGESTED")
    return run_root


def advance_to_extracted(run_root: Path) -> Path:
    advance_to_ingested(run_root)
    fact_list = {
        "schema_version": "v1",
        "source_doc_sha256": SOURCE_SHA,
        "fact_set_id": f"FACTSET_{SOURCE_SHA[:12]}",
        "facts": SAMPLE_FACTS,
    }
    (run_root / "20_extraction" / "fact_list.json").write_text(
        json.dumps(fact_list, indent=2), encoding="utf-8"
    )
    _write_status(run_root, "EXTRACTED")
    return run_root


def _write_summary(run_root: Path, slot: str, filename: str, text: str = SAMPLE_SUMMARY_TEXT) -> str:
    suffix = slot[-1].upper()
    summary = {
        "schema_version": "v1",
        "summary_id": f"SUM_{slot.upper()}_{SOURCE_SHA[:8]}",
        "model_slot": slot,
        "model_id": "claude-haiku-4-5-20251001",
        "source_doc_sha256": SOURCE_SHA,
        "created_at": "2026-01-01T00:00:00+00:00",
        "summary_text": text,
        "fact_count": len(SAMPLE_FACTS),
        "inputs": {
            "facts_path": "20_extraction/fact_list.json",
            "text_path": "10_ingestion/document_text.txt",
        },
    }
    path = run_root / "30_summarization" / filename
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return str(path.relative_to(run_root))


def advance_to_summarized(run_root: Path) -> Path:
    advance_to_extracted(run_root)
    paths = [
        _write_summary(run_root, "summarizer_a", "summary_a.json"),
        _write_summary(run_root, "summarizer_b", "summary_b.json"),
        _write_summary(run_root, "summarizer_c", "summary_c.json"),
    ]
    _write_status(run_root, "SUMMARIZED", {"summaries": paths})
    return run_root


def advance_to_verified(run_root: Path) -> Path:
    advance_to_summarized(run_root)
    summary_paths = [
        "30_summarization/summary_a.json",
        "30_summarization/summary_b.json",
        "30_summarization/summary_c.json",
    ]
    report = {
        "status": "pass",
        "fact_count": len(SAMPLE_FACTS),
        "pass_threshold": 0.75,
        "retries_used": 0,
        "summary_results": [
            {"index": i, "summary_id": f"SUM_{s.upper()}_{SOURCE_SHA[:8]}",
             "model_slot": s, "status": "pass", "coverage_score": 0.9}
            for i, s in enumerate(["summarizer_a", "summarizer_b", "summarizer_c"])
        ],
        "passing_summary_paths": summary_paths,
        "inputs": {"facts_path": "20_extraction/fact_list.json", "summary_paths": summary_paths},
        "warnings": [],
    }
    (run_root / "40_verification" / "verification_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    _write_status(
        run_root, "VERIFIED",
        {"summaries": summary_paths, "passing_summaries": summary_paths},
    )
    return run_root


def advance_to_contextualized(run_root: Path) -> Path:
    advance_to_verified(run_root)
    ctx = {
        "schema_version": "v1",
        "context_id": f"CTX_A_{SOURCE_SHA[:8]}",
        "model_slot": "contextualizer_a",
        "model_id": "claude-sonnet-4-6",
        "source_doc_sha256": SOURCE_SHA,
        "created_at": "2026-01-01T00:00:00+00:00",
        "sections": [{"lens": "historical_context", "content": "Context.", "sources": []}],
        "limitations": "",
        "warnings": [],
    }
    ctx_path = run_root / "50_contextual" / "contextual_a.json"
    ctx_path.write_text(json.dumps(ctx, indent=2), encoding="utf-8")
    _write_status(
        run_root, "CONTEXTUALIZED",
        {
            "summaries": ["30_summarization/summary_a.json",
                          "30_summarization/summary_b.json",
                          "30_summarization/summary_c.json"],
            "passing_summaries": ["30_summarization/summary_a.json",
                                  "30_summarization/summary_b.json",
                                  "30_summarization/summary_c.json"],
            "contextual_analyses": ["50_contextual/contextual_a.json"],
        },
    )
    return run_root


def advance_to_compiled(run_root: Path) -> Path:
    advance_to_contextualized(run_root)
    compiled = {
        "schema_version": "v1",
        "compiled_id": f"COMP_{SOURCE_SHA[:12]}",
        "source_doc_sha256": SOURCE_SHA,
        "created_at": "2026-01-01T00:00:00+00:00",
        "model_slot": "compiler",
        "model_id": "claude-sonnet-4-6",
        "executive_overview": "A concise overview.",
        "key_claims": [{"claim": "X", "fact_ids": ["F001"], "convergence": "all",
                         "source_summaries": ["summarizer_a"]}],
        "compiled_summary_text": "Full compiled summary.",
        "risks_and_limitations": "Some limitations.",
        "section_lineage": {},
        "inputs": {
            "passing_summary_paths": ["30_summarization/summary_a.json"],
            "contextual_analysis_paths": ["50_contextual/contextual_a.json"],
            "facts_path": "20_extraction/fact_list.json",
        },
        "warnings": [],
    }
    (run_root / "60_compilation" / "compiled_summary.json").write_text(
        json.dumps(compiled, indent=2), encoding="utf-8"
    )
    _write_status(
        run_root, "COMPILED",
        {
            "summaries": ["30_summarization/summary_a.json",
                          "30_summarization/summary_b.json",
                          "30_summarization/summary_c.json"],
            "passing_summaries": ["30_summarization/summary_a.json"],
            "contextual_analyses": ["50_contextual/contextual_a.json"],
        },
    )
    return run_root


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch LLMClient._call_anthropic so no real API calls are made."""
    monkeypatch.setattr(LLMClient, "_call_anthropic", _fake_call_anthropic)
