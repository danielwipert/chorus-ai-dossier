from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chorus_ai.runs.status import require_state, set_state
from chorus_ai.stages.pdf_renderer import render_dossier_pdf


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_status(run_root: Path) -> Dict[str, Any]:
    return _load_json(run_root / "00_meta" / "status.json")


def _build_audit_trail(
    run_root: Path,
    ingestion: Dict[str, Any],
    fact_list: Dict[str, Any],
    verification: Optional[Dict[str, Any]],
    compiled: Dict[str, Any],
    status: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble the audit trail from all upstream artifacts."""
    return {
        "source_doc_sha256": ingestion.get("source_doc_sha256", ""),
        "page_count": ingestion.get("page_count", 0),
        "total_chars": ingestion.get("total_chars", 0),
        "fact_count": len(fact_list.get("facts", [])),
        "fact_set_id": fact_list.get("fact_set_id", ""),
        "summaries_generated": status.get("summaries", []),
        "passing_summaries": status.get("passing_summaries", []),
        "contextual_analyses": status.get("contextual_analyses", []),
        "verification": {
            "status": verification.get("status") if verification else "not_run",
            "pass_threshold": verification.get("pass_threshold") if verification else None,
            "retries_used": verification.get("retries_used", 0) if verification else 0,
            "summary_scores": [
                {
                    "summary_id": r.get("summary_id"),
                    "model_slot": r.get("model_slot"),
                    "coverage_score": r.get("coverage_score"),
                    "status": r.get("status"),
                }
                for r in (verification.get("summary_results", []) if verification else [])
            ],
        },
        "compilation": {
            "compiled_id": compiled.get("compiled_id"),
            "model_slot": compiled.get("model_slot"),
            "model_id": compiled.get("model_id"),
        },
        "run_state_history": status.get("history", []),
    }


def _build_contextual_analysis_section(
    run_root: Path, contextual_paths: List[str]
) -> str:
    """Assemble external contextual analyses into a readable section."""
    if not contextual_paths:
        return "[No contextual analysis was generated for this document.]"

    parts: List[str] = []
    for rel in contextual_paths:
        p = (run_root / rel).resolve()
        if not p.exists():
            continue
        try:
            ctx = _load_json(p)
        except Exception:
            continue

        slot = ctx.get("model_slot", "unknown")
        parts.append(f"=== Contextual Analysis ({slot}) ===")
        for section in ctx.get("sections", []):
            lens = section.get("lens", "context").replace("_", " ").title()
            content = section.get("content", "")
            sources = section.get("sources", [])
            parts.append(f"\n[{lens}]")
            parts.append(content)
            if sources:
                parts.append("Sources:")
                for src in sources:
                    parts.append(f"  - {src}")
        limitations = ctx.get("limitations", "")
        if limitations:
            parts.append(f"\nLimitations: {limitations}")

    return "\n\n".join(parts) if parts else "[Contextual analysis could not be loaded.]"


def run_export(run_dir: str) -> dict:
    """
    Stage 7: FINALIZATION (Export)

    Assembles the FinalDossier from all upstream artifacts.

    Required sections (per CLAUDE.md):
      1. Executive Overview
      2. Key Claims (fact-grounded, citing Fact IDs)
      3. Compiled Summary
      4. Contextual Analysis (labeled as external)
      5. Risks, Limitations, and Warnings
      6. Audit Trail

    Returns:
        {"ok": bool, "artifact": str|None, "warnings": list[str]}
    """
    run_root = Path(run_dir)
    require_state(run_root, "COMPILED")

    status = _read_status(run_root)

    # --- Load required artifacts ---
    compiled_path = run_root / "60_compilation" / "compiled_summary.json"
    if not compiled_path.exists():
        return {"ok": False, "artifact": None, "warnings": ["compiled_summary.json missing"]}

    compiled = _load_json(compiled_path)

    ingestion_path = run_root / "10_ingestion" / "ingestion_record.json"
    ingestion = _load_json(ingestion_path) if ingestion_path.exists() else {}

    fact_list_path = run_root / "20_extraction" / "fact_list.json"
    fact_list = _load_json(fact_list_path) if fact_list_path.exists() else {"facts": []}

    verification_path = run_root / "40_verification" / "verification_report.json"
    verification = _load_json(verification_path) if verification_path.exists() else None

    source_sha = ingestion.get("source_doc_sha256", compiled.get("source_doc_sha256", ""))
    contextual_paths: List[str] = status.get("contextual_analyses", [])

    # --- Assemble dossier sections ---
    executive_overview = compiled.get("executive_overview", "")
    if not executive_overview:
        executive_overview = "[Executive overview not available.]"

    key_claims = compiled.get("key_claims", [])

    compiled_summary_text = compiled.get("compiled_summary_text", "")
    if not compiled_summary_text:
        compiled_summary_text = "[Compiled summary not available.]"

    contextual_section = _build_contextual_analysis_section(run_root, contextual_paths)

    risks_and_limitations = compiled.get("risks_and_limitations", "")
    if not risks_and_limitations:
        risks_and_limitations = "[No risks or limitations were identified.]"

    # Append any pipeline warnings
    pipeline_warnings: List[str] = []
    pipeline_warnings.extend(compiled.get("warnings", []))
    if verification:
        pipeline_warnings.extend(verification.get("warnings", []))
    if not contextual_paths:
        pipeline_warnings.append(
            "No contextual analysis was generated; external context section is absent."
        )

    # Flag lowered verification threshold prominently
    _DEFAULT_THRESHOLD = 0.75
    _applied_threshold = verification.get("pass_threshold") if verification else None
    if _applied_threshold is not None and _applied_threshold < _DEFAULT_THRESHOLD:
        _threshold_notice = (
            f"VERIFICATION NOTICE: This dossier was produced using a reduced fact-coverage "
            f"threshold of {_applied_threshold} (standard is {_DEFAULT_THRESHOLD}). "
            f"One or more summaries may have lower grounding fidelity than a standard run. "
            f"Treat conclusions with additional scrutiny."
        )
        pipeline_warnings.insert(0, _threshold_notice)
        risks_and_limitations = _threshold_notice + "\n\n" + risks_and_limitations

    audit_trail = _build_audit_trail(
        run_root, ingestion, fact_list, verification, compiled, status
    )

    # --- Build final dossier ---
    dossier_id = f"DOS_{source_sha[:12]}"
    export_path_rel = "70_export/final_dossier.json"

    final_dossier: Dict[str, Any] = {
        "schema_version": "v1",
        "dossier_id": dossier_id,
        "source_doc_sha256": source_sha,
        "created_at": _utc_now(),
        "sections": {
            "executive_overview": executive_overview,
            "key_claims": key_claims,
            "compiled_summary": compiled_summary_text,
            "contextual_analysis": contextual_section,
            "risks_and_limitations": risks_and_limitations,
            "audit_trail": audit_trail,
        },
        "export_paths": [export_path_rel],
        "warnings": pipeline_warnings,
        "run_status": "complete",
    }

    out_dir = run_root / "70_export"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "final_dossier.json"
    _write_json(out_path, final_dossier)

    # Render PDF
    pdf_path = out_dir / "final_dossier.pdf"
    pdf_warnings: List[str] = []
    try:
        render_dossier_pdf(final_dossier, pdf_path)
        final_dossier["export_paths"].append("70_export/final_dossier.pdf")
        # Re-write JSON with updated export_paths
        _write_json(out_path, final_dossier)
    except Exception as exc:
        pdf_warnings.append(f"PDF rendering failed: {exc}")

    set_state(run_root, "FINALIZED")

    return {
        "ok": True,
        "artifact": str(out_path),
        "pdf": str(pdf_path) if pdf_path.exists() else None,
        "warnings": pipeline_warnings + pdf_warnings,
    }
