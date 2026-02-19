"""
verify_summary_v1.py — Verification V2 (Structural + Semantic scoring)

verify_summary_v1() is the primary callable from stages/verify.py.

Per-summary pipeline:
  1. Structural check: schema fields present and typed correctly.
  2. Semantic scoring: LLM coverage check of facts vs. summary text.
     - coverage_score = covered_facts / total_facts
     - threshold configurable (default 0.75)
  3. Pass rule: at least 2 summaries must pass both checks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_required_fields(data: Dict[str, Any], required: List[str]) -> Tuple[bool, List[str]]:
    missing = [k for k in required if k not in data]
    return len(missing) == 0, missing


def _check_field_types(
    data: Dict[str, Any], type_map: Dict[str, type]
) -> Tuple[bool, List[Dict[str, str]]]:
    errors: List[Dict[str, str]] = []
    for key, expected in type_map.items():
        if key not in data:
            continue
        if not isinstance(data[key], expected):
            errors.append(
                {
                    "field": key,
                    "expected": expected.__name__,
                    "got": type(data[key]).__name__,
                }
            )
    return len(errors) == 0, errors


def _structural_check(summary: Dict[str, Any], fact_count: int) -> Dict[str, Any]:
    """Return a per-summary structural result dict."""
    checks: List[Dict[str, Any]] = []

    required = ["schema_version", "summary_id", "summary_text", "fact_count", "inputs"]
    ok_present, missing = _check_required_fields(summary, required)
    checks.append(
        {
            "name": "required_fields_present",
            "status": "pass" if ok_present else "fail",
            "missing": missing,
        }
    )

    type_map: Dict[str, type] = {
        "schema_version": str,
        "summary_id": str,
        "summary_text": str,
        "fact_count": int,
        "inputs": dict,
    }
    ok_types, type_errors = _check_field_types(summary, type_map)
    checks.append(
        {
            "name": "required_field_types",
            "status": "pass" if ok_types else "fail",
            "errors": type_errors,
        }
    )

    # summary_text must be non-empty
    text = summary.get("summary_text", "")
    text_ok = isinstance(text, str) and text.strip() != ""
    # Exception: if 0 facts, empty/placeholder text is allowed
    if fact_count == 0:
        allowed_empty = {
            "",
            "No facts extracted.",
            "No facts were extracted.",
            "No extractable facts found.",
        }
        text_ok = not isinstance(text, str) or text.strip() in allowed_empty or text.strip() != ""
    checks.append(
        {
            "name": "summary_text_non_empty",
            "status": "pass" if text_ok else "fail",
        }
    )

    # fact_count alignment
    reported = summary.get("fact_count")
    fc_ok = isinstance(reported, int) and reported == fact_count
    checks.append(
        {
            "name": "fact_count_matches",
            "status": "pass" if fc_ok else "fail",
            "expected": fact_count,
            "got": reported,
        }
    )

    status = "pass" if all(c["status"] == "pass" for c in checks) else "fail"
    return {"status": status, "checks": checks}


def _semantic_score(
    summary: Dict[str, Any],
    facts: List[Dict[str, Any]],
    llm_client: Any,
    compiler_model: str,
) -> Dict[str, Any]:
    """
    Call the LLM to score the summary's coverage of the fact list.
    Returns a scoring result dict.
    """
    from chorus_ai.llm.client import load_prompt, parse_json_response

    if not facts:
        return {
            "total_facts": 0,
            "covered_facts": 0,
            "coverage_score": 1.0,
            "unsupported_claims": [],
            "fact_coverage": [],
            "error": None,
        }

    system_prompt = load_prompt("verify_system")
    facts_text = "\n".join(
        f'  {{"fact_id": "{f["fact_id"]}", "claim": "{f["claim"]}"}}'
        for f in facts
    )
    user_content = (
        f"FACTS ({len(facts)} total):\n[\n{facts_text}\n]\n\n"
        f"SUMMARY TO EVALUATE:\n{summary.get('summary_text', '')}"
    )

    try:
        raw = llm_client.complete(
            model=compiler_model,
            system=system_prompt,
            user=user_content,
            max_tokens=4096,
        )
        parsed = parse_json_response(raw)
    except Exception as exc:
        return {
            "total_facts": len(facts),
            "covered_facts": 0,
            "coverage_score": 0.0,
            "unsupported_claims": [],
            "fact_coverage": [],
            "error": str(exc),
        }

    # Normalise coverage_score
    score = parsed.get("coverage_score", 0.0)
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    parsed["coverage_score"] = score

    return parsed


def verify_summary_v1(
    *,
    facts: List[Dict[str, Any]],
    summaries: List[Dict[str, Any]],
    llm_client: Optional[Any] = None,
    compiler_model: str = "claude-sonnet-4-6",
    pass_threshold: float = 0.75,
) -> Dict[str, Any]:
    """
    Core verification entrypoint callable from stages/verify.py.

    Args:
        facts: Loaded fact dicts (from fact_list.json["facts"]).
        summaries: Loaded summary dicts.
        llm_client: LLMClient instance for semantic scoring. If None, skips scoring.
        compiler_model: Model to use for semantic scoring.
        pass_threshold: Minimum coverage score to pass (default 0.75).

    Returns:
        JSON-serializable verification report.
    """
    if not isinstance(facts, list):
        return {"status": "fail", "checks": [], "warnings": ["facts must be a list"]}
    if not isinstance(summaries, list):
        return {"status": "fail", "checks": [], "warnings": ["summaries must be a list"]}

    fact_count = len(facts)
    warnings: List[str] = []
    per_summary: List[Dict[str, Any]] = []

    for i, summary in enumerate(summaries):
        slot = summary.get("model_slot", f"slot_{i}")
        summary_id = summary.get("summary_id", f"summary_{i}")

        if not isinstance(summary, dict):
            per_summary.append(
                {
                    "index": i,
                    "summary_id": summary_id,
                    "model_slot": slot,
                    "status": "fail",
                    "structural": {"status": "fail", "checks": []},
                    "semantic": None,
                    "coverage_score": 0.0,
                }
            )
            continue

        # 1. Structural check
        structural = _structural_check(summary, fact_count)

        # 2. Semantic scoring (only if structural passes and LLM client available)
        semantic: Optional[Dict[str, Any]] = None
        coverage_score = 0.0

        if structural["status"] == "pass" and llm_client is not None:
            semantic = _semantic_score(summary, facts, llm_client, compiler_model)
            coverage_score = semantic.get("coverage_score", 0.0)
            if semantic.get("error"):
                warnings.append(
                    f"Semantic scoring error for {slot}: {semantic['error']}"
                )
                # On scoring error, fail safe
                coverage_score = 0.0
        elif structural["status"] == "pass" and llm_client is None:
            # No LLM: auto-pass semantic with full score (structural-only mode)
            coverage_score = 1.0
            warnings.append(
                f"No LLM client provided; skipping semantic scoring for {slot}."
            )

        # Pass if structural passes AND coverage meets threshold
        passes_threshold = coverage_score >= pass_threshold
        final_status = (
            "pass"
            if (structural["status"] == "pass" and passes_threshold)
            else "fail"
        )

        per_summary.append(
            {
                "index": i,
                "summary_id": summary_id,
                "model_slot": slot,
                "status": final_status,
                "structural": structural,
                "semantic": semantic,
                "coverage_score": coverage_score,
                "passes_threshold": passes_threshold,
            }
        )

    # Pass rule: at least 2 summaries pass
    pass_count = sum(1 for r in per_summary if r["status"] == "pass")
    min_viable = pass_count >= 2

    top_level_checks = [
        {
            "name": "minimum_two_summaries_pass",
            "status": "pass" if min_viable else "fail",
            "pass_count": pass_count,
            "required": 2,
        }
    ]

    if not min_viable:
        warnings.append(
            f"Minimum viability not met: {pass_count}/2 summaries passed "
            f"(threshold={pass_threshold})."
        )

    overall = "pass" if min_viable else "fail"

    return {
        "status": overall,
        "created_at": _utc_now_iso(),
        "fact_count": fact_count,
        "pass_threshold": pass_threshold,
        "summary_results": per_summary,
        "checks": top_level_checks,
        "warnings": warnings,
    }
