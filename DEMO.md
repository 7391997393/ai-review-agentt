# DEMO.md - 5-minute demo

## Before you go on stage

- A scratch repository with the reusable workflow wired in (see BUILD.md section 7).
- Two branches ready: `demo-flawed` (a hard-coded password, an SQL string built from user
  input, and a new function with no test) and a one-commit fix for the first two.
- Run `python verify_setup.py` and have a full dry run done. Keep a screenshot of the finished
  PR as a backup if the network or the model is slow.
- `REOPEN_RESOLVED_THREADS: true` in the caller workflow.

## Script

| Time | Do | Say |
|------|----|-----|
| 0:00 | Slide: the problem | "Reviewers spend their time on checks a machine can make: secrets, injection, missing tests. Real design feedback arrives late." |
| 0:30 | Open the PR on `demo-flawed`. Show the Actions run starting. | "Opening the PR is the only step. The reusable workflow downloads a checksum-verified GitHub MCP server binary. No Docker, which is a Capgemini policy requirement." |
| 1:15 | Show the architecture diagram (docs/ARCHITECTURE.md, system view). | "The agent reads the PR through MCP, asks gpt-oss-120b for structured findings, and uses GraphQL for review threads." |
| 1:45 | Open the finished review: summary plus inline comments. | "Findings are grouped by security, standards, tests and performance, with severity, a recommendation and a confidence score. Every comment sits on a line that exists in the diff; anything else goes in the summary." |
| 2:45 | Push the fix commit. Show the second run. | "The model's answer varies from run to run, so the agent never resolves a thread just because a finding wasn't repeated. It uses GitHub's own signal: the code under the thread changed." |
| 3:30 | Show the resolved threads and the log lines `Resolved thread ...`. | "Only the agent's own threads. A human's thread is never touched." |
| 4:00 | Re-run on the same commit. Show `No new findings to publish (N duplicate(s) skipped)`. | "No noise. Re-running or pushing again does not repeat the same comment." |
| 4:30 | Optional: reintroduce the flaw. Show the thread reopening. | "If the same problem comes back, the original thread is reopened with its history." |
| 4:45 | Close on the numbers slide (BUSINESS_VALUE.md). | "A first-pass reviewer in every PR, at the cost of one workflow run." |

## Talking points

- Reads a real PR end to end, and writes real review threads. Not a chat demo.
- LLM output is treated as untrusted: JSON is repaired and normalised, mentions and hidden
  markers are neutralised, and PR text is fenced as data in the prompt.
- The comment format round-trips: the same module writes comments and reads them back, so
  deduplication cannot drift.
- Failures are visible: a failed GitHub write makes the run exit 1.
- 171 automated tests, no network required.

## Business value (one line each)

- Faster first feedback: minutes after the push, not after a reviewer is free.
- Reviewers spend time on design and intent, not on mechanical checks.
- Security and test gaps are flagged before merge, every time.

## Technical differentiators

1. Full thread lifecycle: post, deduplicate, resolve, reopen. Most review bots only post.
2. Ownership checks, so the agent only manages its own threads.
3. Diff-aware placement: line validation, rename handling, deleted files, summary fallback.
4. Hunk-safe context truncation for large PRs, with a list of what was omitted.
5. MCP server as a pinned, checksum-verified standalone binary.
6. Reusable workflow: one `uses:` line adds it to any repository.

## If something goes wrong

| Problem | Recovery |
|---------|----------|
| Model is slow | Show the backup screenshot and the logs from the dry run. |
| Action fails on a secret | The run summary says why (fork or missing secret). Switch to `python main.py` locally. |
| Thread does not resolve | Say why: GitHub only marks a thread outdated when the flagged line itself changed. Edit that line in the demo fix. |
