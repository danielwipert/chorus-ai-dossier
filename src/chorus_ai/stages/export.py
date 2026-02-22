from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chorus_ai.core.config import load_run_config
from chorus_ai.runs.status import require_state, set_state
from chorus_ai.stages.pdf_renderer import render_dossier_pdf


def _extract_pdf_metadata(run_root: Path) -> Dict[str, str]:
    """
    Attempt to read title, author, and subject from PDF metadata.
    Returns whatever is available; missing fields are omitted.
    """
    pdf_path = run_root / "00_input" / "input.pdf"
    if not pdf_path.exists():
        return {}
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            meta = pdf.metadata or {}
        result: Dict[str, str] = {}
        if meta.get("Title"):
            result["title"] = str(meta["Title"]).strip()
        if meta.get("Author"):
            result["author"] = str(meta["Author"]).strip()
        if meta.get("Subject"):
            result["subject"] = str(meta["Subject"]).strip()
        return result
    except Exception:
        return {}


_SLOT_DISPLAY = {
    "summarizer_a":     "Summarizer A",
    "summarizer_b":     "Summarizer B",
    "summarizer_c":     "Summarizer C",
    "fact_finder":      "Fact Finder",
    "compiler":         "Compiler / Verifier",
    "contextualizer_a": "Contextualizer A",
    "contextualizer_b": "Contextualizer B",
}

_SLOT_DESCRIPTION = {
    "summarizer_a":     "Generates an independent summary of the source document (pass 1 of 3)",
    "summarizer_b":     "Generates an independent summary of the source document (pass 2 of 3)",
    "summarizer_c":     "Generates an independent summary of the source document (pass 3 of 3)",
    "fact_finder":      "Extracts and catalogues all discrete factual claims directly from the source document",
    "compiler":         "Verifies each summary against the fact list and synthesizes the final compiled report",
    "contextualizer_a": "Provides external scholarly context, placing the work in broader academic perspective",
    "contextualizer_b": "Provides a second independent perspective on external scholarly context",
}


def _short_model_id(model_id: str) -> str:
    """Strip provider prefix and return just the model name portion."""
    mid = model_id.replace("together:", "")
    return mid.split("/")[-1] if "/" in mid else mid


def _build_model_roster(config: Dict[str, Any]) -> List[Dict[str, str]]:
    """Build ordered list of models used in this run with roles and descriptions."""
    models_cfg = config.get("models", {})
    roster: List[Dict[str, str]] = []
    for slot in ("summarizer_a", "summarizer_b", "summarizer_c",
                 "fact_finder", "compiler", "contextualizer_a", "contextualizer_b"):
        model_id = models_cfg.get(slot, "")
        if model_id:
            roster.append({
                "slot": slot,
                "role": _SLOT_DISPLAY.get(slot, slot),
                "model_id": model_id,
                "model_short": _short_model_id(model_id),
                "description": _SLOT_DESCRIPTION.get(slot, ""),
            })
    return roster


def _build_section_attributions(roster: List[Dict[str, str]]) -> Dict[str, str]:
    """
    Build a per-section attribution string showing which model(s) produced each section.
    Keys are section numbers as strings ("1"–"5").
    """
    by_slot: Dict[str, str] = {r["slot"]: r for r in roster}  # type: ignore[assignment]

    def _fmt(slot: str) -> str:
        r = by_slot.get(slot)
        if not r:
            return ""
        return f"{r['role']}: {r['model_short']}"

    attributions: Dict[str, str] = {}

    # 01 Executive Overview — compiler
    if "compiler" in by_slot:
        attributions["1"] = _fmt("compiler")

    # 02 Compiled Summary — summarizers (source) + compiler (synthesis)
    summarizer_parts = [_fmt(s) for s in ("summarizer_a", "summarizer_b", "summarizer_c") if s in by_slot]
    compiler_part = _fmt("compiler") if "compiler" in by_slot else ""
    parts_02 = summarizer_parts + ([compiler_part] if compiler_part else [])
    if parts_02:
        attributions["2"] = "  \u00b7  ".join(parts_02)

    # 03 Contextual Analysis — contextualizers
    ctx_parts = [_fmt(s) for s in ("contextualizer_a", "contextualizer_b") if s in by_slot]
    if ctx_parts:
        attributions["3"] = "  \u00b7  ".join(ctx_parts)

    # 04 Risks, Limitations — compiler
    if "compiler" in by_slot:
        attributions["4"] = _fmt("compiler")

    # 05 Verification Receipt — fact_finder + compiler
    receipt_parts = [_fmt(s) for s in ("fact_finder", "compiler") if s in by_slot]
    if receipt_parts:
        attributions["5"] = "  \u00b7  ".join(receipt_parts)

    return attributions


