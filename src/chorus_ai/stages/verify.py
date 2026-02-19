from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from chorus_ai.core.config import load_run_config
from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.core.verification.verify_summary_v1 import verify_summary_v1
from chorus_ai.llm.client import LLMClient
from chorus_ai.runs.status import require_state, set_state


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_status(run_root: Path) -> Dict[str, Any]:
    return _load_json(run_root / "00_meta" / "status.json")


def _write_status(run_root: Path, status: Dict[str, Any]) -> None:
    (run_root / "00_meta" / "status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8"
    )


def _load_summaries(
    run_root: Path, summaries_rel: List[str]
) -> List[Dict[str, Any]]:
    summaries = []
    for rel in summaries_rel:
        p = (run_root / rel).resolve()
        if not p.exists():
            raise ChorusFatalError(
                "SUMMARY_MISSING",
                f"Summary file missing: {rel}",
                {"path": str(p)},
            )
        summaries.append(_load_json(p))
    return summaries


def _failed_slots(summary_results: List[Dict[str, Any]]) -> List[str]:
    """Return the model_slot values for failed summaries."""
    return [
        r["model_slot"]
        for r in summary_results
        if r.get("status") != "pass" and r.get("model_slot")
    ]


def run_verify(run_dir: str) -> dict:
    """
    Stage 4: VERIFICATION

    - Loads summaries from status.json["summaries"]
    - Runs structural + semantic scoring via verify_summary_v1()
    - Pass rule: at least 2 summaries score >= pass_threshold (default 0.75)
    - If fewer than 2 pass: regenerate failed summaries and retry (up to max_retries)
    - On retry exhaustion without 2 passing: FAIL and halt

    Returns:
        {"ok": bool, "artifact": str|None, "warnings": list[str]}
    """
    run_root = Path(run_dir)
    require_state(run_root, "SUMMARIZED")

    config = load_run_config(run_root)
    pass_threshold = float(
        config.get("verification", {}).get("pass_threshold", 0.75)
    )
    max_retries = int(config.get("verification", {}).get("max_retries", 2))
    compiler_model = config.get("models", {}).get("compiler", "claude-sonnet-4-6")

    status = _read_status(run_root)
    summaries_rel: List[str] = status.get("summaries", [])
    if not summaries_rel:
        return {"ok": False, "artifact": None, "warnings": ["status.json has no summaries"]}

    # Load facts
    facts_path = run_root / "20_extraction" / "fact_list.json"
    if not facts_path.exists():
        return {"ok": False, "artifact": None, "warnings": ["fact_list.json missing"]}

    facts_obj = _load_json(facts_path)
    facts = facts_obj.get("facts", []) if isinstance(facts_obj, dict) else []

    llm = LLMClient(config)
    retries_used = 0
    report: Optional[Dict[str, Any]] = None

    for attempt in range(max_retries + 1):
        summaries = _load_summaries(run_root, summaries_rel)

        report = verify_summary_v1(
            facts=facts,
            summaries=summaries,
            llm_client=llm,
            compiler_model=compiler_model,
            pass_threshold=pass_threshold,
        )

        if report["status"] == "pass":
            break

        # Fewer than 2 passed — decide whether to retry
        if attempt < max_retries:
            failed_slots = _failed_slots(report.get("summary_results", []))
            if not failed_slots:
                break  # Nothing to retry (shouldn't happen)

            retries_used += 1
            report["warnings"].append(
                f"Retry {retries_used}/{max_retries}: regenerating {failed_slots}"
            )

            # Regenerate only failed summaries
            from chorus_ai.stages.summarize import run_summarize

            try:
                new_paths = run_summarize(
                    run_root=str(run_root),
                    force=True,
                    slots=failed_slots,
                )
                summaries_rel = new_paths  # updated list from run_summarize
            except ChorusFatalError as exc:
                report["warnings"].append(
                    f"Failed to regenerate summaries during retry: {exc}"
                )
                break
        # If we've exhausted retries, fall through

    assert report is not None

    # Identify passing summary paths
    passing_paths: List[str] = []
    if isinstance(report.get("summary_results"), list):
        for i, res in enumerate(report["summary_results"]):
            if res.get("status") == "pass" and i < len(summaries_rel):
                passing_paths.append(summaries_rel[i])

    report["retries_used"] = retries_used
    report["passing_summary_paths"] = passing_paths
    report["inputs"] = {
        "facts_path": "20_extraction/fact_list.json",
        "summary_paths": summaries_rel,
    }

    # Write verification report
    out_dir = run_root / "40_verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "verification_report.json"
    _write_json(out_path, report)

    # Persist passing summary paths in status for downstream stages
    status = _read_status(run_root)
    status["passing_summaries"] = passing_paths
    _write_status(run_root, status)

    ok = report.get("status") == "pass"
    warnings = report.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    if ok:
        set_state(run_root, "VERIFIED")

    return {"ok": bool(ok), "artifact": str(out_path), "warnings": warnings}
