import argparse
import json
from pathlib import Path

from chorus_ai.core.config import load_and_canonicalize_config
from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.core.hashing import sha256_file
from chorus_ai.runs.layout import compute_run_id, create_run_folders

from chorus_ai.stages.ingest import run_ingest
from chorus_ai.stages.extract import run_extract
from chorus_ai.stages.summarize import run_summarize
from chorus_ai.stages.verify import run_verify
from chorus_ai.stages.contextualize import run_contextualize
from chorus_ai.stages.compile import run_compile
from chorus_ai.stages.export import run_export


# Canonical lifecycle order (used for resume decisions)
STATE_ORDER = [
    "INIT",
    "INGESTED",
    "EXTRACTED",
    "SUMMARIZED",
    "VERIFIED",
    "CONTEXTUALIZED",
    "COMPILED",
    "FINALIZED",
]
STATE_INDEX = {s: i for i, s in enumerate(STATE_ORDER)}


def _read_status_state(run_root: Path) -> str:
    """Read the current lifecycle state from 00_meta/status.json."""
    status_path = run_root / "00_meta" / "status.json"
    if not status_path.exists():
        return "INIT"
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return "INIT"
    state = data.get("state") or data.get("current_state") or data.get("status")
    if not isinstance(state, str):
        return "INIT"
    state = state.strip().upper()
    return state if state in STATE_INDEX else "INIT"


def _should_run_stage(args_resume: bool, current_state: str, target_state: str) -> bool:
    """
    Option A semantics:
      - Not resuming: always run (new run expected from INIT).
      - Resuming: run only stages strictly after current_state.
    """
    if not args_resume:
        return True
    return STATE_INDEX[current_state] < STATE_INDEX[target_state]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="chorus-ai")
    parser.add_argument("pdf", type=str, help="Path to input PDF")
    parser.add_argument("--config", type=str, required=True, help="Path to config JSON")
    parser.add_argument("--runs-dir", type=str, default="runs", help="Base runs directory")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow overwriting stage outputs (use sparingly)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume an existing run folder by skipping stages at or before "
            "the current run state."
        ),
    )
    args = parser.parse_args(argv)

    try:
        pdf_path = Path(args.pdf).expanduser().resolve()
        cfg_path = Path(args.config).expanduser().resolve()
        runs_dir = Path(args.runs_dir).expanduser().resolve()

        if not pdf_path.exists():
            raise ChorusFatalError(
                "PDF_NOT_FOUND", "Input PDF not found", {"path": str(pdf_path)}
            )
        if not cfg_path.exists():
            raise ChorusFatalError(
                "CONFIG_NOT_FOUND", "Config JSON not found", {"path": str(cfg_path)}
            )

        config = load_and_canonicalize_config(cfg_path)
        run_id = compute_run_id(pdf_path, config)
        run_root = runs_dir / f"dossier_{run_id}"

        if run_root.exists():
            if not args.resume:
                raise ChorusFatalError(
                    "RUN_EXISTS",
                    "Run folder already exists (use --resume to continue, "
                    "or delete the run folder).",
                    {"run_root": str(run_root), "run_id": run_id},
                )
        else:
            run_root = create_run_folders(
                runs_dir, run_id, config, pdf_path, force=args.force
            )

        source_sha = sha256_file(pdf_path)
        current_state = _read_status_state(run_root)

        # --- Stage 1: Ingestion ---
        if _should_run_stage(args.resume, current_state, "INGESTED"):
            run_ingest(run_root, source_sha, force=args.force)
            current_state = "INGESTED"

        # --- Stage 2: Extraction ---
        if _should_run_stage(args.resume, current_state, "EXTRACTED"):
            run_extract(run_root, force=args.force)
            current_state = "EXTRACTED"

        # --- Stage 3: Summarization ---
        if _should_run_stage(args.resume, current_state, "SUMMARIZED"):
            run_summarize(str(run_root), force=args.force)
            current_state = "SUMMARIZED"

        # --- Stage 4: Verification (with retry loop) ---
        if _should_run_stage(args.resume, current_state, "VERIFIED"):
            verify_result = run_verify(str(run_root))
            if not verify_result.get("ok"):
                raise ChorusFatalError(
                    "VERIFY_FAILED", "Verification stage failed", verify_result
                )
            current_state = "VERIFIED"

        # --- Stage 5: Contextual Analysis (non-fatal) ---
        if _should_run_stage(args.resume, current_state, "CONTEXTUALIZED"):
            ctx_result = run_contextualize(run_root)
            # Non-fatal: always advance even if context partially failed
            if ctx_result.get("warnings"):
                print(
                    json.dumps(
                        {
                            "stage": "contextualize",
                            "warnings": ctx_result["warnings"],
                        }
                    )
                )
            current_state = "CONTEXTUALIZED"

        # --- Stage 6: Compilation ---
        if _should_run_stage(args.resume, current_state, "COMPILED"):
            compile_result = run_compile(str(run_root))
            if not compile_result.get("ok"):
                raise ChorusFatalError(
                    "COMPILE_FAILED", "Compile stage failed", compile_result
                )
            current_state = "COMPILED"

        # --- Stage 7: Finalization / Export ---
        if _should_run_stage(args.resume, current_state, "FINALIZED"):
            export_result = run_export(str(run_root))
            if not export_result.get("ok"):
                raise ChorusFatalError(
                    "EXPORT_FAILED", "Export stage failed", export_result
                )
            current_state = "FINALIZED"

        print(
            json.dumps(
                {
                    "ok": True,
                    "run_id": run_id,
                    "run_root": str(run_root),
                    "state": current_state,
                    "resume": bool(args.resume),
                },
                indent=2,
            )
        )
        return 0

    except ChorusFatalError as e:
        print(
            json.dumps(
                {"ok": False, "error": e.code, "message": str(e), "details": e.details},
                indent=2,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
