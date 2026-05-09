# Contributing

## Setup de desenvolvimento

```bash
git clone https://github.com/mariotaddeucci/simple-orchestrator
cd simple-orchestrator
uv sync --frozen          # instala dependências
uv run prek install       # instala git hooks (lint + format + type check no commit)
```

---

## Arquitetura

O projeto é um **UV workspace** com 7 pacotes. O princípio central é a separação de contratos (interfaces) da implementação: `simple-orchestrator-core` define o que cada componente deve fazer; os demais pacotes implementam ou consomem essas definições.

### Pacotes e responsabilidades

| Pacote | Módulo | Foco |
|---|---|---|
| `simple-orchestrator` | `simple_orchestrator` | Ponto de entrada CLI (`worker`, `webapi`, `tui`) |
| `simple-orchestrator-core` | `simple_orchestrator_core` | **Contratos**: Pydantic models, Protocol interfaces, settings, validators |
| `simple-orchestrator-database` | `simple_orchestrator_database` | **Persistência**: implementa `IOrchestratorRepository` via SQLite/SQLModel |
| `simple-orchestrator-webapi` | `simple_orchestrator_webapi` | **REST API**: FastAPI; delega todo acesso a dados ao pacote `database` |
| `simple-orchestrator-worker` | `simple_orchestrator_worker` | **Execução**: fila de tarefas, agendamento de eventos, vendors (Claude/OpenCode/Copilot) |
| `simple-orchestrator-api-client` | `simple_orchestrator_api_client` | **Cliente HTTP**: consome a REST API |
| `simple-orchestrator-tui` | `simple_orchestrator_tui` | **Interface**: Textual TUI; consome a REST API |

---

## Diagramas de arquitetura

### Modo standalone

No modo standalone, o comando `simple-orchestrator tui` gerencia o ciclo de vida de todos os componentes. A WebAPI e o worker são iniciados como **subprocessos** da TUI e encerrados automaticamente quando a TUI fecha.

```
  simple-orchestrator tui (processo pai)
  ┌────────────────────────────────────────────────────────────┐
  │                                                            │
  │  TUI (Textual)          WebAPI (subprocesso)              │
  │  ┌──────────────┐       ┌────────────────────┐            │
  │  │  Queue tab   │       │  FastAPI :8765      │            │
  │  │  Agents tab  │◄─────►│  /queue /agents     │            │
  │  │  Events tab  │  HTTP │  /mcps /events      │            │
  │  └──────────────┘       └────────────┬───────┘            │
  │                                      │                    │
  │  Worker (subprocesso)                │ OrchestratorDB     │
  │  ┌──────────────┐       ┌────────────▼───────┐            │
  │  │  QueueRunner │◄─────►│  SQLite             │            │
  │  │  EventSched  │  HTTP └────────────────────┘            │
  │  └──────────────┘                                         │
  └────────────────────────────────────────────────────────────┘
```

Para desativar o modo standalone e conectar a uma WebAPI já existente:

```bash
# Opção 1: flag explícita
uv run simple-orchestrator tui --distributed

# Opção 2: variável de ambiente
ORCHESTRATOR_STANDALONE=false uv run simple-orchestrator tui
```

### Modo distribuído

TUI e worker se comunicam com a WebAPI via HTTP. Cada componente roda em processo independente.

```
  simple-orchestrator-tui          simple-orchestrator-worker
  ┌──────────────────────┐         ┌──────────────────────────┐
  │  Textual TUI         │         │  QueueRunner             │
  │  (Queue/Agents/      │         │  (processa tarefas,      │
  │   Events tabs)       │         │   agenda eventos)        │
  └──────────┬───────────┘         └────────────┬─────────────┘
             │                                  │
             │  HTTP / REST                     │  HTTP / REST
             │                                  │
             └──────────────┬───────────────────┘
                            │
             simple-orchestrator-webapi
             ┌─────────────────────────────────┐
             │  FastAPI                        │
             │  /queue /agents /sessions       │
             │  /mcps /events /health          │
             └──────────────┬──────────────────┘
                            │
             simple-orchestrator-database
             ┌──────────────────────────────┐
             │  OrchestratorDB              │
             │  agents / queue / sessions   │
             │  mcps / events / heartbeats  │
             └──────────────┬───────────────┘
                            │
                       ┌─────────┐
                       │ SQLite  │
                       └─────────┘
```

