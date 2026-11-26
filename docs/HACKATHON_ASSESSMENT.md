# Hackathon assessment, gaps and action plan

This is an internal readiness review, not a submission document. The scores are a candid
judgement of the repository as it stands, not a prediction of the result.

## 1. Scores

| Criterion | Score | Why | Biggest improvement |
|-----------|-------|-----|---------------------|
| Innovation | 7/10 | Full thread lifecycle (dedupe, resolve, reopen) and ownership checks go beyond a comment bot. The core idea (LLM reviews a PR) is common. | Add one visible "wow" feature: auto-suggested fixes (section 4) |
| Technical complexity | 8/10 | MCP plus GraphQL, diff-aware placement, hunk-safe truncation, JSON repair, 171 tests, CI on two Python versions. | Show it live on a real repo with numbers |
| Agentic AI usage | 5/10 | One model call in a one-node LangGraph. The agent does not choose tools, plan, or check its own work. Judges for an "agentic" event will notice. | Add real agent steps: a verification pass and tool use (section 4) |
| Business impact | 6/10 | Clear problem. The ROI is modelled, not measured. | Run a pilot and report real precision and time saved |
| User experience | 6/10 | Native GitHub comments are the right place. No configuration file, no fix suggestions, no dashboard, nothing to show on a slide. | Suggested-change blocks, a short summary with severity counts at the top |
| Scalability | 6/10 | Reusable workflow, pagination, size limits. Single call per run, and large PRs are truncated, not chunked. | Per-file chunking, skip docs-only PRs |

Overall: a solid, well-tested engineering project whose weakest point is how "agentic" it is
and the lack of live evidence.

## 2. Gaps that could cost points

1. **No live end-to-end evidence.** The live path (real MCP binary, real GitHub, real model)
   has not been run in this environment. Unit tests are strong, but judges reward a working
   demo. This is the highest risk.
2. **Agentic depth.** One LLM call is closer to "LLM-assisted" than "agentic".
3. **Business value is unmeasured.** The numbers are assumptions.
4. **No suggested fixes.** Reviewers get problems but not patches.
5. **No project-specific rules.** Teams cannot say "we require X". There is no config file.
6. **Single-model, no false-positive control.** Nothing checks a finding before posting it.
7. **Pinning.** Callers default to `@main`; the Windows binary was not tested on this machine.
8. **No visuals for a demo.** Diagrams exist (docs/ARCHITECTURE.md); screenshots and a short
   recording do not.
9. **Coverage of languages.** Prompts are language-agnostic; nothing proves quality per language.

## 3. Prioritised action plan

### Must have (before submission)

- [ ] Run the live end-to-end test (TEST_PLAN.md E1 to E7) on a scratch repo and keep the PR
      links, logs and screenshots.
- [ ] Fix anything the live run finds (the MCP binary on Windows has not been executed here).
- [ ] Pin the workflow reference and `agent_ref` to a tag, and tag a release.
- [ ] Record a 5-minute demo video following DEMO.md, plus a backup.
- [ ] Replace modelled numbers in BUSINESS_VALUE.md with pilot data if any exists; otherwise
      keep the "illustrative" label.
- [ ] Rotate any token that was ever pasted into a file in the working tree.

### Should have

- [ ] Verification pass: a second, cheap model call that re-checks each finding against the
      diff and drops the ones it cannot support. It improves precision and makes the agent
      genuinely multi-step.
- [ ] Suggested-change blocks for simple fixes (GitHub renders them with an Apply button).
- [ ] A `.ai-review.yml` file for per-repo rules: ignored paths, extra instructions,
      minimum severity.
- [ ] A severity-count header and "top 3 risks" at the top of the summary.
- [ ] Skip docs-only and lock-file-only changes.

### Nice to have

- [ ] Per-file chunked review for very large PRs.
- [ ] Metrics: a small JSON artifact per run (findings, resolved, duplicates, duration).
- [ ] A `/ai-review` comment command to re-run on demand.
- [ ] Optional static-analysis node (ruff or bandit output as extra context).

## 4. Features achievable in 1 to 2 days

Ranked by effect on judging per hour of work.

| Feature | Effort | Raises | What to build |
|---------|--------|--------|---------------|
| Verification node in the LangGraph | 3 to 4 h | Agentic AI, Innovation | Add a second node after `review`: for each finding, ask the model "is this supported by the diff lines shown?"; drop unsupported ones, log the count. The graph becomes review -> verify. |
| Suggested fixes | 3 to 4 h | UX, Innovation | Add an optional `suggestion` field to `Finding`. When present and the finding is inline, append a ```` ```suggestion ```` block to the comment. Validate it is a single replacement line first. |
| Per-repo config file | 3 h | UX, Scalability | Read `.ai-review.yml` through MCP `get_file_contents`: `ignore_paths`, `min_severity`, `extra_instructions`. Apply before building context and before publishing. |
| Run metrics artifact | 1 to 2 h | Business impact | Write `review-metrics.json` (counts, duration) and upload it with `actions/upload-artifact`. Gives real numbers for the ROI slide. |
| Summary header | 1 h | UX | Severity counts and top risks at the top of `formatter.py` output. |
| Skip trivial PRs | 1 h | Scalability, cost | Skip when all changed files match docs or lock-file patterns. |

Suggested order: live E2E, verification node, suggested fixes, metrics artifact. That
combination gives the strongest "agentic" story and real numbers for the impact slide.

## 5. Running the MCP server without Docker

Done in this repository:

| Change | Where |
|--------|-------|
| Launcher resolves a local binary, checks it exists, and keeps Docker as an option | `resolve_mcp_launch()` in `src/mcp_github.py` |
| `GITHUB_MCP_COMMAND` accepts a path (quotes allowed); empty means auto-detect | `.env.example`, README |
| CI downloads the pinned release, verifies SHA-256, and sets `GITHUB_MCP_COMMAND` | `.github/workflows/reusable-ai-review.yml` |
| Read-only preflight | `verify_setup.py` |
| Tests for all launch paths, and a guard that the workflow version equals the pinned one | `tests/test_mcp_launch.py`, `tests/test_project_config.py` |
| Windows guide | `docs/WINDOWS_SETUP.md`, `BUILD.md` |

Steps for you:

1. Download and verify the binary (BUILD.md section 3).
2. Set `GITHUB_MCP_COMMAND` in `.env` to the full path of the `.exe`.
3. Run `python verify_setup.py`, then `python main.py`.
4. Push the changes so the workflow change reaches the repository that runs the review.

What is not verified: the workflow's download step and the Windows binary have not been run
here, so the first real run is the test.
