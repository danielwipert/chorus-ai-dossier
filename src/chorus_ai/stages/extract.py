from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from chorus_ai.artifacts.io import read_json, write_json
from chorus_ai.artifacts.validate import validate_artifact
from chorus_ai.core.config import load_run_config
from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.llm.client import LLMClient, load_prompt, parse_json_response
from chorus_ai.runs.guards import require_missing
from chorus_ai.runs.status import require_state, set_state


def _validate_facts(facts: List[Any]) -> List[Dict[str, Any]]:
    """Validate and normalise fact objects from the LLM response."""
    valid: List[Dict[str, Any]] = []
    required_keys = {"fact_id", "claim", "type", "source_location", "confidence"}
    valid_types = {
        "author_position", "empirical_claim", "definition", "citation", "conclusion"
    }

    for i, fact in enumerate(facts):
        if not isinstance(fact, dict):
            continue
        # Fill missing keys with defaults rather than dropping the fact
        fact_id = str(fact.get("fact_id", f"F{i + 1:03d}"))
        claim = str(fact.get("claim", "")).strip()
        if not claim:
            continue

        ftype = str(fact.get("type", "empirical_claim"))
        if ftype not in valid_types:
            ftype = "empirical_claim"

        loc = fact.get("source_location")
        if not isinstance(loc, dict):
            loc = {"page": 1, "paragraph": 1}

        confidence = fact.get("confidence", 0.5)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        valid.append(
            {
                "fact_id": fact_id,
                "claim": claim,
                "type": ftype,
                "source_location": {
                    "page": int(loc.get("page", 1)),
                    "paragraph": int(loc.get("paragraph", 1)),
                },
                "confidence": confidence,
            }
        )

    return valid


def run_extract(run_root: Path, force: bool = False) -> None:
    """
    Stage 2: EXTRACTION (Fact Finder)

    Preconditions:
      - run state must be INGESTED
      - 10_ingestion/ingestion_record.json and document_text.txt must exist

    Postconditions:
      - 20_extraction/fact_list.json written and validated
      - run state becomes EXTRACTED

    Uses Model 4 (fact_finder) — cheap, extractive-only.
    """
    require_state(run_root, "INGESTED")

    ingestion_path = run_root / "10_ingestion" / "ingestion_record.json"
    text_path = run_root / "10_ingestion" / "document_text.txt"
    out_path = run_root / "20_extraction" / "fact_list.json"

    require_missing(out_path, force=force)

    ingestion = read_json(ingestion_path)
    source_sha = ingestion["source_doc_sha256"]

    if not text_path.exists():
        raise ChorusFatalError(
            "TEXT_MISSING",
            "document_text.txt not found; re-run ingestion",
            {"path": str(text_path)},
        )
    document_text = text_path.read_text(encoding="utf-8")

    config = load_run_config(run_root)
    model = config.get("models", {}).get("fact_finder", "claude-haiku-4-5-20251001")

    llm = LLMClient(config)
    system_prompt = load_prompt("extract_system")

    try:
        raw = llm.complete(
            model=model,
            system=system_prompt,
            user=f"Extract all facts from the following document:\n\n{document_text}",
            max_tokens=8192,
        )
    except Exception as exc:
        raise ChorusFatalError(
            "LLM_CALL_FAILED",
            f"Fact extraction LLM call failed: {exc}",
            {"model": model},
        ) from exc

    try:
        parsed = parse_json_response(raw)
    except ValueError as exc:
        raise ChorusFatalError(
            "LLM_BAD_JSON",
            f"Fact extractor returned non-JSON output: {exc}",
            {"model": model, "raw_preview": raw[:300]},
        ) from exc

    raw_facts = parsed.get("facts", []) if isinstance(parsed, dict) else []
    facts = _validate_facts(raw_facts)

    fact_set_id = f"FACTSET_{source_sha[:12]}"
    fact_list: Dict[str, Any] = {
        "schema_version": "v1",
        "source_doc_sha256": source_sha,
        "fact_set_id": fact_set_id,
        "facts": facts,
    }

    validate_artifact("fact_list", fact_list)
    write_json(out_path, fact_list, force=force)

    set_state(run_root, "EXTRACTED")