### Fluxo de comunicação entre pacotes

```
  simple-orchestrator-core  ◄── importado por TODOS os outros pacotes
  │
  ├── models/          Pydantic v2 (SessionRecord, QueueItem, AgentRecord,
  │                                 McpRecord, EventRecord, ...)
  ├── interfaces.py    IOrchestratorRepository (Protocol = contrato)
  ├── api.py           Request/Response Pydantic (compartilhados com api-client)
  ├── settings.py      WebApiSettings, WorkerSettings, TuiSettings
  ├── schedule.py      compute_next_run() — cálculo de próxima execução (interval/cron)
  └── validators.py    ValidULID, ValidWorkdir, ValidAgentId, ...

  simple-orchestrator-database
  └── OrchestratorDB  implementa IOrchestratorRepository (SQLite/SQLModel)

  simple-orchestrator-api-client
  └── ApiClient       cliente HTTP para a REST API

  simple-orchestrator-webapi
  ├── FastAPI routes  delega para OrchestratorDB (do pacote database)
  └── session_config_builder  monta SessionConfig a partir de agente + MCPs globais do DB

  simple-orchestrator-worker
  ├── QueueRunner     dequeue/dispatch com controle de concorrência
  ├── EventScheduler  agenda eventos periódicos (interval ou cron) via loop interno
  ├── vendors/base    BaseVendor ABC
  ├── vendors/claude_code
  ├── vendors/opencode
  └── vendors/copilot

  simple-orchestrator-tui
  └── Textual TUI     tabs Queue / Agents / Events; consome a REST API via api-client
```

---

## Princípios de design

**Core é o único pacote importado por todos.** Nenhum pacote importa de outro (exceto `database` → `core`, `webapi` → `database` + `core`, etc.). Isso previne dependências circulares.

**Orientado a banco de dados.** Agentes, MCPs e eventos são gerenciados via API REST (e persistidos no SQLite). Não há mais configuração de agentes/MCPs via TOML — o TOML só define parâmetros de infraestrutura (db_path, porta, log_level, etc.).

**Modo standalone = subprocesso.** Ao rodar `simple-orchestrator tui`, a WebAPI e o worker são automaticamente iniciados como subprocessos e encerrados junto com a TUI.

**`IOrchestratorRepository` é o ponto de injeção.** Código que lê/escreve dados deve tipificar contra a Protocol, nunca contra `OrchestratorDB` diretamente.

**Vendors são assíncronos, DB é síncrono.** `OrchestratorDB` usa SQLAlchemy síncrono. A WebAPI envolve chamadas DB em `anyio.to_thread.run_sync()` para não bloquear o event loop.

---

## Testes

Cada pacote tem configuração pytest própria — sempre use `--package`:

```bash
# Todos os testes de um pacote
uv run --package simple-orchestrator-core    pytest packages/simple-orchestrator-core/
uv run --package simple-orchestrator-worker  pytest packages/simple-orchestrator-worker/
uv run --package simple-orchestrator-webapi  pytest packages/simple-orchestrator-webapi/

# Arquivo único
uv run --package simple-orchestrator-webapi  pytest packages/simple-orchestrator-webapi/tests/test_orchestrator_db.py

# Por nome
uv run --package simple-orchestrator-core    pytest packages/simple-orchestrator-core/ -k test_parse_vendor

# Integração (requer autenticação com vendors)
uv run --package simple-orchestrator-worker  pytest packages/simple-orchestrator-worker/ -m integration
```

---

## Code quality

```bash
uv run ruff check .           # lint
uv run ruff check --fix .     # lint + auto-fix
uv run ruff format .          # format
uv run pyrefly check          # type check
uv run prek run --all-files   # tudo de uma vez
```

---

## Adicionando um novo pacote ao workspace

1. Crie `packages/<nome>/pyproject.toml` com `build-backend = "uv_build"`.
2. Adicione `"packages/<nome>"` em `[tool.uv.workspace] members` no `pyproject.toml` raiz.
3. Adicione a fonte em `[tool.uv.sources]` e em `dependencies` do workspace raiz.
4. Se o pacote expõe código sob `pyrefly check`, adicione o path em `[tool.pyrefly] project_includes`.
5. Execute `uv sync` (sem `--frozen`) para atualizar o lockfile.
6. Crie `README.md` vazio no pacote (necessário para o build).
