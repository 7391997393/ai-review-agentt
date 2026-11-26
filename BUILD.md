# BUILD.md - build, configure and run

Everything here works without Docker. For a more detailed Windows walkthrough see
[docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md).

## 1. Prerequisites

| Item | Version / note |
|------|----------------|
| Python | 3.12 or newer |
| Git | any recent version |
| GitHub personal access token | Pull requests: read and write; Contents: read and write (GitHub requires it to resolve review threads) |
| Capgemini Generative Engine key | `CG_API_KEY`, model `gpt-oss-120b` |
| GitHub MCP Server binary | v2.0.3, standalone executable (section 3) |

## 2. Local setup

```powershell
git clone https://github.com/7391997393/ai-review-agentt.git
cd ai-review-agentt
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

macOS or Linux: `source .venv/bin/activate` instead of the Activate script.

Check the build:

```powershell
ruff check .
ruff format --check .
python -m pytest
```

## 3. MCP server without Docker

The agent starts the GitHub MCP Server itself, as a child process over stdio. It only needs
the executable.

```powershell
$dir = "C:\tools\github-mcp-server"
New-Item -ItemType Directory -Force $dir | Out-Null
$base = "https://github.com/github/github-mcp-server/releases/download/v2.0.3"
Invoke-WebRequest "$base/github-mcp-server_Windows_x86_64.zip" -OutFile "$dir\mcp.zip"
Invoke-WebRequest "$base/github-mcp-server_2.0.3_checksums.txt" -OutFile "$dir\checksums.txt"
$expected = (Select-String "$dir\checksums.txt" -Pattern "Windows_x86_64.zip").Line.Split()[0]
if ((Get-FileHash "$dir\mcp.zip" -Algorithm SHA256).Hash.ToLower() -ne $expected) { throw "Checksum mismatch" }
Expand-Archive "$dir\mcp.zip" -DestinationPath $dir -Force
```

Linux or macOS: download `github-mcp-server_Linux_x86_64.tar.gz` (or the Darwin build) from
the same release and extract the `github-mcp-server` file.

How the agent picks the server (`resolve_mcp_launch` in `src/mcp_github.py`):

| `GITHUB_MCP_COMMAND` | Behaviour |
|----------------------|-----------|
| a path to the binary | Runs `<path> stdio --toolsets=repos,pull_requests,issues` |
| empty | Uses Docker if present, otherwise `github-mcp-server` on `PATH` |
| `docker` | Runs the pinned image (kept for compatibility) |

A wrong path fails immediately with `GitHub MCP server binary not found`.

## 4. Configuration

```powershell
Copy-Item .env.example .env
```

| Variable | Required | Example / default |
|----------|----------|-------------------|
| `CG_API_KEY` | yes | your key |
| `CG_MODEL` | yes | `gpt-oss-120b` |
| `CG_BASE_URL` | no | `https://openai.generative.engine.capgemini.com/v1` |
| `GITHUB_TOKEN` | yes | your PAT (`GH_PAT`, `GITHUB_PAT` also accepted) |
| `GITHUB_OWNER` | yes | repository owner |
| `GITHUB_REPO` | yes | repository name |
| `PR_NUMBER` | local runs | pull request number |
| `GITHUB_MCP_COMMAND` | recommended | `C:\tools\github-mcp-server\github-mcp-server.exe` |
| `REOPEN_RESOLVED_THREADS` | no | `false` |
| `AGENT_LOGINS` | no | extra bot accounts that posted for the agent earlier |
| `MAX_REVIEW_CONTEXT_CHARS` | no | `120000` |
| `CG_MAX_OUTPUT_TOKENS` | no | `8192` |
| `LOG_LEVEL` | no | `INFO` |

`.env` is gitignored. Never commit tokens.

## 5. Verify connectivity (read-only)

```powershell
python verify_setup.py
```

It checks the environment, starts the MCP server, lists its tools, validates the token and
repository access, and reads the PR if `PR_NUMBER` is set. It posts nothing.

## 6. Run a review

```powershell
python main.py
echo $LASTEXITCODE    # 0 = success, 1 = a GitHub operation failed
```

## 7. Run it in GitHub Actions

In the repository that should be reviewed, add secrets `CG_API_KEY` and `GH_PAT`, then:

```yaml
name: AI Review
on:
  pull_request:
    types: [opened, synchronize, reopened]
jobs:
  review:
    uses: 7391997393/ai-review-agentt/.github/workflows/reusable-ai-review.yml@main
    with:
      cg_model: gpt-oss-120b
      reopen_resolved_threads: true
    secrets:
      cg_api_key: ${{ secrets.CG_API_KEY }}
      gh_pat: ${{ secrets.GH_PAT }}
```

The workflow downloads the MCP binary, verifies its SHA-256, and sets `GITHUB_MCP_COMMAND`.
For production, pin `@main` and `agent_ref` to a tag or commit SHA.
