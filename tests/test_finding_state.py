from src.finding_state import (
    FindingState,
    encode_state,
    decode_state,
)


def test_state_roundtrip():
    states = [
        FindingState(
            "src/app.py:42:sql-injection",
            "gh/thread/123",
            "resolved",
        ),
        FindingState(
            "src/auth.py:10:hardcoded-password",
            None,
            "open",
        ),
    ]

    encoded = encode_state(states)
    decoded = decode_state(encoded)

    assert decoded == states