def _build_process_description(
    verification: Optional[Dict[str, Any]],
    audit: Dict[str, Any],
) -> str:
    """
    Generate a plain-English description of the pipeline process for the cover page.
    Written for a general audience — no jargon.
    """
    n_summaries = len(audit.get("summaries_generated", []))
    n_passing = len(audit.get("passing_summaries", []))
    n_contextual = len(audit.get("contextual_analyses", []))
    fact_count = audit.get("fact_count", 0)

    summary_clause = (
        f"three separate AI models" if n_summaries == 3
        else f"{n_summaries} separate AI models"
    )
    passing_clause = (
        f"All {n_passing} summaries" if n_passing == n_summaries
        else f"{n_passing} of {n_summaries} summaries"
    )
    context_clause = (
        f"Two independent models then added external scholarly context, "
        "drawing on published sources to place the work in broader perspective. "
        if n_contextual >= 2
        else (
            "One model added external scholarly context. "
            if n_contextual == 1
            else ""
        )
    )

    return (
        f"This report was produced by the Chorus AI 7-stage verification pipeline. "
        f"The source document was independently summarized by {summary_clause} — "
        f"each working without knowledge of the others' outputs. "
        f"A dedicated fact-extraction model then catalogued {fact_count} discrete "
        f"claims directly from the original text, creating a locked fact list. "
        f"A verification model checked each summary against that fact list for contradictions; "
        f"{passing_clause} passed the hallucination check and advanced. "
        f"A compiler model synthesized the passing summaries into a single coherent "
        f"analysis, retaining only claims corroborated by multiple sources. "
        f"{context_clause}"
        f"Every key claim in this report traces back to a specific fact extracted "
        f"from the source document."
    )


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
    dossier_id: str = "",
) -> Dict[str, Any]:
    """Assemble the audit trail from all upstream artifacts."""
    return {
        "dossier_id": dossier_id,
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
            "max_contradiction_score": verification.get("max_contradiction_score") if verification else None,
            "retries_used": verification.get("retries_used", 0) if verification else 0,
            "summary_scores": [
                {
                    "summary_id": r.get("summary_id"),
                    "model_slot": r.get("model_slot"),
                    "contradiction_score": r.get("contradiction_score"),
                    "coverage_score": r.get("coverage_score"),
                    "passes_contradiction_check": r.get("passes_contradiction_check"),
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

    config = load_run_config(run_root)
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

    # --- Build final dossier ---
    dossier_id = f"DOS_{source_sha[:12]}"
    export_path_rel = "70_export/final_dossier.json"

    audit_trail = _build_audit_trail(
        run_root, ingestion, fact_list, verification, compiled, status,
        dossier_id=dossier_id,
    )

    document_meta = _extract_pdf_metadata(run_root)
    process_description = _build_process_description(verification, audit_trail)
    model_roster = _build_model_roster(config)
    section_attributions = _build_section_attributions(model_roster)

    final_dossier: Dict[str, Any] = {
        "schema_version": "v1",
        "dossier_id": dossier_id,
        "source_doc_sha256": source_sha,
        "created_at": _utc_now(),
        "document_meta": document_meta,
        "process_description": process_description,
        "model_roster": model_roster,
        "section_attributions": section_attributions,
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
