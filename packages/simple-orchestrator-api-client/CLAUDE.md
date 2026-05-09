# CLAUDE.md — `simple-orchestrator-api-client` (cliente HTTP)

Escopo: `packages/simple-orchestrator-api-client/`.

## Por que existe

- Permitir que `worker`/`tui` consumam o sistema via HTTP **sem mudar o código consumidor**.
- Implementar o mesmo contrato do repositório, só que chamando a `webapi`.

## Objetivo principal

- Paridade: mudanças em endpoints/shapes devem refletir aqui e na `webapi` (via `core/api.py`).

## Como será desenvolvido

- Mapear erros/transientes de rede sem “inventar” regras de negócio.
- Respeitar settings (URL, API key, timeouts).

## Validação rápida

```bash
uv run --package simple-orchestrator-api-client pytest packages/simple-orchestrator-api-client/
```
