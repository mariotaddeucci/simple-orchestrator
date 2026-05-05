"""Slash command prompts for simple-orchestrator.

Prompts are markdown files stored in the prompts/ directory at the repository root.
Each file has a YAML-style frontmatter with name and description, followed by the prompt content.

Example prompt file::

    # Security Auditor

    ## Role

    You are a senior application security engineer...

The first H1 header becomes the prompt name (or filename if no H1 is present).
The content following the first header becomes the description (extracted from next paragraph).
The entire file content becomes the prompt template.

Use :func:`list_prompt_names` to discover available prompts and
:func:`get_prompt_content` to retrieve a prompt's full content.
"""

from pathlib import Path

# Prompts directory is at repository root, not in the package
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_PROMPTS_DIR = _REPO_ROOT / "prompts"


def list_prompt_names() -> list[str]:
    """Return the names of all available prompt files.

    Returns
    -------
    list[str]
        List of prompt identifiers (filenames without .md extension).
    """
    if not _PROMPTS_DIR.exists():
        return []

    return sorted(p.stem for p in _PROMPTS_DIR.glob("*.md") if p.is_file())


def get_prompt_path(name: str) -> Path:
    """Return the absolute path to a prompt file.

    Parameters
    ----------
    name
        Prompt identifier (filename without .md extension).

    Returns
    -------
    Path
        Absolute path to the prompt file.

    Raises
    ------
    ValueError
        If the prompt name is not found.
    FileNotFoundError
        If the prompt file doesn't exist.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        available = list_prompt_names()
        if available:
            known = ", ".join(f'"{n}"' for n in available)
            raise ValueError(f"Unknown prompt {name!r}. Available prompts: {known}.")
        raise FileNotFoundError(f"Prompts directory is empty or does not exist: {_PROMPTS_DIR}")
    return path


def get_prompt_content(name: str) -> str:
    """Read and return the full content of a prompt file.

    Parameters
    ----------
    name
        Prompt identifier (filename without .md extension).

    Returns
    -------
    str
        Full prompt content.

    Raises
    ------
    ValueError
        If the prompt name is not found.
    FileNotFoundError
        If the prompt file doesn't exist.
    """
    path = get_prompt_path(name)
    return path.read_text(encoding="utf-8")


def parse_prompt_metadata(content: str) -> tuple[str, str]:
    """Extract title and description from prompt content.

    Parameters
    ----------
    content
        Full prompt file content.

    Returns
    -------
    tuple[str, str]
        (title, description) where:
        - title is extracted from first H1 header (# Title) or empty string
        - description is extracted from first paragraph after title or empty string
    """
    lines = content.splitlines()
    title = ""
    description = ""

    # Find first H1 header
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            title = stripped[2:].strip()
            # Look for first non-empty paragraph after title
            for j in range(i + 1, len(lines)):
                candidate = lines[j].strip()
                # Skip empty lines and headers
                if not candidate or candidate.startswith("#"):
                    continue
                # Found first paragraph
                description = candidate[:200]  # Limit to 200 chars
                break
            break

    return title, description
