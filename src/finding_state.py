import json
from dataclasses import dataclass, asdict


STATE_MARKER = "ai-review-state"


@dataclass
class FindingState:
    finding_key: str
    thread_id: str | None
    status: str


def encode_state(states: list[FindingState]) -> str:
    payload = [asdict(s) for s in states]

    return (
        f"<!-- {STATE_MARKER}:start -->\n"
        f"{json.dumps(payload)}\n"
        f"<!-- {STATE_MARKER}:end -->"
    )


def decode_state(body: str) -> list[FindingState]:
    start_tag = f"<!-- {STATE_MARKER}:start -->"
    end_tag = f"<!-- {STATE_MARKER}:end -->"

    if start_tag not in body:
        return []

    start = body.index(start_tag) + len(start_tag)
    end = body.index(end_tag)

    json_blob = body[start:end].strip()

    data = json.loads(json_blob)

    return [FindingState(**x) for x in data]