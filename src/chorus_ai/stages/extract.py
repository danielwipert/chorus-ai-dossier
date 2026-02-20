from __future__ import annotations

import re
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


_PAGES_PER_CHUNK_DEFAULT = 3


def _split_into_page_chunks(document_text: str, pages_per_chunk: int) -> List[str]:
    """Split document text into chunks of N pages using [PAGE N] markers."""
    # Split on [PAGE N] markers, keeping the markers
    parts = re.split(r"(\[PAGE \d+\])", document_text)

    # Pair each marker with the text that follows it
    pages: List[str] = []
    i = 0
    while i < len(parts):
        if re.match(r"\[PAGE \d+\]", parts[i]):
            header = parts[i]
            body = parts[i + 1] if i + 1 < len(parts) else ""
            pages.append(header + body)
            i += 2
        else:
            i += 1

    if not pages:
        # No [PAGE N] markers — treat whole document as one chunk
        return [document_text]

    # Group pages into chunks of pages_per_chunk
    chunks: List[str] = []
    for start in range(0, len(pages), pages_per_chunk):
        chunk = "\n".join(pages[start : start + pages_per_chunk]).strip()
        chunks.append(chunk)

    return chunks


def _extract_facts_from_chunk(
    llm: LLMClient,
    model: str,
    system_prompt: str,
    chunk_text: str,
    chunk_index: int,
) -> List[Dict[str, Any]]:
    """Run the extraction LLM call on a single chunk and return raw fact dicts."""
    try:
        raw = llm.complete(
            model=model,
            system=system_prompt,
            user=f"Extract all facts from the following document:\n\n{chunk_text}",
            max_tokens=8192,
        )
    except Exception as exc:
        raise ChorusFatalError(
            "LLM_CALL_FAILED",
            f"Fact extraction LLM call failed on chunk {chunk_index}: {exc}",
            {"model": model, "chunk_index": chunk_index},
        ) from exc

    try:
        parsed = parse_json_response(raw)
    except ValueError as exc:
        raise ChorusFatalError(
            "LLM_BAD_JSON",
            f"Fact extractor returned non-JSON output on chunk {chunk_index}: {exc}",
            {"model": model, "chunk_index": chunk_index, "raw_preview": raw[:300]},
        ) from exc

    return parsed.get("facts", []) if isinstance(parsed, dict) else []


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
    pages_per_chunk = config.get("extraction", {}).get(
        "pages_per_chunk", _PAGES_PER_CHUNK_DEFAULT
    )

    llm = LLMClient(config)
    system_prompt = load_prompt("extract_system")

    chunks = _split_into_page_chunks(document_text, pages_per_chunk)

    all_raw_facts: List[Dict[str, Any]] = []
    for i, chunk in enumerate(chunks):
        chunk_facts = _extract_facts_from_chunk(llm, model, system_prompt, chunk, i)
        all_raw_facts.extend(chunk_facts)

    facts = _validate_facts(all_raw_facts)

    # Renumber fact IDs globally so they are unique across chunks
    for idx, fact in enumerate(facts):
        fact["fact_id"] = f"F{idx + 1:03d}"

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
