# Architecture

The agent runs as one Python process inside a GitHub Actions job (or on a laptop). It reads a
pull request through the **GitHub MCP Server**, asks the **Capgemini Generative Engine**
(`gpt-oss-120b`) for structured findings, validates them against the real diff, and publishes
one review. It also manages its own review threads through the **GitHub GraphQL API**.

The MCP server runs as a standalone executable started over stdio. No Docker is used.

## 1. System architecture

```mermaid
flowchart LR
    DEV([Developer]) -- opens / updates PR --> GH[(GitHub<br/>Pull Request)]
    GH -- pull_request event --> GA[GitHub Actions<br/>reusable workflow]

    subgraph RUNNER["Actions runner (or laptop) - no Docker"]
        GA --> BIN[/"github-mcp-server<br/>standalone binary<br/>checksum-verified"/]
        GA --> APP["main.py<br/>AI Review Agent"]
        APP <-- "MCP over stdio" --> BIN
    end

    BIN -- "REST / MCP tools<br/>read PR, write review" --> GH
    APP -- "GraphQL<br/>threads, reviews,<br/>resolve / unresolve" --> GH
    APP -- "OpenAI-compatible API" --> LLM[["Capgemini Generative Engine<br/>gpt-oss-120b"]]

    SECRETS[(Repository secrets<br/>CG_API_KEY, GH_PAT)] -.-> GA
    GH -- inline comments + summary --> DEV
```

## 2. Component diagram

```mermaid
flowchart TB
    subgraph ENTRY["Entry"]
        MAIN["main.py<br/>orchestration, run report,<br/>exit code"]
        VERIFY["verify_setup.py<br/>read-only preflight"]
        CFG["src/config.py<br/>Settings from env"]
    end

    subgraph GITHUB["GitHub access - src/mcp_github.py"]
        LAUNCH["resolve_mcp_launch()<br/>binary or image"]
        MCPC["GitHubMCPClient<br/>MCP tools"]
        GQL["GraphQL client<br/>pagination, resolve,<br/>unresolve with confirmation"]
    end

    subgraph REVIEW["Review pipeline"]
        CTX["context_builder.py<br/>numbered diff, hunk-safe<br/>truncation"]
        GRAPH["graph.py<br/>LangGraph workflow"]
        PROMPT["prompts.py<br/>4 categories, injection guard"]
        REV["reviewer.py<br/>LLM call, JSON repair,<br/>normalisation"]
        SCHEMA["schemas.py<br/>Pydantic Finding"]
    end

    subgraph PUBLISH["Publishing and lifecycle"]
        DIFF["diff_utils.py<br/>is the line commentable?"]
        THREAD["thread_resolver.py<br/>ownership, dedupe,<br/>resolve / reopen, sanitising"]
        FMT["formatter.py<br/>summary markdown"]
    end

    MAIN --> CFG
    MAIN --> MCPC
    MAIN --> GQL
    MCPC --> LAUNCH
    MAIN --> CTX --> GRAPH --> REV
    PROMPT --> REV
    REV --> SCHEMA
    MAIN --> DIFF
    MAIN --> THREAD
    MAIN --> FMT
    VERIFY --> MCPC
```

## 3. Sequence: from PR to resolved thread

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant GH as GitHub
    participant GA as GitHub Actions
    participant AG as main.py (agent)
    participant MCP as GitHub MCP Server (binary)
    participant LLM as Capgemini GenAI (gpt-oss-120b)

    Dev->>GH: Open or update pull request
    GH->>GA: pull_request event (reusable workflow)
    GA->>GA: Secrets guard (skip forks / Dependabot with a visible notice)
    GA->>GA: Download MCP binary, verify SHA-256
    GA->>AG: python main.py

    AG->>MCP: start (stdio), initialize
    AG->>MCP: pull_request_read get + get_files (paged)
    MCP->>GH: read PR and patches
    GH-->>AG: details and per-file diffs

    AG->>AG: Build numbered, size-limited context
    AG->>LLM: Review prompt (PR is untrusted data)
    LLM-->>AG: JSON findings
    AG->>AG: Repair, normalise, validate against the diff

    AG->>GH: GraphQL: existing threads, earlier reviews, viewer login
    AG->>GH: GraphQL resolveReviewThread (own outdated threads only)
    AG->>AG: Drop duplicates (thread key / summary fingerprint)

    AG->>MCP: create pending review
    loop each new inline finding
        AG->>MCP: add_comment_to_pending_review
    end
    AG->>MCP: submit_pending (event COMMENT)
    MCP->>GH: publish review
    GH-->>Dev: Inline comments and summary

    Note over Dev,GH: Developer pushes a fix
    GH->>GA: synchronize event, run again
    AG->>GH: Thread is now outdated, so GraphQL resolves it
    opt REOPEN_RESOLVED_THREADS=true and the issue returns
        AG->>GH: GraphQL unresolveReviewThread
    end
```

## 4. Design decisions

| Decision | Reason |
|----------|--------|
| MCP for reading and writing the review, GraphQL for threads | MCP does not expose thread IDs or resolve; GraphQL gives exact IDs and confirms the result. |
| Standalone binary, SHA-256 verified | Meets the no-Docker policy and keeps the pinned, tested server version. |
| One LLM call, LangGraph with one node | Low cost and latency; the graph is the extension point for more stages. |
| Findings validated against the diff | Comments only land on lines GitHub accepts; the rest go to the summary. |
| Thread ownership by author | The agent never resolves or reopens a human's thread. |
| Exit code 1 when any GitHub write fails | CI shows failures instead of hiding them. |
