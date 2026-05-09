# CLAUDE.md — `simple-orchestrator-core` (contract)

Scope: `packages/simple-orchestrator-core/`.

## Why it exists

- Be the **shared layer** imported by all other packages.
- Define stable contracts: Pydantic models, settings, validators, and Protocols (`IOrchestratorRepository`).

## Main goal

- Evolve schemas carefully: changes here affect `database`, `webapi`, `api-client`, `worker`, and `tui`.

## Development guidelines

- Prefer backwards compatibility (e.g., coercions/validators for legacy schemas).
- API shapes live in `core` so `webapi` and `api-client` validate identically.
- Protocols must be the type used by consumers (do not couple to concrete classes).
- `Literal` types must NOT be used as SQLModel table field types — use `str` and validate at the API layer.

## Where to make changes

- `src/simple_orchestrator_core/interfaces.py`: repository Protocols.
- `src/simple_orchestrator_core/models/`: domain models.
- `src/simple_orchestrator_core/api.py`: REST API request/response shapes.
- `src/simple_orchestrator_core/schedule.py`: `compute_next_run()` for interval/cron scheduling.
- `src/simple_orchestrator_core/settings.py` and `validators.py`: settings loading and validation.

## Quick validation

```bash
uv run --package simple-orchestrator-core pytest packages/simple-orchestrator-core/
```
