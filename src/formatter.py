from collections import Counter

from src.schemas import Finding


def format_review(
    owner: str,
    repo: str,
    pull_number: int,
    findings: list[Finding],
) -> str:
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
        " | ".join(
            f"{severity.title()}: {counts.get(severity, 0)}"
            for severity in ["critical", "high", "medium", "low", "info"]
        ),
        "",
    ]

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    sorted_findings = sorted(findings, key=lambda x: order[x.severity])

    for finding in sorted_findings:
        location = finding.file
        if finding.line:
            location += f":{finding.line}"

        lines += [
            f"### {finding.severity.upper()} — {finding.category.title()}",
            "",
            f"**{finding.title}**",
            "",
            f"**Location:** `{location}`",
            "",
            finding.description,
            "",
            f"**Recommendation:** {finding.recommendation}",
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

    return "\n".join(lines)
