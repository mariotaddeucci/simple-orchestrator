# CLAUDE.md — `simple-orchestrator-webapi` (REST API)

Escopo: `packages/simple-orchestrator-webapi/`.

## Por que existe

- Expor o `IOrchestratorRepository` via REST (FastAPI) para modo distribuído.
- Ser um thin-layer: validação e roteamento; persistência delegada para `database`.

## Objetivo principal

- Manter paridade com `simple-orchestrator-core/src/.../api.py` e com `api-client`.

## Como será desenvolvido

- Endpoints devem trabalhar com os modelos do `core` (request/response).
- Evitar duplicar regras que já existem no repositório SQLite.

## Validação rápida

```bash
uv run --package simple-orchestrator-webapi pytest packages/simple-orchestrator-webapi/
```
