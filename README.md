# GitHub Actions Dependency Analyzer

A Python tool to analyze GitHub Actions workflows and their nested action dependencies (both local and remote).

## Features

- 📊 Analyzes all workflows in `.github/workflows/`
- 🔍 Follows nested dependencies in composite actions
- 🌐 Fetches and analyzes remote actions from GitHub
- 🔄 Detects dependency cycles
- 🔐 Supports GitHub token authentication (via environment variable or `gh` CLI)
- 📁 Can analyze any repository by specifying a path

## Installation

1. Install dependencies:
```bash
pip install requests pyyaml
```

Or use a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install requests pyyaml
```

## Usage

### Basic usage (current directory)
```bash
python actions_deps.py
```

### Analyze a specific repository
```bash
python actions_deps.py /path/to/repo
```

### With test samples
```bash
python actions_deps.py test
```

### Help
```bash
python actions_deps.py --help
```

## Authentication

The script will automatically use authentication in this order:
1. `GITHUB_TOKEN` environment variable
2. `gh auth token` (if GitHub CLI is installed and authenticated)
3. Unauthenticated (with rate limits)

To set a token manually:
```bash
export GITHUB_TOKEN='your_github_token'
```

Or authenticate with GitHub CLI:
```bash
gh auth login
```

## Example Output

```
Repo root: /path/to/repo
Workflows and their nested action dependencies (local + remote):

=== .github/workflows/build.yaml ===
  ↳ actions/checkout@abc123
  ↳ actions/setup-python@def456
  ↳ pre-commit/action@ghi789
      ↳ actions/cache@v4
  ↳ ./.github/actions/my-action
      ↳ actions/checkout@abc123
          ↳ [CYCLE] actions/checkout:@abc123
      ↳ actions/setup-node@jkl012
```

## Understanding the Output

- `↳` indicates a direct dependency
- Indented `↳` shows nested dependencies (e.g., actions used by composite actions)
- `[CYCLE]` indicates a dependency that was already analyzed (prevents infinite loops)
- Local actions (starting with `./`) are followed to show their dependencies

## Test Samples

The `test/` directory contains sample workflows demonstrating:
- Remote actions (from GitHub marketplace)
- Local composite actions (`.github/actions/`)
- Nested dependencies
- Reusable workflows

## License

MIT
