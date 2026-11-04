from collections import Counter
from collections.abc import Iterable

from src.prompts import SEVERITIES
from src.schemas import Finding
from src.thread_resolver import sanitize_text, sanitize_title, summary_marker

_ORDER = {severity: index for index, severity in enumerate(SEVERITIES)}


def format_review(
    owner: str,
    repo: str,
    pull_number: int,
    findings: list[Finding],
    summary_fingerprints: Iterable[str] = (),
) -> str:
    """Markdown body of the summary review.

    `summary_fingerprints` are embedded as hidden markers so findings that are
    reported only here (no inline comment) are not repeated on the next run.
    """
    lines = [
        "## 🤖 AI Code Review",
        "",
        f"Repository: `{owner}/{repo}`  ",
        f"Pull Request: `#{pull_number}`",
        "",
    ]

    if not findings:
        lines += [
            "### ✅ No actionable findings",
            "",
            "The AI reviewer did not identify a concrete security, standards, testing, "
            "or performance issue in the supplied changes.",
        ]
        return "\n".join(lines)

    counts = Counter(item.severity for item in findings)
    lines += [
        f"**Total findings:** {len(findings)}",
        "",
        " | ".join(f"{severity.title()}: {counts.get(severity, 0)}" for severity in SEVERITIES),
        "",
    ]

    for finding in sorted(findings, key=lambda item: _ORDER[item.severity]):
        location = sanitize_text(finding.file) or "(general)"
        if finding.line:
            location += f":{finding.line}"

        lines += [
            f"### {finding.severity.upper()} — {finding.category.title()}",
            "",
            f"**{sanitize_title(finding.title)}**",
            "",
            f"**Location:** `{location}`",
            "",
            sanitize_text(finding.description),
            "",
            f"**Recommendation:** {sanitize_text(finding.recommendation)}",
            "",
            f"_Confidence: {finding.confidence:.0%}_",
            "",
            "---",
            "",
        ]

    lines += [
        "### ⚠️ Human review",
        "",
        "These findings are AI-generated suggestions. Validate important findings "
        "with tests, static analysis, and human review before making merge decisions.",
    ]
    markers = [summary_marker(fp) for fp in sorted(set(summary_fingerprints))]
    if markers:
        lines += ["", *markers]

    return "\n".join(lines)
