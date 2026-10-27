# pyrefly: ignore [missing-import]
from src.finding_state import FindingState

from src.finding_lifecycle import compare_findings


def reconcile_state(
    previous_states: list[FindingState],
    current_keys: set[str],
):
    previous_open = {
        s.finding_key
        for s in previous_states
        if s.status.lower() == "open"
    }

    previous_resolved = {
        s.finding_key
        for s in previous_states
        if s.status.lower() == "resolved"
    }

    result = compare_findings(
        previous_open=previous_open,
        previous_resolved=previous_resolved,
        current=current_keys,
    )

    updated_states = []

    for state in previous_states:
        if state.finding_key in result.resolved:
            state.status = "resolved"

        elif state.finding_key in result.reopened:
            state.status = "open"

        updated_states.append(state)

    known_keys = {
        s.finding_key
        for s in updated_states
    }

    for key in result.new:
        if key not in known_keys:
            updated_states.append(
                FindingState(
                    finding_key=key,
                    thread_id=None,
                    status="open",
                )
            )

    return result, updated_states