# CLAUDE.md — `simple-orchestrator-tui` (Textual UI)

Escopo: `packages/simple-orchestrator-tui/`.

## Por que existe

- Interface terminal para enfileirar/monitorar sessões.
- Consumir o repositório (SQLite direto ou HTTP via `api-client`) sem acoplamento a implementações.

## Objetivo principal

- UX previsível e estável; manter a TUI como cliente (sem regras de persistência aqui).

## Como será desenvolvido

- Evitar dependência direta em `database`/SQL; usar o repositório injetado.
- Mudanças de fluxo devem ser validadas rodando a TUI contra o modo escolhido.

## Validação rápida

Este pacote tende a ser validado via execução manual da TUI; quando houver testes, preferir rodá-los por pacote.
