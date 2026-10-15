from dataclasses import dataclass


@dataclass
class LifecycleResult:
    new: set[str]
    existing: set[str]
    resolved: set[str]
    reopened: set[str]


def compare_findings(
    *,
    previous_open: set[str],
    previous_resolved: set[str],
    current: set[str],
) -> LifecycleResult:
    """
    Compare previous and current findings.

    NEW:
        Present now but never seen before.

    EXISTING:
        Already open and still present.

    RESOLVED:
        Was open previously but missing now.

    REOPENED:
        Was resolved previously and appeared again.
    """

    new = current - previous_open - previous_resolved

    existing = current & previous_open

    resolved = previous_open - current

    reopened = current & previous_resolved

    return LifecycleResult(
        new=new,
        existing=existing,
        resolved=resolved,
        reopened=reopened,
    )