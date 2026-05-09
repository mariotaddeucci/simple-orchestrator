# CLAUDE.md — `simple-orchestrator` (CLI / wiring)

Escopo: `packages/simple-orchestrator/` (este guia é usado via `AGENTS.md` → symlink).

## Por que existe

- Fornecer entrypoints/CLI para iniciar `worker` e `webapi`.
- Centralizar o “wiring” (settings + DI) sem acoplar consumidores a implementações concretas.

## Objetivo principal

- Garantir que executar via CLI configure corretamente: settings, repositório (SQLite direto ou HTTP) e logging.

## Como será desenvolvido

- Manter subcomandos simples (parse/dispatch) e empurrar regras de negócio para os pacotes especializados.
- Alterações aqui geralmente implicam documentação de CLI e validação end-to-end com comandos de execução.

## Validação rápida

```bash
uv run ruff check packages/simple-orchestrator/
uv run ruff format packages/simple-orchestrator/
```
