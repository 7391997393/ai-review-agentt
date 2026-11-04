# AI Review Agent: Learning Guide

This guide explains the project, as it is actually implemented, to an instructor. Every
statement here matches the code in `main.py` and `src/`.

## 1. Problem statement

Code review is valuable but slow. Human reviewers spend time on repetitive checks
instead of architecture, correctness and security. This project adds an AI reviewer to
the Pull Request workflow. It posts a first-pass review automatically, and people make
the final decision.

## 2. What is an LLM?

A Large Language Model generates and reasons over text. Here it receives the PR context
and produces structured review findings.

The LLM (Capgemini Generative Engine) is not GitHub and not the MCP server. It is only
the reasoning engine.

## 3. What is an AI agent?

An agent combines a model with tools, state, instructions and workflow logic. This
application:

- receives a PR to review (from GitHub Actions)
- gets the PR data through tools (GitHub MCP)
- asks the model for findings and validates them
- reasons about existing review threads (duplicates, outdated threads)
- acts on GitHub (posts a review, resolves its own outdated threads)

## 4. LangChain

LangChain provides the model client. `src/reviewer.py` uses `ChatOpenAI` from
`langchain-openai`, pointed at the Capgemini OpenAI-compatible endpoint:

```python
ChatOpenAI(model=..., api_key=..., base_url=..., temperature=0, max_tokens=...)
```

The project does **not** use `with_structured_output`. The model is told to return a
JSON object. The code extracts that JSON (`extract_json`), normalises each finding
(`normalize_finding`) and validates the result with Pydantic (`ReviewResult`). Doing
this by hand works with any OpenAI-compatible endpoint, and lets the agent repair a
malformed answer once before giving up.

## 5. LangGraph

LangGraph models the workflow as a graph with **state**, **nodes** and **edges**.

```python
class ReviewState(TypedDict, total=False):
    context: str
    findings: list[Finding]
```

The current graph (`src/graph.py`) has **one** node:

```text
START -> review -> END
```

The `review` node calls `review_all_categories`, which reviews all four categories in a
single model call. That keeps cost and latency low. The graph is the extension point:
separate category nodes or a static-analysis node can be added later without changing
`main.py`.

## 6. MCP

MCP (Model Context Protocol) standardises how an application connects to tools.

```text
Agent (MCP client)  --MCP over stdio-->  GitHub MCP Server  -->  GitHub
```

MCP does not replace the LLM. It is the tool boundary.

## 7. GitHub MCP Server

GitHub's official MCP server exposes GitHub operations as tools. The agent starts it in
Docker, using a pinned image (`ghcr.io/github/github-mcp-server:v2.0.3`) with only the
`repos,pull_requests,issues` toolsets enabled.

Tools used:

| Tool | Method | Used for |
|---|---|---|
| `pull_request_read` | `get` | PR title, author, branches, description |
| `pull_request_read` | `get_files` | changed files with per-file patches (paginated) |
| `pull_request_read` | `get_diff` | fallback only, when no patches are returned |
| `pull_request_read` | `get_review_comments` | fallback only, when GraphQL fails |
| `pull_request_review_write` | `create`, `submit_pending` | create and submit the review |
| `add_comment_to_pending_review` | | inline comments |

If an MCP tool reports an error, `GitHubMCPClient.call` raises `GitHubError` instead of
returning the error text, so a failed operation is never mistaken for a success.

## 8. Why GraphQL as well?

Some operations go directly to the GitHub GraphQL API (`execute_graphql`, using a
shared `httpx` client):

- `reviewThreads`: thread IDs, `isResolved`, `isOutdated`, path, line, first comments
  and their authors, plus `viewer { login }` (the account behind the token);
- `reviews`: earlier review bodies, used to detect repeated summary-only findings;
- `resolveReviewThread` and `unresolveReviewThread` mutations.

A mutation only counts as successful when GitHub returns the thread with the expected
`isResolved` value. Null data, GraphQL errors and HTTP errors all raise `GitHubError`.

## 9. GitHub Actions

GitHub Actions decides **when** the agent runs. The caller workflow in the target
repository listens to:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]
```

- opened: new PR
- synchronize: new commits pushed to the PR
- reopened: a closed PR is reopened

It calls the reusable workflow `.github/workflows/reusable-ai-review.yml`. That workflow
checks that the secrets exist, checks out the agent (`agent_ref`), installs the
requirements and runs `python main.py`. It allows only one review per PR at a time and
has a 20-minute timeout.

For pull requests from forks, GitHub does not provide secrets. The workflow then skips
the review and says so clearly in a warning and in the job summary.

## 10. How does the agent know the PR number?

The workflow passes `PR_NUMBER` from `github.event.pull_request.number`. When it is
missing, `get_pr_number()` reads the event file at `GITHUB_EVENT_PATH`.

## 11. Building the review context

`src/context_builder.py` turns the PR into text for the model:

- the PR title, author, base and head branches, and description (capped at 4000 chars);
- each file's patch exactly **once**, with a gutter showing the new-file line number:

```text
@@ -1,3 +1,4 @@
     1  import os
       -password = 'x'
     2 +password = os.environ['PASSWORD']
     3 +token = 'abc'
