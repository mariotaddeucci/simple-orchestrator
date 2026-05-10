from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path


def git_cache_dir(remote: str, cache_base: Path) -> Path:
    """Stable clone directory for a given git remote."""
    normalized = remote.strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return cache_base / digest


def resolve_workdir(workdir: str | None, cache_base: Path) -> str | None:
    """Resolve workdir from (git remote | None) into a local directory path.

    - None -> None (caller may create a temp dir for the session)
    - git remote -> ensure cached clone exists and return its path
    """
    if workdir is None:
        return None

    remote = workdir.strip()
    if not remote:
        raise ValueError("workdir must not be empty")

    if _looks_like_local_path(remote):
        # Internal callers (and tests) may pass an already-resolved local path.
        return remote

    repo_dir = git_cache_dir(remote, cache_base)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if not repo_dir.exists():
        _run_git(["clone", remote, str(repo_dir)])
        return str(repo_dir)

    if not is_git_worktree(repo_dir):
        raise ValueError(f"workdir cache directory exists but is not a git repository: {repo_dir}")

    return str(repo_dir)


def _looks_like_local_path(v: str) -> bool:
    if v.startswith(("/", "./", "../", "~")):
        return True
    # Windows drive letter path (e.g. C:\repo)
    return len(v) >= 3 and v[1] == ":" and v[2] in ("\\", "/") and v[0].isalpha()


def _run_git(args: list[str], *, cwd: Path | None = None) -> None:
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=str(cwd) if cwd else None,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def is_git_worktree(path: Path | str) -> bool:
    path = Path(path)
    try:
        subprocess.run(  # noqa: S603
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return False
    return True
