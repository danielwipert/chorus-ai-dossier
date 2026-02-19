from chorus_ai.stages.ingest import run_ingest
from chorus_ai.stages.extract import run_extract
from chorus_ai.stages.summarize import run_summarize
from chorus_ai.stages.verify import run_verify
from chorus_ai.stages.compile import run_compile
from chorus_ai.stages.export import run_export


def run_pipeline(run_dir: str) -> dict:
    results = {}

    results["ingest"] = run_ingest(run_dir)
    if not results["ingest"].get("ok"):
        return {"ok": False, "failed_stage": "ingest", "results": results}

    results["extract"] = run_extract(run_dir)
    if not results["extract"].get("ok"):
        return {"ok": False, "failed_stage": "extract", "results": results}

    results["summarize"] = run_summarize(run_dir)
    if not results["summarize"].get("ok"):
        return {"ok": False, "failed_stage": "summarize", "results": results}

    results["verify"] = run_verify(run_dir)
    if not results["verify"].get("ok"):
        return {"ok": False, "failed_stage": "verify", "results": results}

    results["compile"] = run_compile(run_dir)
    if not results["compile"].get("ok"):
        return {"ok": False, "failed_stage": "compile", "results": results}

    results["export"] = run_export(run_dir)
    if not results["export"].get("ok"):
        return {"ok": False, "failed_stage": "export", "results": results}

    return {"ok": True, "failed_stage": None, "results": results}
