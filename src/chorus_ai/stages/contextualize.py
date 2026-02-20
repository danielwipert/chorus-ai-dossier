from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chorus_ai.artifacts.io import read_json
from chorus_ai.core.config import load_run_config
from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.llm.client import LLMClient, load_prompt, parse_json_response
from chorus_ai.runs.status import require_state, set_state

_CONTEXT_SLOTS = ["contextualizer_a"]
_SLOT_FILENAMES = {
    "contextualizer_a": "contextual_a.json",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_status(run_root: Path) -> Dict[str, Any]:
    path = run_root / "00_meta" / "status.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_status(run_root: Path, status: Dict[str, Any]) -> None:
    path = run_root / "00_meta" / "status.json"
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_user_prompt(passing_summaries: List[Dict[str, Any]]) -> str:
    parts = ["Provide contextual analysis for the following document summaries.\n"]
    for i, s in enumerate(passing_summaries):
        slot = s.get("model_slot", f"model_{i}")
        text = s.get("summary_text", "")
        parts.append(f"=== Summary from {slot} ===\n{text}\n")
    return "\n".join(parts)


def _run_one_context_slot(
    run_root: Path,
    slot: str,
    llm: LLMClient,
    config: Dict[str, Any],
    source_sha: str,
    passing_summaries: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Generate contextual analysis for one model slot.
    Returns the relative path to the written artifact, or None on failure.
    Failure is NON-FATAL per CLAUDE.md.
    """
    model = config.get("models", {}).get(slot, "claude-sonnet-4-6")
    out_dir = run_root / "50_contextual"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = _SLOT_FILENAMES.get(slot, f"{slot}.json")
    out_path = out_dir / filename

    system_prompt = load_prompt("contextualize_system")
    user_content = _build_user_prompt(passing_summaries)

    try:
        raw = llm.complete(
            model=model,
            system=system_prompt,
            user=user_content,
            max_tokens=4096,
        )
        parsed = parse_json_response(raw)
    except Exception as exc:
        return None  # Non-fatal

    context_id = f"CTX_{slot.upper()}_{source_sha[:8]}"
    artifact: Dict[str, Any] = {
        "schema_version": "v1",
        "context_id": context_id,
        "model_slot": slot,
        "model_id": model,
        "source_doc_sha256": source_sha,
        "created_at": _utc_now(),
        "sections": parsed.get("sections", []),
        "limitations": parsed.get("limitations", ""),
        "warnings": parsed.get("warnings", []),
    }

    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out_path.relative_to(run_root))


def run_contextualize(run_root: Path) -> dict:
    """
    Stage 5: CONTEXTUAL ANALYSIS

    NON-FATAL: if the context model fails, the stage notes the gap and continues.

    Preconditions:
      - run state must be VERIFIED
      - 40_verification/verification_report.json must exist

    Postconditions:
      - 50_contextual/contextual_a.json written (if model succeeds)
      - status.json["contextual_analyses"] updated
      - run state becomes CONTEXTUALIZED

    Returns:
        {"ok": True, "artifact": list[str]|None, "warnings": list[str]}
    """
    require_state(run_root, "VERIFIED")

    config = load_run_config(run_root)
    status = _read_status(run_root)

    # Load passing summaries from verification report
    verification_path = run_root / "40_verification" / "verification_report.json"
    if not verification_path.exists():
        # Non-fatal: no verification report, use all summaries
        passing_paths = status.get("summaries", [])
    else:
        verification = _load_json(verification_path)
        passing_paths = verification.get("passing_summary_paths", status.get("summaries", []))

    if not passing_paths:
        passing_paths = status.get("summaries", [])

    # Load passing summary content
    passing_summaries: List[Dict[str, Any]] = []
    for rel in passing_paths:
        p = (run_root / rel).resolve()
        if p.exists():
            try:
                passing_summaries.append(_load_json(p))
            except Exception:
                pass

    if not passing_summaries:
        # Non-fatal: no summaries to contextualize
        warnings = ["No passing summaries available for contextual analysis; skipping."]
        set_state(run_root, "CONTEXTUALIZED")
        status["contextual_analyses"] = []
        _write_status(run_root, status)
        return {"ok": True, "artifact": None, "warnings": warnings}

    ingestion = read_json(run_root / "10_ingestion" / "ingestion_record.json")
    source_sha = ingestion["source_doc_sha256"]

    llm = LLMClient(config)
    warnings: List[str] = []
    written_paths: List[str] = []

    for slot in _CONTEXT_SLOTS:
        result = _run_one_context_slot(
            run_root=run_root,
            slot=slot,
            llm=llm,
            config=config,
            source_sha=source_sha,
            passing_summaries=passing_summaries,
        )
        if result is not None:
            written_paths.append(result)
        else:
            warnings.append(
                f"Contextual analysis for slot '{slot}' failed; gap noted."
            )

    if not written_paths:
        warnings.append(
            "All contextual analysis models failed. "
            "Proceeding without external context (noted in final dossier)."
        )

    # Update status
    status = _read_status(run_root)
    status["contextual_analyses"] = written_paths
    _write_status(run_root, status)

    set_state(run_root, "CONTEXTUALIZED")

    return {
        "ok": True,
        "artifact": written_paths if written_paths else None,
        "warnings": warnings,
    }
