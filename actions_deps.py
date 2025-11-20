#!/usr/bin/env python3
"""
GitHub Actions Dependency Analyzer
Analyzes workflows and actions to show their nested dependencies.
"""
import argparse
import base64
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
import yaml

# --------- CONFIG ---------


def get_github_token() -> Optional[str]:
    """Get GitHub token from environment or gh CLI."""
    if token := os.getenv("GITHUB_TOKEN"):
        return token

    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and (token := result.stdout.strip()):
            return token
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return None


GITHUB_TOKEN = get_github_token()
GITHUB_API_URL = "https://api.github.com"

# --------- CACHES ---------

local_yaml_cache: Dict[Path, Any] = {}
remote_yaml_cache: Dict[Tuple[str, str, str, str], Any] = {}
VisitedKey = str

# --------- LOCAL FILE HELPERS ---------


def load_local_yaml(path: Path) -> Any:
    if path in local_yaml_cache:
        return local_yaml_cache[path]
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    local_yaml_cache[path] = data
    return data


def find_all_workflows(repo_root: Path) -> List[Path]:
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.exists():
        return []
    return sorted(p for p in workflows_dir.glob("*.y*ml") if p.is_file())


def find_all_local_actions(repo_root: Path) -> List[Path]:
    """Find all local action.yml/action.yaml files in .github/actions/"""
    actions_dir = repo_root / ".github" / "actions"
    if not actions_dir.exists():
        return []

    action_files = []
    for action_yml in actions_dir.rglob("action.y*ml"):
        if action_yml.is_file():
            action_files.append(action_yml)
    return sorted(action_files)


def is_local_path(uses: str) -> bool:
    # e.g. "./.github/actions/foo", ".github/workflows/bar.yml"
    return uses.startswith("./") or uses.startswith(".github/")


def resolve_local_path(uses: str, repo_root: Path) -> Path:
    """
    Resolve a local `uses:` path to a file (action.yml or workflow yml).
    """
    # Remove leading ./ if present
    if uses.startswith("./"):
        raw = uses[2:]
    else:
        raw = uses

    candidate = repo_root / raw

    if candidate.is_dir():
        # Probably a composite action dir; look for action.{yml,yaml}
        for name in ("action.yml", "action.yaml"):
            candidate_file = candidate / name
            if candidate_file.exists():
                return candidate_file
    elif candidate.is_file():
        # Could be a workflow file directly
        return candidate

    raise FileNotFoundError(f"Cannot resolve local uses path: {uses} -> {candidate}")


# --------- REMOTE FILE HELPERS ---------


