# JUDGE_GUIDE.md - AI Code Review Agent

## Problem statement

Code review is a bottleneck. Reviewers spend time on checks a machine can make (leaked
secrets, injection, missing tests, obvious performance traps), and feedback arrives late.
Existing bots post comments but leave a mess behind: duplicates on every push, stale threads
nobody closes, and comments that GitHub rejects because the line is not in the diff.

## Solution

An agent that runs on every pull request and manages the whole review lifecycle:

1. Detects the PR event in GitHub Actions.
2. Reads the changed files through the GitHub MCP Server.
3. Reviews them with Capgemini Generative Engine (`gpt-oss-120b`) across four categories:
   security, standards and correctness, tests, performance.
4. Validates each finding against the real diff and posts inline comments, with a summary.
5. Skips findings that already have a thread.
6. Resolves its own threads when the code under them changes, and reopens them if the issue
   returns.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the system, component and sequence
diagrams.

- **Trigger:** reusable GitHub Actions workflow, one `uses:` line per repository.
- **GitHub access:** official GitHub MCP Server as a standalone, checksum-verified binary
  (no Docker), plus the GraphQL API for threads.
- **Reasoning:** LangGraph workflow that calls the model through LangChain.
- **Safety:** Pydantic-validated findings, diff validation, sanitised output, ownership checks.

## Innovation

- **Lifecycle, not just comments.** Post, deduplicate, resolve and reopen.
- **Deterministic around a non-deterministic model.** Threads are resolved on GitHub's
  "outdated" signal, not on whether the model repeated a finding.
- **Untrusted-by-default.** PR content is fenced in the prompt, model output is normalised,
  and `@mentions` and the agent's hidden markers are neutralised.
- **Policy-friendly deployment.** No container runtime needed.

## Impact

- Faster first feedback on every PR.
- Consistent security and test-gap checks that do not depend on who reviews.
- Less reviewer time on mechanical issues, more on design.

Estimates and assumptions are in [BUSINESS_VALUE.md](BUSINESS_VALUE.md). They are modelled,
not measured.

## Scalability

| Dimension | Current behaviour | Next step |
|-----------|-------------------|-----------|
| Repositories | Reusable workflow; add one `uses:` line | Org-level required workflow |
| Large PRs | Hunk-safe truncation at `MAX_REVIEW_CONTEXT_CHARS`, with omitted files listed | Review in chunks, one call per file group |
| Many threads | Paginated GraphQL (up to 20 pages of threads) | None needed for typical PRs |
| Concurrency | One run per PR at a time, newer pushes queue | None |
| Cost | One model call per run | Skip docs-only changes, cache by commit |

## How to verify it quickly

1. `python -m pytest` : 171 tests pass without network.
2. `python verify_setup.py` : checks MCP, token and repository access, read-only.
3. Open a PR with a hard-coded password; read the review; push a fix; watch the thread resolve.

## Honest limitations

- One model call per run; a single LangGraph node.
- Comment ownership relies on the token's account; a different account is only recognised via
  `AGENT_LOGINS`.
- Findings are suggestions and need human validation.
