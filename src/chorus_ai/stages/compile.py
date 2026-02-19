from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from chorus_ai.core.config import load_run_config
from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.llm.client import LLMClient, load_prompt, parse_json_response
from chorus_ai.runs.status import require_state, set_state


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_status(run_root: Path) -> Dict[str, Any]:
    return _load_json(run_root / "00_meta" / "status.json")


def _build_user_prompt(
    summaries: List[Dict[str, Any]],
    facts: List[Dict[str, Any]],
    contextuals: List[Dict[str, Any]],
) -> str:
    parts: List[str] = []

    parts.append(f"FACT LIST ({len(facts)} facts):")
    for f in facts:
        parts.append(
            f'  {{"fact_id": "{f["fact_id"]}", "claim": "{f["claim"]}", "type": "{f["type"]}"}}'
        )

    parts.append("")
    parts.append(f"VERIFIED SUMMARIES ({len(summaries)} summaries):")
    for s in summaries:
        slot = s.get("model_slot", "unknown")
        parts.append(f"\n--- Summary from {slot} ---")
        parts.append(s.get("summary_text", ""))

    if contextuals:
        parts.append("")
        parts.append("CONTEXTUAL ANALYSES (external scholarly context):")
        for c in contextuals:
            slot = c.get("model_slot", "unknown")
            parts.append(f"\n--- Contextual analysis from {slot} ---")
            for section in c.get("sections", []):
                parts.append(f"[{section.get('lens', 'context')}]")
                parts.append(section.get("content", ""))
            limitations = c.get("limitations", "")
            if limitations:
                parts.append(f"Limitations: {limitations}")

    return "\n".join(parts)


def run_compile(run_dir: str) -> dict:
    """
    Stage 6: COMPILATION

    Preconditions:
      - run state must be CONTEXTUALIZED
      - passing summaries and fact list must exist

    Postconditions:
      - 60_compilation/compiled_summary.json written
      - run state becomes COMPILED

    Returns:
        {"ok": bool, "artifact": str|None, "warnings": list[str]}
    """
    run_root = Path(run_dir)
    require_state(run_root, "CONTEXTUALIZED")

    config = load_run_config(run_root)
    compiler_model = config.get("models", {}).get("compiler", "claude-sonnet-4-6")
    status = _read_status(run_root)

    # Load passing summaries (prefer verified passing; fall back to all summaries)
    passing_paths: List[str] = status.get(
        "passing_summaries", status.get("summaries", [])
    )
    if not passing_paths:
        return {
            "ok": False,
            "artifact": None,
            "warnings": ["No summaries available for compilation."],
        }

    summaries: List[Dict[str, Any]] = []
    for rel in passing_paths:
        p = (run_root / rel).resolve()
        if p.exists():
            obj = _load_json(p)
            if isinstance(obj, dict):
                summaries.append(obj)

    if not summaries:
        return {
            "ok": False,
            "artifact": None,
            "warnings": ["Could not load any summary files."],
        }

    # Load fact list
    facts_path = run_root / "20_extraction" / "fact_list.json"
    if not facts_path.exists():
        return {
            "ok": False,
            "artifact": None,
            "warnings": ["fact_list.json missing."],
        }
    facts_obj = _load_json(facts_path)
    facts = facts_obj.get("facts", []) if isinstance(facts_obj, dict) else []

    # Load contextual analyses (optional)
    contextuals: List[Dict[str, Any]] = []
    for rel in status.get("contextual_analyses", []):
        p = (run_root / rel).resolve()
        if p.exists():
            try:
                contextuals.append(_load_json(p))
            except Exception:
                pass

    # Read ingestion for source sha
    ingestion = _load_json(run_root / "10_ingestion" / "ingestion_record.json")
    source_sha = ingestion["source_doc_sha256"]

    llm = LLMClient(config)
    system_prompt = load_prompt("compile_system")
    user_content = _build_user_prompt(summaries, facts, contextuals)

    warnings: List[str] = []
    try:
        raw = llm.complete(
            model=compiler_model,
            system=system_prompt,
            user=user_content,
            max_tokens=8192,
        )
        parsed = parse_json_response(raw)
    except Exception as exc:
        raise ChorusFatalError(
            "LLM_CALL_FAILED",
            f"Compilation LLM call failed: {exc}",
            {"model": compiler_model},
        ) from exc

    compiled_id = f"COMP_{source_sha[:12]}"
    compiled: Dict[str, Any] = {
        "schema_version": "v1",
        "compiled_id": compiled_id,
        "source_doc_sha256": source_sha,
        "created_at": _utc_now(),
        "model_slot": "compiler",
        "model_id": compiler_model,
        "executive_overview": parsed.get("executive_overview", ""),
        "key_claims": parsed.get("key_claims", []),
        "compiled_summary_text": parsed.get("compiled_summary_text", ""),
        "risks_and_limitations": parsed.get("risks_and_limitations", ""),
        "section_lineage": parsed.get("section_lineage", {}),
        "inputs": {
            "passing_summary_paths": passing_paths,
            "contextual_analysis_paths": [
                rel for rel in status.get("contextual_analyses", [])
            ],
            "facts_path": "20_extraction/fact_list.json",
        },
        "warnings": parsed.get("warnings", []) + warnings,
    }

    out_dir = run_root / "60_compilation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "compiled_summary.json"
    _write_json(out_path, compiled)

    set_state(run_root, "COMPILED")

    return {"ok": True, "artifact": str(out_path), "warnings": compiled["warnings"]}
