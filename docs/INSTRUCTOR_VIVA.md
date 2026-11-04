# Instructor Viva Questions and Answers

## Basic

### Q1. What is the project?

It is a reusable AI Pull Request review agent. It analyses changed code for security,
coding standards, testing and performance problems, and posts a review with inline
comments to GitHub.

### Q2. Why did you build it?

Manual review is valuable, but repetitive checks consume reviewer time. The agent does a
first pass automatically so people can focus on architecture and business logic.

### Q3. What language did you use?

Python 3.12+.

### Q4. What is the role of the LLM?

The Capgemini Generative Engine reasons over the PR diff and returns findings as JSON.

### Q5. Is the LLM itself an agent?

No. The LLM is the reasoning model. The surrounding application supplies the tools
(GitHub MCP, GraphQL), state, workflow, prompts, validation and actions.

## LangChain / LangGraph

### Q6. Why LangChain?

`langchain-openai`'s `ChatOpenAI` gives a clean, async client for the Capgemini
OpenAI-compatible API (model, base URL, temperature, max tokens).

### Q7. Do you use `with_structured_output`?

No. The prompt asks for a JSON object. The code extracts it, normalises each field and
validates it with Pydantic. If the JSON is malformed or cut off, one repair call is
made. If that fails too, the run stops instead of posting incomplete findings.

### Q8. Why LangGraph if the graph has only one node?

The graph is `START -> review -> END`. One node reviews all four categories in one model
call, which keeps cost and latency low. The graph is the extension point for adding
per-category nodes or a static-analysis node without changing the entry point.

### Q9. What are state, nodes and edges?

State is the shared data (`context`, `findings`). A node is a function that returns
state updates (`review`). An edge defines what runs next.

## MCP and GraphQL

### Q10. What does MCP stand for, and what does it solve?

Model Context Protocol. It standardises how AI applications connect to tools and
context.

### Q11. Which GitHub MCP tools do you use?

`pull_request_read` (`get`, `get_files`, and the fallbacks `get_diff` and
`get_review_comments`), `pull_request_review_write` (`create`, `submit_pending`) and
`add_comment_to_pending_review`. The server image is pinned to `v2.0.3`.

### Q12. Why call GraphQL directly as well?

To read review threads with their exact IDs, `isOutdated`/`isResolved` flags and comment
authors, to read earlier review bodies, and to run the `resolveReviewThread` and
`unresolveReviewThread` mutations. A mutation only counts as successful when GitHub
returns the expected `isResolved` value.

### Q13. Is GitHub MCP the same as GitHub?

No. GitHub is the platform. The MCP server is an integration layer exposing GitHub
operations as tools.

## Review lifecycle

### Q14. How do you avoid duplicate comments?

Each finding has a key `file:line:normalised title`. If an AI thread with that key
still sits on current code, the finding is skipped. Findings that appear only in the
summary carry a hidden fingerprint in the review body, which is read back on the next
run. Duplicates inside the same run are removed too.

### Q15. When does the agent resolve a thread?

Only when all of these are true: the agent started the thread (first comment in the
agent's format, **and** its author is the token's account from GraphQL `viewer.login`),
the thread is unresolved, and GitHub marks it **outdated** because the code changed.
If the account cannot be determined, nothing is resolved. Other people's threads are
never resolved, even if they look like AI comments.

### Q16. Why not resolve a thread when the LLM stops reporting the finding?

LLM output is not deterministic. A missing finding does not prove the issue was fixed,
so closing threads on that basis would hide real problems.

### Q17. Can threads be reopened?

Yes, when the option is on (`REOPEN_RESOLVED_THREADS=true`). A resolved AI thread whose
finding is reported again on the same current line is reopened with
`unresolveReviewThread`. It is off by default, so a reviewer's decision to resolve is
respected.

### Q18. What happens if the model cites a line that is not in the diff?