def parse_remote_uses(uses: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse remote `uses` string like:
      - owner/repo@ref
      - owner/repo/path/to/action@ref
    into (owner, repo, path, ref).

    Returns None if not a remote GitHub repo reference.
    """
    if "@" not in uses:
        return None
    before, ref = uses.rsplit("@", 1)
    if "/" not in before:
        return None

    owner, rest = before.split("/", 1)
    parts = rest.split("/")
    repo = parts[0]
    path = "/".join(parts[1:])  # may be ""

    return owner, repo, path, ref


def github_api_get(
    url: str, *, params: Optional[Dict[str, str]] = None
) -> requests.Response:
    headers = {
        "Accept": "application/vnd.github.v3+json",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    resp = requests.get(url, headers=headers, params=params or {})
    resp.raise_for_status()
    return resp


def load_remote_yaml(owner: str, repo: str, path: str, ref: str) -> Tuple[str, Any]:
    """
    Fetch and parse a remote YAML file from a GitHub repo.

    `path` may be:
      - "" (meaning repo root, we’ll try action.yml / action.yaml)
      - a directory (we’ll try <path>/action.yml, <path>/action.yaml)
      - a file like ".github/workflows/build.yml"

    Returns (resolved_path, yaml_data).
    """
    cache_key = (owner, repo, path or "", ref)
    if cache_key in remote_yaml_cache:
        # We stored (resolved_path, data) here
        return remote_yaml_cache[cache_key]

    candidate_paths: List[str] = []

    if not path:
        candidate_paths = ["action.yml", "action.yaml"]
    else:
        if path.endswith(".yml") or path.endswith(".yaml"):
            candidate_paths = [path]
        else:
            # Try .yml first as it's more common
            candidate_paths = [f"{path}/action.yml", f"{path}/action.yaml"]

    last_err: Optional[Exception] = None

    for candidate in candidate_paths:
        url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{candidate}"
        try:
            resp = github_api_get(url, params={"ref": ref})
        except requests.HTTPError as e:
            last_err = e
            continue

        data = resp.json()
        # contents API for file returns { content: base64, ... }
        if isinstance(data, dict) and data.get("type") == "file":
            content_b64 = data.get("content", "")
            content = base64.b64decode(content_b64)
            yaml_data = yaml.safe_load(content)
            remote_yaml_cache[cache_key] = (candidate, yaml_data)
            return candidate, yaml_data

    raise RuntimeError(
        f"Could not fetch remote YAML for {owner}/{repo} path={path!r} ref={ref!r}; "
        f"last error: {last_err}"
    )


# --------- COMMON YAML PARSING ---------


def extract_uses_from_steps(steps: List[Dict[str, Any]]) -> List[str]:
    uses_refs: List[str] = []
    if not steps:
        return uses_refs
    for step in steps:
        if isinstance(step, dict) and "uses" in step:
            uses_refs.append(step["uses"])
    return uses_refs


def extract_uses_from_workflow(doc: Dict[str, Any]) -> List[str]:
    uses_refs: List[str] = []
    jobs = doc.get("jobs", {}) or {}
    for _, job in jobs.items():
        if not isinstance(job, dict):
            continue

        # Reusable workflow call
        if "uses" in job:
            uses_refs.append(job["uses"])

        # Normal steps
        steps = job.get("steps", [])
        uses_refs.extend(extract_uses_from_steps(steps))
    return uses_refs


def extract_uses_from_action(doc: Dict[str, Any]) -> List[str]:
    runs = doc.get("runs", {}) or {}
    steps = runs.get("steps", [])
    return extract_uses_from_steps(steps)


def classify_doc(doc: Any, *, path_hint: Optional[str] = None) -> str:
    """
    Classify parsed YAML document as:
      - 'workflow'
      - 'composite_action'
      - 'unknown'
    """
    if not isinstance(doc, dict):
        return "unknown"

    # Composite action: has runs
    if "runs" in doc:
        return "composite_action"

    # Workflow: has 'on' (or True, since YAML parses 'on' as boolean) and 'jobs'
    # Note: YAML spec treats 'on' as a boolean True
    if ("on" in doc or True in doc) and "jobs" in doc:
        # path_hint like ".github/workflows/ci.yml" is a good sign
        if path_hint and ".github/workflows/" in path_hint:
            return "workflow"
        return "workflow"

    return "unknown"


def extract_uses_from_local(path: Path) -> List[str]:
    doc = load_local_yaml(path) or {}
    kind = classify_doc(doc, path_hint=str(path))
    if kind == "workflow":
        return extract_uses_from_workflow(doc)
    elif kind == "composite_action":
        return extract_uses_from_action(doc)
    else:
        return []


def extract_uses_from_remote(owner: str, repo: str, path: str, ref: str) -> List[str]:
    resolved_path, doc = load_remote_yaml(owner, repo, path, ref)
    kind = classify_doc(doc, path_hint=resolved_path)
    if kind == "workflow":
        return extract_uses_from_workflow(doc)
    elif kind == "composite_action":
        return extract_uses_from_action(doc)
    else:
        return []


# --------- TREE PRINTING ---------


def print_tree_local(
    path: Path, repo_root: Path, prefix: str, visited: Set[VisitedKey]
) -> None:
    key: VisitedKey = f"local:{path}"
    if key in visited:
        print(f"{prefix}↳ [CYCLE] {path.relative_to(repo_root)}")
        return
    visited.add(key)

    uses_refs = extract_uses_from_local(path)

    for uses in uses_refs:
        print(f"{prefix}↳ {uses}")

        # Follow local uses
        if is_local_path(uses):
            try:
                target = resolve_local_path(uses, repo_root)
            except FileNotFoundError as e:
                print(f"{prefix}    [WARN] {e}")
                continue
            print_tree_local(target, repo_root, prefix + "    ", visited)
            continue

        # Follow remote uses
        remote = parse_remote_uses(uses)
        if remote:
            owner, repo, rpath, ref = remote
            print_tree_remote(owner, repo, rpath, ref, prefix + "    ", visited)


def print_tree_remote(
    owner: str,
    repo: str,
    path: str,
    ref: str,
    prefix: str,
    visited: Set[VisitedKey],
) -> None:
    # Identify this remote file by resolved path once fetched
    key_base = f"remote:{owner}/{repo}:{path or ''}@{ref}"

    if key_base in visited:
        print(f"{prefix}↳ [CYCLE] {owner}/{repo}:{path or ''}@{ref}")
        return

    # Try to fetch YAML and classify/extract uses
    try:
        resolved_path, doc = load_remote_yaml(owner, repo, path, ref)
    except Exception:
        # Silently skip - likely a JS/Docker action without nested dependencies
        return

    visited.add(key_base)
    kind = classify_doc(doc, path_hint=resolved_path)

    if kind not in ("workflow", "composite_action"):
        # Check if it's a JS/Docker/container action
        if isinstance(doc, dict) and "runs" in doc:
            runs = doc.get("runs", {})
            if isinstance(runs, dict):
                using = runs.get("using", "")
                if using in ("node12", "node16", "node20", "docker"):
                    # JS or Docker action - show the type
                    print(f"{prefix}    [{using} action]")
                    return
        # Unknown type, nothing more to do
        return

    uses_refs = []
    if kind == "workflow":
        uses_refs = extract_uses_from_workflow(doc)
    elif kind == "composite_action":
        uses_refs = extract_uses_from_action(doc)

    for uses in uses_refs:
        print(f"{prefix}↳ {uses}")

        # Remote workflows and composite actions can point to:
        # - local relative paths (rare, but we’ll ignore because we don’t have their repo)
        # - other remote actions
        remote2 = parse_remote_uses(uses)
        if remote2:
            o2, r2, p2, ref2 = remote2
            print_tree_remote(o2, r2, p2, ref2, prefix + "    ", visited)


# --------- MAIN ---------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze GitHub Actions workflows and their nested action dependencies"
    )
    parser.add_argument(
        "repo_path",
        nargs="?",
        default=".",
        help="Path to repository root (containing .github folder). Defaults to current directory.",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_path).resolve()

    if not repo_root.exists():
        print(f"Error: Path does not exist: {repo_root}")
        sys.exit(1)

    if not repo_root.is_dir():
        print(f"Error: Path is not a directory: {repo_root}")
        sys.exit(1)

    workflows = find_all_workflows(repo_root)
    local_actions = find_all_local_actions(repo_root)

    if not workflows and not local_actions:
        print(f"No workflows or actions found under {repo_root / '.github'}")
        sys.exit(0)

    if not GITHUB_TOKEN:
        print(
            "NOTE: GITHUB_TOKEN not set. "
            "You may hit rate limits or be unable to read private repos.\n"
        )

    print(f"Repo root: {repo_root}")
    print("Workflows and their nested action dependencies (local + remote):\n")

    for wf in workflows:
        rel = wf.relative_to(repo_root)
        print(f"=== {rel} ===")
        visited: Set[VisitedKey] = set()
        print_tree_local(wf, repo_root, prefix="  ", visited=visited)
        print()

    if local_actions:
        print("\nLocal actions (not necessarily referenced):\n")
        for action in local_actions:
            action_dir = action.parent.relative_to(repo_root)
            print(f"=== {action_dir} ===")
            action_visited: Set[VisitedKey] = set()
            print_tree_local(action, repo_root, prefix="  ", visited=action_visited)
            print()


if __name__ == "__main__":
    main()
