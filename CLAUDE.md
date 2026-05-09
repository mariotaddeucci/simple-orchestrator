# CLAUDE.md (root)

Guia do repositório para agentes (Claude Code / Codex CLI).

Este arquivo é **conceitual e curto**. Detalhes práticos ficam no `CLAUDE.md` de cada pacote.
Observação: `AGENTS.md` na raiz é um symlink para este arquivo.

## Objetivo

- Orquestrar execução assíncrona de agentes IA em background (multi-vendor).
- Persistir fila/sessões/memória em SQLite.
- Rodar em **standalone** (SQLite direto) ou **distribuído** (WebAPI + API client).

## Princípios de arquitetura

- `simple-orchestrator-core` é o **contrato**: modelos Pydantic, Protocols e shapes de API.
- Todo o resto depende de `core` (não o inverso).
- `database` implementa `IOrchestratorRepository` (SQLite) e é usado por `webapi`.
- `api-client` implementa o mesmo repositório via HTTP para manter o consumo idêntico.
- `worker` contém execução e vendors; `tui` é cliente do repositório (DB direto ou HTTP).

## Como trabalhar (comandos)

Use sempre `uv` (não ative venv manualmente):

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format .
uv run pyrefly check
```

Rodar o sistema:

```bash
uv run simple-orchestrator worker
uv run simple-orchestrator webapi
uv run simple-orchestrator-tui
```

Testes rodam por pacote (cada um tem seu `pyproject.toml`):

```bash
uv run --package simple-orchestrator-core       pytest packages/simple-orchestrator-core/
uv run --package simple-orchestrator-api-client pytest packages/simple-orchestrator-api-client/
uv run --package simple-orchestrator-webapi     pytest packages/simple-orchestrator-webapi/
uv run --package simple-orchestrator-worker     pytest packages/simple-orchestrator-worker/
```

## Índice de pacotes (onde mexer)

Veja também o `CLAUDE.md` dentro de cada pasta em `packages/`:

| Pacote | Para quê existe | Onde desenvolver / o que fazer |
|---|---|---|
| `packages/simple-orchestrator-core/` | Contrato (modelos, settings, Protocols, shapes da API) | Evoluir schemas/validação e manter compatibilidade entre `webapi` e `api-client`. |
| `packages/simple-orchestrator-database/` | Persistência SQLite (implementação do repositório) | Alterar consultas/retention/locking/migrations; garantir atomicidade e compatibilidade. |
| `packages/simple-orchestrator-webapi/` | FastAPI REST server | Expor endpoints finos; delegar persistência ao `database`; não duplicar regras de negócio. |
| `packages/simple-orchestrator-api-client/` | Cliente HTTP que implementa o repositório | Manter paridade com `webapi` + `core/api.py`; mapear erros/timeout/retries. |
| `packages/simple-orchestrator-worker/` | Runner da fila + vendors | Concorrência, cancelamento, timeouts, logs; integração com vendors (Claude/OpenCode/Copilot). |
| `packages/simple-orchestrator-tui/` | Interface terminal (Textual) | UX e fluxos; consumir apenas o repositório (DB direto ou HTTP). |
| `packages/simple-orchestrator/` | CLI/entrypoints do sistema | Subcomandos (`worker`, `webapi`), wiring de settings e DI. |

## Mudanças de conceito (manutenção do guia)

Se, durante o trabalho, você identificar **um novo conceito**, **um novo fundamento** ou **uma regra que se repete**:

1. Traga junto na resposta uma sugestão objetiva do que acrescentar no `CLAUDE.md` apropriado (raiz ou pacote).
2. Se for cross-cutting (afeta vários pacotes), inclua no `CLAUDE.md` da raiz e referencie o pacote.
3. Se for específico de um pacote, atualize apenas o `packages/<pacote>/CLAUDE.md`.

### Worker heartbeats

Worker sends ULID-keyed periodic heartbeats to WebAPI (`POST /heartbeat`). WebAPI upserts into `worker_heartbeats` table and uses TTL (`heartbeat_ttl_seconds`) to determine liveness on `GET /health`.

### Logging (`logging_config.py`)

Two log streams — import the right one per module:
- `get_internal_logger(__name__)` — `logs/orchestrator.log` (queue, DB, polling)
- `get_vendor_logger(__name__)` — `logs/vendor.log` (agent execution)

`DEBUG` mode adds `[filename.py:line]` to every log line.

---

## Vendor-specific notes

**ClaudeCodeVendor** — passes `session_id` to `ClaudeAgentOptions` so the SDK uses our ULID. MCP servers mapped `McpConfig → McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig` TypedDicts. Skills flattened to `list[str]`.

**OpenCodeVendor** — HTTP client (`AsyncOpencode`). Creates session via `session.create()`, stores returned `vendor_session_id`. Kill calls `session.abort(vendor_session_id)`.

**GithubCopilotVendor** — spawns CLI subprocess via `CopilotClient`. Session handle in `_active_handles`. Kill calls `session.abort()` then `session.disconnect()`.
