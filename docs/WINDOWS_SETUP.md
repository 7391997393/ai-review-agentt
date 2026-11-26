# Windows setup without Docker

The agent talks to GitHub through the official GitHub MCP Server. On Windows you run
that server as a standalone `.exe`. Docker is not needed.

Where it is launched: `resolve_mcp_launch()` in `src/mcp_github.py`, controlled by
`GITHUB_MCP_COMMAND`.

## 1. Install the binary

The version below matches the one the agent is tested with (`v2.0.3`).

```powershell
$dir = "C:\tools\github-mcp-server"
New-Item -ItemType Directory -Force $dir | Out-Null
$base = "https://github.com/github/github-mcp-server/releases/download/v2.0.3"
Invoke-WebRequest "$base/github-mcp-server_Windows_x86_64.zip" -OutFile "$dir\mcp.zip"
Invoke-WebRequest "$base/github-mcp-server_2.0.3_checksums.txt" -OutFile "$dir\checksums.txt"

# Verify the download against the published checksum.
$expected = (Select-String "$dir\checksums.txt" -Pattern "Windows_x86_64.zip").Line.Split()[0]
$actual = (Get-FileHash "$dir\mcp.zip" -Algorithm SHA256).Hash.ToLower()
if ($expected -ne $actual) { throw "Checksum mismatch" } else { "Checksum OK" }

Expand-Archive "$dir\mcp.zip" -DestinationPath $dir -Force
& "$dir\github-mcp-server.exe" --version
```

On an ARM laptop use `Windows_arm64.zip` instead. If downloads from github.com are
blocked, download the zip in a browser and place it in `C:\tools\github-mcp-server`.

## 2. Create the GitHub token

Create a personal access token that can reach the repository you want reviewed.
Fine-grained: select the repository, with **Pull requests: Read and write** and
**Contents: Read and write**. (Classic token: `repo` scope.)

Why Contents write: a live test showed that with Contents set to Read, posting reviews
works but resolving threads fails with `Resource not accessible by personal access token`.
GitHub appears to require Contents write for the `resolveReviewThread` mutation even though
resolving changes no files. The agent never writes repository contents. The run then exits
with code 1 and lists each thread it could not resolve.

## 3. Configure `.env`

```powershell
Copy-Item .env.example .env
```

Set at least these values (the token stays only in `.env`, which is gitignored):

```dotenv
CG_API_KEY=<your Capgemini key>
CG_MODEL=gpt-oss-120b
GITHUB_TOKEN=<your PAT>
GITHUB_OWNER=<repository owner>
GITHUB_REPO=<repository name>
PR_NUMBER=<pull request number>
GITHUB_MCP_COMMAND=C:\tools\github-mcp-server\github-mcp-server.exe
REOPEN_RESOLVED_THREADS=true
```

`GITHUB_MCP_COMMAND` accepts a full path (quotes optional). If you leave it empty, the
agent uses Docker when installed and otherwise looks for `github-mcp-server` on `PATH`.
Docker users can set it to `docker`; nothing else changes.

## 4. Install Python dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 5. Check connectivity (read-only)

```powershell
python verify_setup.py
```

Expected output:

```text
[PASS] Environment variables: ...
[PASS] MCP launcher resolved: C:\tools\github-mcp-server\github-mcp-server.exe
[PASS] MCP session initialised
[PASS] Required MCP tools
[PASS] GitHub token valid: acting as <your login>
[PASS] Repository access: <owner>/<repo>
[PASS] Pull request #<n> readable via MCP: <k> file(s)
```

To test the binary on its own, run it by hand. It waits for MCP messages on stdin,
so seeing no output and no error means it started; press Ctrl+C to stop.

```powershell
$env:GITHUB_PERSONAL_ACCESS_TOKEN = "<your PAT>"
& "C:\tools\github-mcp-server\github-mcp-server.exe" stdio --toolsets=repos,pull_requests,issues
```

## 6. Run a full review

```powershell
python main.py
```

The run: read the PR through MCP, ask the model for findings, resolve this agent's
outdated threads, skip findings that already have a thread, post the rest as one
review with inline comments.

## 7. Validation checklist

Use a scratch pull request that adds a hard-coded password and a SQL string built from
user input.

| # | Proof | How to check | Expected |
|---|-------|--------------|----------|
| 1 | MCP connection works | `python verify_setup.py` | `MCP session initialised` and `Required MCP tools` pass |
| 2 | Repository access works | same command | `GitHub token valid` and `Repository access` pass; PR read passes with `PR_NUMBER` set |
| 3 | PR comments are created | `python main.py` on the scratch PR | Log: `Review submitted: N finding(s), M inline comment(s)`; the PR shows a review plus inline comments; exit code 0 (`$LASTEXITCODE`) |
| 4 | Duplicates are not generated | run `python main.py` again with no code change | Log: `No new findings to publish (N duplicate(s) skipped)`; no new review on the PR |
| 5 | Threads are resolved | fix the flagged lines, push, run `python main.py` | Log: `Resolved thread <id> (thread is outdated by code changes)`; the threads show as resolved on GitHub |
| 6 | Resolved threads reopen (optional) | with `REOPEN_RESOLVED_THREADS=true`, reintroduce a flaw on the same line and title, run | Log: `Reopened thread ...` |

How resolution works: the agent resolves only its own threads, and only when GitHub
marks them outdated because the code changed. A flaw that is still present is never
resolved just because the model did not repeat it. A fix that leaves the old line
untouched will not mark the thread outdated, so edit the flagged line itself.

## Troubleshooting

| Message | Cause and fix |
|---------|---------------|
| `GitHub MCP server binary not found` | Wrong `GITHUB_MCP_COMMAND`; use the full path to the `.exe`. |
| `GitHub GraphQL HTTP error 401` | Bad or expired token. |
| `Resource not accessible by personal access token` | The token lacks pull-request write access on that repo. |
| `GITHUB_OWNER and GITHUB_REPO are required` | Set both in `.env`. |
| Antivirus or AppLocker blocks the `.exe` | Ask IT to allow `C:\tools\github-mcp-server`. |
