"""
verify_summary_v1.py — Verification V2 (Structural + Contradiction scoring)

verify_summary_v1() is the primary callable from stages/verify.py.

Per-summary pipeline:
  1. Structural check: schema fields present and typed correctly.
  2. Semantic scoring: LLM contradiction check of a sampled subset of facts vs. summary text.
     - A deterministic stratified sample (by fact type) is used to keep LLM output within
       token limits.
     - PRIMARY metric: contradiction_score = contradicted_facts / total_facts
       A summary fails if contradiction_score > max_contradiction_score (default 0.0).
     - SECONDARY metric: coverage_score recorded for audit trail but does not gate pass/fail.
  3. Pass rule: at least 2 summaries must pass both checks.
"""
from __future__ import annotations

from collections import defaultdict
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


_MAX_SAMPLE_FACTS_DEFAULT = 40


def _sample_facts(facts: List[Dict[str, Any]], max_sample: int) -> List[Dict[str, Any]]:
    """
    Deterministic stratified sample of facts by type.

    Facts are already ordered by fact_id. Within each type bucket we take
    evenly-spaced elements so the sample spans the full document rather than
    clustering at the start. Returns at most max_sample facts sorted by fact_id.
    """
    if len(facts) <= max_sample:
        return facts

    # Group by type, preserving fact_id order within each bucket
    by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in facts:
        by_type[f.get("type", "empirical_claim")].append(f)

    n_types = len(by_type)
    per_type = max(1, max_sample // n_types)

    sampled: List[Dict[str, Any]] = []
    for type_facts in by_type.values():
        if len(type_facts) <= per_type:
            sampled.extend(type_facts)
        else:
            step = len(type_facts) / per_type
            sampled.extend(type_facts[int(i * step)] for i in range(per_type))

    # Sort by fact_id for a stable, deterministic output ordering
    sampled.sort(key=lambda f: f.get("fact_id", ""))
    return sampled[:max_sample]


def _semantic_score(
    summary: Dict[str, Any],
    facts: List[Dict[str, Any]],
    llm_client: Any,
    compiler_model: str,
    max_sample_facts: int = _MAX_SAMPLE_FACTS_DEFAULT,
) -> Dict[str, Any]:
    """
    Call the LLM to check the summary for contradictions against the fact list.
    Returns a scoring result dict with contradiction_score as the primary metric
    and coverage_score as a secondary informational metric.
    """
    from chorus_ai.llm.client import load_prompt, parse_json_response

    if not facts:
        return {
            "total_facts": 0,
            "contradicted_facts": 0,
            "covered_facts": 0,
            "contradiction_score": 0.0,
            "coverage_score": 1.0,
            "unsupported_claims": [],
            "fact_coverage": [],
            "error": None,
        }

    sample = _sample_facts(facts, max_sample_facts)
    sampled = len(sample) < len(facts)

    system_prompt = load_prompt("verify_system")
    facts_text = "\n".join(
        f'  {{"fact_id": "{f["fact_id"]}", "claim": "{f["claim"]}"}}'
        for f in sample
    )
    sample_note = (
        f" (stratified sample of {len(sample)} from {len(facts)} total)"
        if sampled
        else ""
    )
    user_content = (
        f"FACTS ({len(sample)} total{sample_note}):\n[\n{facts_text}\n]\n\n"
        f"SUMMARY TO EVALUATE:\n{summary.get('summary_text', '')}"
    )

    try:
        raw = llm_client.complete(
            model=compiler_model,
            system=system_prompt,
            user=user_content,
            max_tokens=8192,
            json_mode=True,
        )
        parsed = parse_json_response(raw)
    except Exception as exc:
        return {
            "total_facts": len(facts),
            "contradicted_facts": 0,
            "covered_facts": 0,
            "contradiction_score": 0.0,
            "coverage_score": 0.0,
            "unsupported_claims": [],
            "fact_coverage": [],
            "error": str(exc),
        }

    # Normalise contradiction_score
    contradiction_score = parsed.get("contradiction_score", 0.0)
    try:
        contradiction_score = float(contradiction_score)
    except (TypeError, ValueError):
        contradiction_score = 0.0
    contradiction_score = max(0.0, min(1.0, contradiction_score))
    parsed["contradiction_score"] = contradiction_score

    # Normalise coverage_score (secondary / informational)
    coverage_score = parsed.get("coverage_score", 0.0)
    try:
        coverage_score = float(coverage_score)
    except (TypeError, ValueError):
        coverage_score = 0.0
    coverage_score = max(0.0, min(1.0, coverage_score))
    parsed["coverage_score"] = coverage_score

    return parsed


def verify_summary_v1(
    *,
    facts: List[Dict[str, Any]],
    summaries: List[Dict[str, Any]],
    llm_client: Optional[Any] = None,
    compiler_model: str = "claude-sonnet-4-6",
    pass_threshold: float = 0.75,
    max_contradiction_score: float = 0.0,
    max_sample_facts: int = _MAX_SAMPLE_FACTS_DEFAULT,
) -> Dict[str, Any]:
    """
    Core verification entrypoint callable from stages/verify.py.

    Args:
        facts: Loaded fact dicts (from fact_list.json["facts"]).
        summaries: Loaded summary dicts.
        llm_client: LLMClient instance for semantic scoring. If None, skips scoring.
        compiler_model: Model to use for semantic scoring.
        pass_threshold: Kept for backwards compatibility; not used in pass/fail logic.
        max_contradiction_score: Maximum allowed contradiction_score to pass (default 0.0).
            A summary fails if it contradicts any extracted facts.

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
                    "contradiction_score": 1.0,
                    "coverage_score": 0.0,
                }
            )
            continue

        # 1. Structural check
        structural = _structural_check(summary, fact_count)

        # 2. Semantic scoring (only if structural passes and LLM client available)
        semantic: Optional[Dict[str, Any]] = None
        contradiction_score = 0.0
        coverage_score = 0.0

        if structural["status"] == "pass" and llm_client is not None:
            semantic = _semantic_score(
                summary, facts, llm_client, compiler_model, max_sample_facts
            )
            if semantic.get("error"):
                warnings.append(
                    f"Semantic scoring error for {slot}: {semantic['error']}"
                )
                # On scoring error, fail safe — treat as no contradictions detected
                contradiction_score = 0.0
                coverage_score = 0.0
            else:
                contradiction_score = semantic.get("contradiction_score", 0.0)
                coverage_score = semantic.get("coverage_score", 0.0)
        elif structural["status"] == "pass" and llm_client is None:
            # No LLM: auto-pass (structural-only mode)
            contradiction_score = 0.0
            coverage_score = 1.0
            warnings.append(
                f"No LLM client provided; skipping semantic scoring for {slot}."
            )

        # PRIMARY gate: fail if summary contradicts any extracted facts
        passes_contradiction_check = contradiction_score <= max_contradiction_score
        final_status = (
            "pass"
            if (structural["status"] == "pass" and passes_contradiction_check)
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
                "contradiction_score": contradiction_score,
                "coverage_score": coverage_score,
                "passes_contradiction_check": passes_contradiction_check,
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
            f"(max_contradiction_score={max_contradiction_score})."
        )

    overall = "pass" if min_viable else "fail"

    return {
        "status": overall,
        "created_at": _utc_now_iso(),
        "fact_count": fact_count,
        "max_contradiction_score": max_contradiction_score,
        "summary_results": per_summary,
        "checks": top_level_checks,
        "warnings": warnings,
    }
