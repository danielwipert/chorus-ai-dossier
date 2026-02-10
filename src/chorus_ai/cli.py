import argparse
import json
from pathlib import Path

from chorus_ai.core.config import load_and_canonicalize_config
from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.runs.layout import compute_run_id, create_run_folders


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="chorus-ai")
    parser.add_argument("pdf", type=str, help="Path to input PDF")
    parser.add_argument("--config", type=str, required=True, help="Path to config JSON")
    parser.add_argument("--runs-dir", type=str, default="runs", help="Base runs directory")
    parser.add_argument("--force", action="store_true", help="Allow overwriting run folder/meta")
    args = parser.parse_args(argv)

    try:
        pdf_path = Path(args.pdf).expanduser().resolve()
        cfg_path = Path(args.config).expanduser().resolve()
        runs_dir = Path(args.runs_dir).expanduser().resolve()

        if not pdf_path.exists():
            raise ChorusFatalError("PDF_NOT_FOUND", "Input PDF not found", {"path": str(pdf_path)})

        config = load_and_canonicalize_config(cfg_path)

        run_id = compute_run_id(pdf_path, config)
        run_root = create_run_folders(runs_dir, run_id, config, pdf_path, force=args.force)

        print(json.dumps({"ok": True, "run_id": run_id, "run_root": str(run_root)}, indent=2))
        return 0

    except ChorusFatalError as e:
        print(json.dumps({"ok": False, "error": e.code, "message": str(e), "details": e.details}, indent=2))
        return 2
