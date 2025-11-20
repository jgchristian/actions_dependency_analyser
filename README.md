# GitHub Actions Dependency Analyzer

A Python tool to analyze GitHub Actions workflows and their nested action dependencies (both local and remote).

## Features

- 📊 Analyzes all workflows in `.github/workflows/`
- 📁 Discovers all local actions in `.github/actions/` (even if not referenced)
- 🔍 Follows nested dependencies in composite actions
- 🌐 Fetches and analyzes remote actions from GitHub
- 🔄 Detects dependency cycles
- 🔐 Auto-detects GitHub token (from environment or `gh` CLI)
- 📂 Can analyze any repository by path

## Installation

```bash
pip install requests pyyaml
```

Or with a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install requests pyyaml
```

## Usage

```bash
# Analyze current directory
python actions_deps.py

# Analyze specific repository
python actions_deps.py /path/to/repo

# Analyze test samples
python actions_deps.py test

# Show help
python actions_deps.py --help
```

## Authentication

Auto-detects in order:

1. `GITHUB_TOKEN` environment variable
2. `gh auth token` (if GitHub CLI installed)
3. Unauthenticated (rate limited)

Manual setup:

```bash
export GITHUB_TOKEN='your_token'
# or
gh auth login
```

## Example Output

```text
Repo root: /path/to/repo
Workflows and their nested action dependencies (local + remote):

=== .github/workflows/build.yaml ===
  ↳ actions/checkout@abc123
  ↳ actions/setup-python@v5
  ↳ pre-commit/action@def456
      ↳ actions/cache@v4
  ↳ ./.github/actions/my-action
      ↳ actions/checkout@abc123
          ↳ [CYCLE] actions/checkout:@abc123

Local actions (not necessarily referenced):

=== .github/actions/my-action ===
  ↳ actions/checkout@abc123
  ↳ actions/setup-node@ghi789
```

## Output Explained

- `↳` - Direct dependency
- Indented `↳` - Nested dependency (used by composite actions)
- `[CYCLE]` - Already analyzed (prevents infinite loops)
- Local actions starting with `./` are followed recursively

## Test Samples

The `test/` directory contains sample workflows demonstrating:

- Remote actions from GitHub Marketplace
- Local composite actions
- Nested dependencies
- Dependency cycles

## Use Case

This tool helps identify hidden dependencies in GitHub Actions, particularly useful when:

- Your organization restricts actions to specific SHAs
- You need to audit all action dependencies
- Composite actions use unpinned or unapproved actions
- You want to discover all actions in a repository

## License

MIT
