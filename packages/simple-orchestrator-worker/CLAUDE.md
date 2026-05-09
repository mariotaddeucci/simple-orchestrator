# CLAUDE.md — `simple-orchestrator-worker` (fila + vendors)

Escopo: `packages/simple-orchestrator-worker/`.

## Por que existe

- Rodar a fila (dequeue/dispatch) com paralelismo controlado.
- Implementar vendors (Claude Code, OpenCode, GitHub Copilot) e o ciclo de vida de sessões.

## Objetivo principal

- Execução robusta: concorrência, serialização por `workdir`, cancelamento, timeouts e logs.

## Como será desenvolvido

- Código vendor-specific fica em `vendors/`; evitar espalhar detalhes de vendor pelo runner.
- Integração com WebAPI (heartbeat, dequeue) deve manter shapes do `core`.
- Testes de integração que dependem de autenticação real devem ser marcados/auto-skipados em CI.

## Validação rápida

```bash
uv run --package simple-orchestrator-worker pytest packages/simple-orchestrator-worker/
```
