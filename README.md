AI Code Review Agent
An AI-powered, reusable Pull Request code-review agent that automatically analyzes code changes and provides actionable review findings directly on GitHub.
The application is designed as a central reusable AI Code Review Agent. Any GitHub repository can trigger the same central application through a small GitHub Actions workflow.
What This Project Does
When a Pull Request is opened, reopened, or updated:
GitHub Actions triggers the reusable AI Code Review workflow.
The central AI Review Agent receives the target repository and Pull Request details dynamically.
The application connects to GitHub through the official GitHub MCP Server.
GitHub MCP retrieves the Pull Request information and changed files/diff.
The AI reviewer analyzes the changes for: 
 
Security
Coding standards and maintainability
Testing
Performance
The Capgemini Generative Engine analyzes the supplied code changes.
Pydantic validates the structured AI response.
The findings are converted into an enterprise-friendly review format.
The agent posts the findings back to the Pull Request, including inline comments on relevant changed lines when a finding has a valid file and line location.
The final merge decision remains with the developer/reviewer.
The agent does not automatically modify code or merge Pull Requests.
Key Objective
The main goal is to build a reusable AI code-review service rather than a reviewer that is hard-coded for one repository.
The central application can be reused by different GitHub repositories.
                 Any GitHub Repository
                         |
                         | Pull Request
                         v
                 GitHub Actions
                         |
                         v
          Central AI Code Review Agent
              7391997393/ai-review-agentt
                         |
          +--------------+--------------+
          |                             |
          v                             v
    GitHub MCP Server          Capgemini Generative
          |                    Engine / LLM
          v                             |
    PR + Changed Files                  |
          |                             |
          +-------------+---------------+
                        |
                        v
                Pydantic Validation
                        |
                        v
              Review Findings
                        |
                        v
              GitHub PR Review
              + Inline Comments
Architecture
1. Target Repository
The target repository contains only a small caller workflow.
For example:
Target Repository
└── .github/
    └── workflows/
        └── ai-code-review.yml
The target repository does not contain the complete AI reviewer application.
2. Central AI Review Agent
The complete application is maintained centrally:
7391997393/ai-review-agentt
The central application contains the Python code, AI review logic, GitHub MCP integration, validation, formatting, tests, and reusable GitHub Actions workflow.
End-to-End Workflow
Developer changes code
        |
        v
Creates / updates Pull Request
        |
        v
GitHub Actions
        |
        v
Reusable AI Review Workflow
        |
        v
Central AI Review Agent
        |
        v
GitHub MCP Server
        |
        +---- PR details
        |
        +---- Changed files
        |
        +---- PR diff
        |
        v
AI Review
        |
        +---- Security
        +---- Standards / Code Quality
        +---- Tests
        +---- Performance
        |
        v
Capgemini Generative Engine
        |
        v
Pydantic Validation
        |
        v
Validated Findings
        |
        v
GitHub MCP
        |
        +---- PR review
        |
        +---- Inline comments
        |
        v
Developer reviews findings
        |
        v
Human makes merge decision
Technology Stack
TechnologyPurposePythonCore applicationGitHub ActionsPR-triggered automationGitHub Reusable WorkflowsMakes the central reviewer reusableGitHub MCP ServerGitHub operations through MCPMCPCommunication between the application and GitHub toolsLangChainLLM integration and structured outputLangGraphReview workflow orchestrationCapgemini Generative EngineAI code analysisPydanticStructured response validationDockerRuns the official GitHub MCP ServerpytestApplication testing
Review Categories
The agent evaluates Pull Request changes across four main areas.
1. Security
Examples:
Hard-coded passwords or secrets
Unsafe handling of sensitive information
Injection risks
Insecure coding practices
Authentication or authorization issues
2. Standards / Code Quality
Examples:
Poor naming
Maintainability problems
Duplicated logic
Unnecessary complexity
Poor coding practices
3. Tests
Examples:
Missing tests for new functionality
Weak test coverage
Missing edge-case testing
Incorrect or incomplete tests
4. Performance
Examples:
Unnecessary loops
Repeated expensive operations
Inefficient data processing
Avoidable resource usage
AI Finding Structure
Each finding contains structured information such as:
Category
Severity
File
Line
Title
Description
Recommendation
Confidence
Example:
HIGH — Security
 
Hard-coded password
 
Location: src/example.py:25
 
A password is stored directly in the source code.
 
Recommendation:
Move the credential to a secure environment variable or
secret-management system.
When a valid changed-file location is available, the finding can be posted as an inline Pull Request comment on the relevant changed line.
GitHub MCP Integration
The application uses the official GitHub MCP Server instead of directly implementing GitHub API operations throughout the application.
The MCP client communicates with GitHub through MCP tools.
The application uses GitHub MCP for operations such as:
Reading Pull Request information
Reading Pull Request diffs
Reading changed files
Creating Pull Request reviews
Adding review comments
The MCP server is configured with the required GitHub toolsets.
Capgemini Generative Engine
The AI reviewer uses the Capgemini Generative Engine through its OpenAI-compatible API.
The application uses:
CG_API_KEY
CG_MODEL
CG_BASE_URL
The API key is stored as a GitHub Actions secret.
The model and base URL are supplied through GitHub Actions configuration.
The application does not store the API key in source code.
Configuration
The central application expects:
CG_API_KEY
CG_MODEL
CG_BASE_URL
 