`validate_finding_against_changed_files` checks the file, the rename mapping, whether
the file was deleted, and whether the line is on the new side of the diff. Invalid
targets are reported in the summary instead of as inline comments, so GitHub does not
reject inline comments for being outside the diff.

### Q19. What happened to the LifecycleManager?

It stored finding state in hidden review comments. It was never connected to the
pipeline, and it had defects: lost thread mappings, repeated "resolved" actions,
description-based identity, and wrong response parsing. GitHub's own thread state
(`isResolved`, `isOutdated`) already provides the lifecycle, so it was removed. Its
useful parts, patch parsing and diff validation, moved to `src/diff_utils.py`.

## GitHub Actions

### Q20. What triggers the review?

`pull_request` events of types `opened`, `synchronize` and `reopened` in the caller
workflow, which calls the reusable workflow.

### Q21. What permissions are needed?

`contents: read` and `pull-requests: write` for the job. The `gh_pat` secret needs pull
request read/write access on the target repository.

### Q22. What about pull requests from forks?

GitHub does not give secrets to fork PR workflows. The workflow detects this, skips the
review, adds a warning annotation, and writes "AI review not performed" to the job
summary. The check itself stays green, so the summary is where to look. Dependabot
pull requests are handled the same way unless the secrets are also stored as
Dependabot secrets.

### Q23. How do you stop two pushes from creating two reviews at once?

A `concurrency` group per repository and PR number runs one review at a time. A newer
run waits rather than cancelling a run that is halfway through posting.

## Reliability and security

### Q24. Can the AI be wrong?

Yes. The output is presented as suggestions in a `COMMENT` review, and people decide.

### Q25. How do you reduce hallucinations?

Give the model the real diff with line numbers, tell it not to invent evidence, validate
the output, move unverifiable line references to the summary, and keep people in the
loop.

### Q26. What is prompt injection, and how do you handle it?

Untrusted content trying to change the model's instructions, for example a code comment
saying "ignore your task". The PR context is wrapped in `<pull_request_context>` tags
and declared as data. The repair prompt treats the malformed answer as data. Model
output is sanitised so it cannot @mention people or forge the agent's hidden markers.

### Q27. What happens if GitHub fails?

MCP tool errors and GraphQL errors raise `GitHubError`. If review threads cannot be
loaded, the agent refuses to post rather than risk duplicates. If an inline comment or
thread resolution fails, the rest of the review continues, but the process exits with
code 1 so the job fails visibly. If submitting the review fails, the agent deletes its
own pending review first, because GitHub allows only one pending review per user and a
leftover would block every later run.

### Q28. What happens if the LLM returns invalid output?

One repair attempt is made. If the answer is still invalid, the run stops with an error
and nothing is posted.

### Q29. How is the project tested?

`pytest` with every external service mocked. The thread-resolution path is tested end
to end through the real `GitHubMCPClient` class. The pipeline tests replace only its
`execute_graphql` and MCP `call` methods; the tests of those two methods mock
`httpx` and the MCP session underneath them. A mutation harness checks that removing
any safety check makes the suite fail. Ruff and the tests run in CI (`ci.yml`) on Python 3.12 and 3.14.

## Advanced

### Q30. Why not only static analysis, or only the LLM?

Static analysis is precise for deterministic patterns but misses context. An LLM
understands intent but can hallucinate. Combining them is stronger, and adding static
analysis is a planned next step.

### Q31. How would you make it more production-ready?

Release tags for the reusable workflow, static-analysis input, evaluation datasets,
retries with backoff, observability (tracing, metrics) and repository-specific
policies.

### Q32. How would you support Azure DevOps?

Add an Azure DevOps integration behind the same client interface (fetch PR, post
review, list and resolve threads), while keeping the review graph unchanged.

## One-line architecture answer

> GitHub Actions triggers the Python agent. GitHub MCP supplies the PR and posts the
> review. GraphQL manages review threads. LangGraph orchestrates the review node.
> LangChain calls the Capgemini LLM. Pydantic validates the findings. Only valid,
> non-duplicate findings are posted.
