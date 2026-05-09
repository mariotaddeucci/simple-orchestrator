# CLAUDE.md — `simple-orchestrator-tui` (Textual UI)

Scope: `packages/simple-orchestrator-tui/`.

## Why it exists

- Terminal interface for queueing and monitoring sessions.
- Consume the repository without coupling to implementations.

## Main goal

- Predictable and stable UX; keep the TUI as a consumer (no persistence logic here).

## Development guidelines

- Avoid direct dependency on `database`/SQL; use the injected repository.
- Flow changes must be validated by running the TUI against the chosen mode.

## Quick validation

This package is normally validated via manual TUI execution; when tests exist, prefer running them per package.
