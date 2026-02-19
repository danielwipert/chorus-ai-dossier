import json
from pathlib import Path
from datetime import datetime, timezone


VALID_TRANSITIONS = {
    None: "INGESTED",
    "INGESTED": "EXTRACTED",
    "EXTRACTED": "SUMMARIZED",
    "SUMMARIZED": "VERIFIED",
    "VERIFIED": "CONTEXTUALIZED",
    "CONTEXTUALIZED": "COMPILED",
    "COMPILED": "FINALIZED",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(run_root: Path) -> dict:
    state_path = run_root / "state.json"
    if not state_path.exists():
        return {"current_state": None, "history": []}
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_state(run_root: Path, state: dict) -> None:
    state_path = run_root / "state.json"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def transition(run_root: Path, next_state: str) -> dict:
    state = load_state(run_root)
    current = state.get("current_state")

    expected = VALID_TRANSITIONS.get(current)
    if expected != next_state:
        raise RuntimeError(
            f"Invalid state transition: {current} → {next_state} (expected {expected})"
        )

    state["current_state"] = next_state
    state["history"].append({"state": next_state, "timestamp": _utc_now_iso()})

    save_state(run_root, state)
    return state