GITHUB_TOKEN
GITHUB_OWNER
GITHUB_REPO
PR_NUMBER
GitHub configuration
The GitHub token is provided securely through GitHub Actions.
The repository owner, repository name, and Pull Request number are obtained dynamically from the GitHub Actions caller context.
This keeps the application repository-independent.
Reusable GitHub Actions Workflow
The central repository contains:
.github/workflows/reusable-ai-review.yml
This is the only central workflow used for the reusable AI review process.
A target repository can call the central workflow instead of copying the complete application.
Example caller workflow:
name: AI Code Review
 
on:
  pull_request:
    types: [opened, synchronize, reopened]
 
permissions:
  contents: read
  pull-requests: write
 
jobs:
  ai-review:
    uses: 7391997393/ai-review-agentt/.github/workflows/reusable-ai-review.yml@main
    with:
      cg_model: ${{ vars.CG_MODEL }}
      cg_base_url: ${{ vars.CG_BASE_URL }}
    secrets:
      cg_api_key: ${{ secrets.CG_API_KEY }}
The target repository only needs this small workflow.
The complete AI review implementation remains in the central repository.
GitHub reusable workflows support defining inputs and secrets with workflow_call and passing them from the calling workflow.
Repository Independence
The application is designed to work with different repositories.
It does not hard-code:
spring-petclinic
or any other specific target repository.
Instead, GitHub Actions supplies:
GITHUB_OWNER
GITHUB_REPO
PR_NUMBER
at runtime.
Therefore the same central application can review Pull Requests from different repositories that call the reusable workflow.
Project Structure
ai-review-agentt/
│
├── .github/
│   └── workflows/
│       └── reusable-ai-review.yml
│
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── schemas.py
│   ├── prompts.py
│   ├── mcp_github.py
│   ├── reviewer.py
│   ├── graph.py
│   └── formatter.py
│
├── tests/
│   └── test_formatter.py
│
├── docs/
│
├── .env.example
├── .gitignore
├── main.py
├── pytest.ini
├── requirements.txt
└── README.md
Main Components
main.py
Application entry point.
It:
Loads configuration
Determines the Pull Request
Connects to GitHub MCP
Retrieves Pull Request context
Runs the AI review graph
Formats the findings
Sends the findings back to GitHub
src/config.py
Loads and validates application configuration from environment variables.
src/mcp_github.py
Provides the GitHub MCP client used to communicate with the official GitHub MCP Server.
src/reviewer.py
Connects the application to the Capgemini Generative Engine and obtains structured AI review findings.
src/prompts.py
Contains the review instructions used for the different review categories.
src/schemas.py
Defines Pydantic models for validating AI-generated findings.
src/graph.py
Defines the LangGraph review workflow.
src/formatter.py
Converts validated findings into the GitHub review format.
Local Development
Clone the central application:
git clone https://github.com/7391997393/ai-review-agentt.git
cd ai-review-agentt
Create a virtual environment:
python -m venv .venv
Windows:
.venv\Scripts\activate
Install dependencies:
pip install -r requirements.txt
Create the environment file:
copy .env.example .env
Configure the required environment variables.
Run the application:
python main.py
Testing
Run:
python -m pytest -q
The test suite validates important application behavior such as review formatting.
Security
Repository content is treated as untrusted input.
Pull Request descriptions, comments, and source code may contain prompt-injection instructions.
The AI reviewer should treat repository content as code/data to analyze, not as instructions that can override the review policy.
The GitHub MCP Server should be restricted to the toolsets required by the application.
API keys and tokens must never be committed to the repository.
What the Agent Does Not Do
The agent provides recommendations.
It does not:
Automatically modify the developer's code
Automatically merge Pull Requests
Automatically approve Pull Requests
Replace human code review
Store API keys in source code
The developer/reviewer remains responsible for deciding whether a finding is valid and whether the Pull Request should be merged.
Demo Flow
For demonstration, an external/open-source repository can be used as the target repository.
Example:
Open-source repository
        |
        v
Create a Pull Request with intentionally problematic code
        |
        v
GitHub Actions triggers
        |
        v
Central AI Review Agent
        |
        v
GitHub MCP retrieves the PR/diff
        |
        v
Capgemini Generative Engine analyzes the changes
        |
        v
Security / Standards / Tests / Performance findings
        |
        v
Pydantic validation
        |
        v
GitHub PR review + inline comments
 
The external repository is only the target being reviewed. It is not part of the central AI Review Agent application.
---
30-Second Project Explanation
> This project is a reusable AI-based Pull Request code-review agent. GitHub Actions triggers the central application whenever a Pull Request is opened or updated. The application uses the official GitHub MCP Server to retrieve the Pull Request and changed code. LangGraph and LangChain coordinate the AI review, while the Capgemini Generative Engine analyzes the changes for security, standards, testing, and performance issues. Pydantic validates the structured response, and the agent posts actionable findings and inline comments back to GitHub. The solution is reusable because the target repository, owner, and Pull Request number are supplied dynamically by the calling workflow.
---
Future Improvements
Possible future enhancements include:
More programming-language-specific review rules
Improved duplicate-comment detection
Better changed-line mapping
Additional review categories
Review history and tracking
Configurable severity thresholds
Enterprise authentication and policy controls
Improved test coverage
---
License
This project is intended as an AI Code Review Agent proof of concept