```

When the context would exceed `MAX_REVIEW_CONTEXT_CHARS`, whole hunks are dropped, never
half a hunk, and the files that were left out are listed.

## 12. Why Pydantic?

LLM output is untrusted and inconsistent. `normalize_finding` coerces every field
(unknown category → `standards`, invalid line → `null`, confidence clamped to 0–1,
over-long text cut), and then Pydantic validates:

```text
category, severity, file, line, title, description, recommendation, confidence
```

## 13. Four review categories

All four are reviewed in one prompt (`src/prompts.py`). The common instructions appear
once, followed by one section per category:

- **Security**: injection, secrets, authn/authz, deserialization, path traversal, …
- **Standards**: logic bugs, boundaries, error handling, duplication, naming, …
- **Tests**: new or changed behaviour without tests, missing edge cases
- **Performance**: N+1 access, repeated network calls, O(n²) work, …

## 14. Duplicate detection and thread lifecycle

`src/thread_resolver.py` is the single place that writes and reads the agent's comment
format.

- **Finding key** = `file:line:normalised title`. The description is left out on
  purpose, so a reworded finding is still the same finding.
- An **AI thread** is one whose *first* comment has the agent's format, and whose author
  is the token's account when GitHub reports the author. Human threads are never
  touched.
- **Outdated AI threads** (the code under them changed) are **resolved**. The finding
  may then be reported again on the new code.
- A finding is a **duplicate** if an AI thread with the same key still sits on current
  code, open or resolved.
- **Summary-only findings** (no line, or a line outside the diff) carry a hidden
  fingerprint in the summary review, which is read back on the next run.
- With `REOPEN_RESOLVED_THREADS=true`, a resolved AI thread whose finding is reported
  again is **reopened** (`unresolveReviewThread`).

Threads are never resolved just because the LLM did not repeat a finding. LLM output is
not deterministic, so a missing finding does not prove the issue was fixed.

## 15. Valid inline comments only

GitHub rejects inline comments on lines that are not part of the diff.
`validate_finding_against_changed_files` (`src/diff_utils.py`) checks that:

- the file is in the PR (old names of renamed files are mapped to the new name);
- the file was not deleted and has a textual patch;
- the line is an added or unchanged line on the new side of the diff.

Anything else is reported in the summary review instead.

## 16. Security architecture

- Repository content is **untrusted**. The PR context is wrapped in
  `<pull_request_context>` tags, and the model is told never to follow instructions
  inside it.
- Model output is also untrusted. Mentions (`@user`) are neutralised and HTML comments
  are escaped, so the model cannot ping people or forge hidden markers.
- No PR code is checked out or executed.
- Tokens are never logged, and debug logs record only response sizes.

## 17. Why temperature 0 and why COMMENT reviews?

`temperature=0` reduces randomness, which suits code review, although answers are still
not guaranteed to be identical. The review is always submitted with event `COMMENT`:
AI suggests, and humans decide.

```text
AI suggests  ->  human validates  ->  merge decision
```

## 18. End-to-end run

```text
1.  GitHub emits a pull_request event; the caller workflow calls the reusable workflow.
2.  The secrets check passes (or the run is skipped for forks, with a warning).
3.  The agent repository is checked out and its requirements are installed.
4.  main.py loads Settings and the PR number.
5.  The GitHub MCP Server starts in Docker; the MCP session initialises.
6.  pull_request_read get + get_files fetch the PR and its patches.
7.  context_builder builds the numbered, size-limited context.
8.  LangGraph runs the review node: one LLM call, JSON parsing, Pydantic validation.
9.  Review threads are loaded through GraphQL (MCP fallback).
10. Outdated AI threads are resolved; reopening is optional.
11. Findings are split into inline, summary-only and duplicate.
12. A pending review is created, inline comments are added, the review is submitted.
13. The exit code is 1 if any GitHub operation failed, otherwise 0.
```

## 19. The most important distinction

```text
GitHub Actions  = WHEN the agent runs
GitHub MCP      = HOW the agent reads the PR and writes the review
GitHub GraphQL  = HOW review threads are inspected and resolved
LangGraph       = HOW the workflow is orchestrated (one node today)
LangChain       = the client for the OpenAI-compatible model API
LLM             = the REASONING engine
Pydantic        = OUTPUT validation
Python          = the application
```

## 20. Limitations and next steps

- One LLM call; very large PRs are truncated at hunk boundaries.
- The model's line numbers can be wrong. Those findings go to the summary.
- No static analysis yet. Ruff, Bandit or CodeQL results could be combined with the LLM.
- Possible next steps: per-category graph nodes, repository-specific rules, severity
  thresholds, evaluation datasets (precision/recall), release tags for the workflow,
  and an Azure DevOps integration behind the same review graph.
