from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chorus_ai.artifacts.io import read_json, write_json
from chorus_ai.core.config import load_run_config
from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.llm.client import LLMClient, load_prompt
from chorus_ai.runs.status import require_state, set_state

_SLOTS = ["summarizer_a", "summarizer_b", "summarizer_c"]
_SLOT_FILENAMES = {
    "summarizer_a": "summary_a.json",
    "summarizer_b": "summary_b.json",
    "summarizer_c": "summary_c.json",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_status(run_root: Path) -> Dict[str, Any]:
    path = run_root / "00_meta" / "status.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_status(run_root: Path, status: Dict[str, Any]) -> None:
    path = run_root / "00_meta" / "status.json"
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")


def generate_summary_for_slot(
    run_root: Path,
    slot: str,
    llm: LLMClient,
    config: Dict[str, Any],
    document_text: str,
    source_sha: str,
    fact_count: int,
    facts_rel_path: str,
    force: bool = False,
) -> str:
    """
    Generate and write a single summary for a model slot.

    Returns the relative path (from run_root) to the written summary file.
    This function is also called by the verification retry loop.
    """
    model = config.get("models", {}).get(slot, "claude-haiku-4-5-20251001")
    out_dir = run_root / "30_summarization"
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = _SLOT_FILENAMES.get(slot, f"summary_{slot}.json")
    out_path = out_dir / filename

    if out_path.exists() and not force:
        raise ChorusFatalError(
            "STAGE_ALREADY_DONE",
            f"Summary for slot '{slot}' already exists; use force=True to regenerate",
            {"path": str(out_path)},
        )

    system_prompt = load_prompt("summarize_system")

    try:
        summary_text = llm.complete(
            model=model,
            system=system_prompt,
            user=f"Summarize the following document:\n\n{document_text}",
            max_tokens=4096,
        )
    except Exception as exc:
        raise ChorusFatalError(
            "LLM_CALL_FAILED",
            f"Summarization LLM call failed for slot '{slot}': {exc}",
            {"model": model, "slot": slot},
        ) from exc

    summary_id = f"SUM_{slot.upper()}_{source_sha[:8]}"
    summary: Dict[str, Any] = {
        "schema_version": "v1",
        "summary_id": summary_id,
        "model_slot": slot,
        "model_id": model,
        "source_doc_sha256": source_sha,
        "created_at": _utc_now(),
        "summary_text": summary_text.strip(),
        "fact_count": fact_count,
        "inputs": {
            "facts_path": facts_rel_path,
            "text_path": "10_ingestion/document_text.txt",
        },
    }

    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out_path.relative_to(run_root))


def run_summarize(
    run_root: str,
    force: bool = False,
    slots: Optional[List[str]] = None,
) -> List[str]:
    """
    Stage 3: SUMMARIZATION

    Generates three independent summaries (A, B, C) using different model slots.
    Each model sees only the document text — summaries are independent.

    Args:
        run_root: Path to the run folder (string for backward-compat with CLI).
        force: Overwrite existing summary files.
        slots: If provided, only regenerate summaries for these slots (used by retry loop).

    Returns:
        List of relative paths to all current summary files.

    Postconditions:
      - 30_summarization/summary_{a,b,c}.json written
      - status.json["summaries"] updated with all current summary paths
      - run state becomes SUMMARIZED (only when all slots generated fresh)
    """
    run_path = Path(run_root)
    slots_to_generate = slots if slots is not None else _SLOTS

    # State check only on fresh full runs (not retries from verify)
    if slots is None:
        require_state(run_path, "EXTRACTED")

    ingestion_path = run_path / "10_ingestion" / "ingestion_record.json"
    ingestion = read_json(ingestion_path)
    source_sha = ingestion["source_doc_sha256"]

    text_path = run_path / "10_ingestion" / "document_text.txt"
    if not text_path.exists():
        raise ChorusFatalError(
            "TEXT_MISSING",
            "document_text.txt not found; re-run ingestion",
            {"path": str(text_path)},
        )
    document_text = text_path.read_text(encoding="utf-8")

    fact_list_path = run_path / "20_extraction" / "fact_list.json"
    fact_list = read_json(fact_list_path)
    fact_count = len(fact_list.get("facts", []))
    facts_rel_path = "20_extraction/fact_list.json"

    config = load_run_config(run_path)
    llm = LLMClient(config)

    # On a full run, discover existing summary paths from status.json
    status = _read_status(run_path)
    existing_summaries: List[str] = status.get("summaries", [])

    # Build a dict of slot → current relative path
    slot_to_path: Dict[str, str] = {}
    for rel in existing_summaries:
        for slot, fname in _SLOT_FILENAMES.items():
            if rel.endswith(fname):
                slot_to_path[slot] = rel

    # Generate (or re-generate) the requested slots
    for slot in slots_to_generate:
        rel_path = generate_summary_for_slot(
            run_root=run_path,
            slot=slot,
            llm=llm,
            config=config,
            document_text=document_text,
            source_sha=source_sha,
            fact_count=fact_count,
            facts_rel_path=facts_rel_path,
            force=force or (slots is not None),  # always force on retry
        )
        slot_to_path[slot] = rel_path

    # Rebuild ordered list of all summary paths (A, B, C order)
    all_paths = [slot_to_path[s] for s in _SLOTS if s in slot_to_path]

    # Update status.json
    status["summaries"] = all_paths
    _write_status(run_path, status)

    # Advance state only on a full initial run
    if slots is None:
        set_state(run_path, "SUMMARIZED")

    return all_paths
