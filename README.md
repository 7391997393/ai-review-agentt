# AI Review Agent

An AI-powered Pull Request code-review agent built with Python, LangChain, LangGraph, the official GitHub MCP Server, and GitHub Actions.

## What it does

When a Pull Request is opened, reopened, or updated:

1. GitHub Actions starts the agent.
2. The agent connects to GitHub through the official GitHub MCP Server.
3. It reads the PR, changed files, and diff.
4. LangGraph orchestrates four review stages:
   - Security
   - Coding standards / maintainability
   - Test coverage / test quality
   - Performance
5. An LLM returns validated, structured findings using Pydantic.
6. The agent combines the findings.
7. The agent posts one review to the Pull Request through GitHub MCP.

## Architecture

```text
Pull Request
     |
     v
GitHub Actions
     |
     v
Python application
     |
     +----------------------+
     | GitHub MCP Client    |
     +----------+-----------+
                |
                v
      Official GitHub MCP Server
                |
                v
        GitHub PR / Diff / Files
                |
                v
          LangGraph workflow
                |
       +--------+--------+--------+
       |        |        |        |
       v        v        v        v
   Security  Standards  Tests  Performance
       \        |        |        /
        \       |        |       /
         +------v--------v------+
                |
                v
          Structured LLM output
                |
                v
          Review formatter
                |
                v
      GitHub MCP: create review
                |
                v
             PR comment
```

## Prerequisites

- Python 3.10+
- Docker
- A GitHub repository
- A GitHub token stored as a secret
- An API key for an LLM provider supported by `langchain-openai` or an OpenAI-compatible endpoint

## Local setup

```bash
git clone <your-repository>
cd Ai_review_agent

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt

copy .env.example .env
```

Edit `.env`:

```text
OPENAI_API_KEY=your-key
OPENAI_MODEL=your-model-name

GITHUB_PERSONAL_ACCESS_TOKEN=your-github-token
GITHUB_OWNER=your-owner
GITHUB_REPO=your-repo
PR_NUMBER=1
```

Run:

```bash
python main.py
```

## GitHub MCP Server

This project launches GitHub's official MCP server as a Docker subprocess:

```text
ghcr.io/github/github-mcp-server
```

The MCP server is configured with the toolsets needed by this project:

```text
repos,pull_requests
```

The application uses MCP tools such as:

- `pull_request_read`
- `get_file_contents`
- `pull_request_review_write`

The official server also supports more toolsets and individual-tool allowlists.

## GitHub Actions

The workflow is in:

```text
.github/workflows/code-review.yml
```

Add these repository secrets:

```text
OPENAI_API_KEY
```

The GitHub token is supplied to the workflow from `secrets.GITHUB_TOKEN`.

The workflow provides:

```text
GITHUB_REPOSITORY
GITHUB_EVENT_PATH
```

so the Python program can identify the repository and Pull Request.

## Important security note

Treat repository content as untrusted input. Code, comments, and PR descriptions can contain prompt-injection instructions. The model is instructed to treat repository text as code/data, not as instructions. The GitHub MCP server should also be restricted to only the toolsets required by the application.

For the first working version, this project posts a single review summary rather than automatically changing code or merging PRs.

## Project structure

```text
Ai_review_agent/
|
+-- .github/
|   +-- workflows/
|       +-- code-review.yml
|
+-- src/
|   +-- __init__.py
|   +-- config.py
|   +-- schemas.py
|   +-- prompts.py
|   +-- mcp_github.py
|   +-- reviewer.py
|   +-- graph.py
|   +-- formatter.py
|
+-- tests/
|   +-- test_formatter.py
|
+-- .env.example
+-- .gitignore
+-- requirements.txt
+-- main.py
+-- README.md
```

## How to explain this project

### 30-second explanation

> This project is an AI-based Pull Request reviewer. GitHub Actions triggers a Python application whenever a Pull Request changes. The application uses the official GitHub MCP Server to retrieve Pull Request information and code changes. LangGraph orchestrates separate review stages for security, coding standards, testing, and performance. An LLM analyzes each stage and returns validated Pydantic objects. The findings are combined and posted back to GitHub as a Pull Request review.

### Key concepts

**LLM:** The model that reasons about the code.

**Agent:** The application that decides what work needs to be done and coordinates tools and model calls.

**LangChain:** Provides model integration and structured output support.

**LangGraph:** Represents the review workflow as a graph of state + nodes + edges.

**MCP:** A standard protocol that lets an AI application communicate with external tools.

**GitHub MCP Server:** The GitHub-provided MCP server exposing GitHub operations as MCP tools.

**GitHub Actions:** The CI/CD automation layer that triggers the agent from Pull Request events.

**Pydantic:** Defines the expected finding schema and validates the model response.

## Instructor questions you should be able to answer

1. Why use an LLM?
2. Why use an agent instead of a simple script?
3. Why LangGraph?
4. What is the state in LangGraph?
5. What is a node?
6. What is an edge?
7. What is MCP?
8. What is an MCP client?
9. What is an MCP server?
10. Why GitHub MCP instead of directly calling the GitHub REST API?
11. How does GitHub Actions trigger the project?
12. How does the agent know which PR to inspect?
13. How are changed files obtained?
14. How is the LLM output made reliable?
15. Why use Pydantic?
16. What security risks exist with AI code review?
17. Why should the agent not blindly modify code?
18. How could Azure DevOps MCP be added?
19. How would you reduce hallucinations?
20. How would you scale this to many repositories?

## Limitations of this academic version

- It is a review assistant, not a replacement for human reviewers.
- LLM findings can be incorrect and require validation.
- It posts a summary review rather than automatically approving/rejecting a PR.
- For production, add rate limits, caching, diff-size limits, observability, secret scanning, and stronger policy enforcement.
