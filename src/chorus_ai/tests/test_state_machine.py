"""Tests for the state machine — valid transitions, invalid transitions, history."""
import pytest

from chorus_ai.core.state_machine import transition, load_state, VALID_TRANSITIONS


def test_all_valid_transitions_defined():
    """Every state in the pipeline has a defined next state."""
    expected = {
        None: "INGESTED",
        "INGESTED": "EXTRACTED",
        "EXTRACTED": "SUMMARIZED",
        "SUMMARIZED": "VERIFIED",
        "VERIFIED": "CONTEXTUALIZED",
        "CONTEXTUALIZED": "COMPILED",
        "COMPILED": "FINALIZED",
    }
    assert VALID_TRANSITIONS == expected


def test_transition_init_to_ingested(tmp_path):
    state = transition(tmp_path, "INGESTED")
    assert state["current_state"] == "INGESTED"


def test_full_transition_sequence(tmp_path):
    sequence = [
        "INGESTED", "EXTRACTED", "SUMMARIZED", "VERIFIED",
        "CONTEXTUALIZED", "COMPILED", "FINALIZED",
    ]
    for target in sequence:
        transition(tmp_path, target)
    assert load_state(tmp_path)["current_state"] == "FINALIZED"


def test_transition_records_history(tmp_path):
    transition(tmp_path, "INGESTED")
    transition(tmp_path, "EXTRACTED")
    history = load_state(tmp_path)["history"]
    assert len(history) == 2
    assert history[0]["state"] == "INGESTED"
    assert history[1]["state"] == "EXTRACTED"


def test_invalid_transition_raises(tmp_path):
    with pytest.raises(RuntimeError, match="Invalid state transition"):
        transition(tmp_path, "COMPILED")  # skips many states


def test_invalid_transition_from_valid_state_raises(tmp_path):
    transition(tmp_path, "INGESTED")
    with pytest.raises(RuntimeError, match="Invalid state transition"):
        transition(tmp_path, "FINALIZED")  # wrong next state


def test_load_state_returns_none_when_missing(tmp_path):
    state = load_state(tmp_path)
    assert state["current_state"] is None
    assert state["history"] == []
