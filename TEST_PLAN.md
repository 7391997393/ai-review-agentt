# TEST_PLAN.md

Status legend: **Automated** runs in CI today. **Manual** is a documented procedure that has
to be executed by a person with real credentials.

## 1. Unit testing (Automated)

`python -m pytest` : 171 tests, no network, no LLM, no GitHub. Runs on Python 3.12 and 3.14
in CI together with `ruff check` and `ruff format --check`.

| Area | File | Covers |
|------|------|--------|
| Configuration | `test_config.py` | required variables, integer and boolean parsing, defaults |
| Context building | `test_context_builder.py` | line numbering, hunk-safe truncation, size limit |
| Diff handling | `test_diff_utils.py` | which lines can carry comments, renames, deleted files |
| Review parsing | `test_reviewer.py` | JSON extraction and repair, normalising bad model output |
| Thread logic | `test_thread_resolver.py` | comment format round-trip, ownership, duplicates, resolve/reopen selection |
| Formatting | `test_formatter.py` | summary output, sanitising |
| MCP launch | `test_mcp_launch.py` | binary path, missing binary, Docker kept working, token not on command line |
| Workflow guard | `test_project_config.py` | requirement lists in sync, workflow uses the pinned binary |

## 2. Integration testing (Automated, mocked boundaries)

`test_main.py`, `test_graph.py`, `test_mcp_github.py` and `test_safety_and_failures.py` run the
real pipeline (`run_review`, `publish_review`) against a fake GitHub client and a fake model:

- full review: read PR, find findings, post inline comments, submit;
- duplicate suppression across runs;
- resolve outdated threads, reopen on recurrence;
- partial failure: one inline comment fails, others are posted, exit code 1;
- submit fails: the pending review is deleted so the next run is not blocked.

## 3. End-to-end testing (Manual, requires credentials)

Prerequisite: `python verify_setup.py` passes. Use a scratch repository.

| # | Step | Expected |
|---|------|----------|
| E1 | Open a PR containing a hard-coded password, an SQL string built from input, and an untested function | Run succeeds; one review with inline comments on those lines |
| E2 | Re-run on the same commit | `No new findings to publish`; no new review |
| E3 | Push a fix that edits the flagged lines | Old threads are resolved; log shows `Resolved thread` |
| E4 | With `REOPEN_RESOLVED_THREADS=true`, bring the flaw back | The thread reopens |
| E5 | A human replies in an AI thread, and a human starts their own thread on a flagged line | Human thread untouched in both cases |
| E6 | Open a PR from a fork | Run is skipped with a visible notice, no failure |
| E7 | Run in GitHub Actions on the runner | MCP binary downloads, checksum passes, review posted |

Record results with date, PR link and the run log. Until E1 to E7 are executed, treat the
live path as unverified.

## 4. Security testing

| Check | How | Status |
|-------|-----|--------|
| Prompt injection in the diff | PR containing "ignore previous instructions"; confirm the findings are unaffected | Manual |
| Mention and marker forging | Model output containing `@team` or `<!-- ai-review-agent -->` is neutralised | Automated (`test_thread_resolver.py`) |
| Thread ownership | Human threads are never resolved or reopened | Automated |
| Token handling | Token is passed by environment, never on the command line or in logs | Automated (`test_mcp_launch.py`, log checks) |
| Dependency vulnerabilities | `pip install pip-audit; pip-audit -r requirements.txt` | Manual, last run: none found |
| Secrets in the repo | `.env` is gitignored; check `git log -S` for token prefixes before release | Manual |
| Fork PRs | Secrets are not exposed to fork code; the workflow skips with a notice | Manual (E6) |
| Supply chain of the MCP binary | SHA-256 verified against the release's checksum file | Automated check that the step exists; Manual for a live run |

## 5. Performance validation (Manual)

| Metric | How | Target |
|--------|-----|--------|
| End-to-end run time | Time `python main.py` on small (5 files), medium (30) and large (150) PRs | Small PR under 2 minutes |
| Context size limit | PR larger than `MAX_REVIEW_CONTEXT_CHARS` | Run completes; omitted files are logged |
| Model latency and tokens | Check the log for the single model call | One call per run |
| Cost per run | Provider usage dashboard for the test runs | Record and use it in BUSINESS_VALUE.md |

No load or timing results have been collected yet; the targets above are goals, not
measurements.
