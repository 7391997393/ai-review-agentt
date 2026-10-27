from src.finding_lifecycle import compare_findings


def test_new_findings():
    result = compare_findings(
        previous_open=set(),
        previous_resolved=set(),
        current={"A", "B"},
    )

    assert result.new == {"A", "B"}
    assert result.existing == set()
    assert result.resolved == set()
    assert result.reopened == set()


def test_resolved_finding():
    result = compare_findings(
        previous_open={"A", "B"},
        previous_resolved=set(),
        current={"A"},
    )

    assert result.existing == {"A"}
    assert result.resolved == {"B"}


def test_reopened_finding():
    result = compare_findings(
        previous_open=set(),
        previous_resolved={"A"},
        current={"A"},
    )

    assert result.reopened == {"A"}
