# CLAUDE.md — `simple-orchestrator-database` (SQLite / repositório)

Escopo: `packages/simple-orchestrator-database/`.

## Por que existe

- Implementar `IOrchestratorRepository` com SQLite (SQLModel/SQLAlchemy sync).
- Ser o backend único para o modo standalone e para a `webapi` no modo distribuído.

## Objetivo principal

- Persistência correta: atomicidade (claim/dequeue), consistência de status e retenção/cleanup.

## Como será desenvolvido

- Evitar lógica de HTTP aqui (isso é papel de `webapi` / `api-client`).
- Mudanças em schema/queries devem acompanhar atualizações em `core` (modelos/validators).
- Manter comportamento estável para dependências (`depends_on`) e cleanup de itens antigos.

## Validação rápida

Este pacote normalmente é validado indiretamente pelos testes da `webapi` e do `worker`:

```bash
uv run --package simple-orchestrator-webapi pytest packages/simple-orchestrator-webapi/
uv run --package simple-orchestrator-worker pytest packages/simple-orchestrator-worker/
```
