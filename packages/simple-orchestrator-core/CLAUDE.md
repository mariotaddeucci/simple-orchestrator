# CLAUDE.md — `simple-orchestrator-core` (contrato)

Escopo: `packages/simple-orchestrator-core/`.

## Por que existe

- Ser a camada **compartilhada** por todos os outros pacotes.
- Definir contratos estáveis: modelos Pydantic, settings, validators e Protocols (`IOrchestratorRepository`).

## Objetivo principal

- Evoluir schemas com cuidado: mudanças aqui afetam `database`, `webapi`, `api-client`, `worker` e `tui`.

## Como será desenvolvido

- Preferir compatibilidade retroativa (ex.: coercions/validators para schemas legados).
- Shapes de API ficam em `core` para `webapi` e `api-client` validarem de forma idêntica.
- Protocols devem ser o tipo usado por consumidores (não implementar dependência em classes concretas).

## Onde mexer

- `src/simple_orchestrator_core/interfaces.py`: Protocols do repositório.
- `src/simple_orchestrator_core/models/`: modelos de domínio.
- `src/simple_orchestrator_core/api.py`: request/response da REST API.
- `src/simple_orchestrator_core/settings.py` e `validators.py`: carregamento e validação.

## Validação rápida

```bash
uv run --package simple-orchestrator-core pytest packages/simple-orchestrator-core/
```
