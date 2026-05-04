"""Built-in skills shipped with simple-orchestrator.

Use :func:`get_skill_path` to resolve the absolute path of a bundled skill file,
or :func:`list_skill_names` to enumerate all available skill names.

Bundled skills
--------------
- ``queue-tasks``    — how to add and monitor tasks in the orchestrator queue.
- ``memory-tool``    — how to save, list, retrieve, and delete agent memories.
- ``task-executor``  — how to read the current task and record a session note (for executing agents).

Example (Python)::

    from simple_orchestrator.skills import get_skill_path
    skill_path = get_skill_path("queue-tasks")
"""

from pathlib import Path

_SKILLS_DIR = Path(__file__).parent
_SKILL_NAMES = ("queue-tasks", "memory-tool", "task-executor")


def list_skill_names() -> tuple[str, ...]:
    """Return the names of all built-in skills."""
    return _SKILL_NAMES


def get_skill_path(name: str) -> Path:
    """Return the absolute :class:`~pathlib.Path` to a built-in skill file.

    Parameters
    ----------
    name:
        Skill name, e.g. ``"queue-tasks"``.

    Raises
    ------
    ValueError
        If *name* is not a known built-in skill.
    FileNotFoundError
        If the skill file is unexpectedly missing from the installed package.
    """
    if name not in _SKILL_NAMES:
        known = ", ".join(f'"{n}"' for n in _SKILL_NAMES)
        raise ValueError(f"Unknown built-in skill {name!r}. Known skills: {known}.")

    path = _SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"Built-in skill file not found: {path}")
    return path
