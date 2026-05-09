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
| `simple-orchestrator` | `simple_orchestrator` | Ponto de entrada CLI (`worker`, `webapi`) |
| `simple-orchestrator-core` | `simple_orchestrator_core` | **Contratos**: Pydantic models, Protocol interfaces, settings, validators |
| `simple-orchestrator-database` | `simple_orchestrator_database` | **Persistência**: implementa `IOrchestratorRepository` via SQLite/SQLModel |
| `simple-orchestrator-webapi` | `simple_orchestrator_webapi` | **REST API**: FastAPI; delega todo acesso a dados ao pacote `database` |
| `simple-orchestrator-worker` | `simple_orchestrator_worker` | **Execução**: fila de tarefas, vendors (Claude/OpenCode/Copilot) |
| `simple-orchestrator-api-client` | `simple_orchestrator_api_client` | **Cliente HTTP**: implementa `IOrchestratorRepository` via REST |
| `simple-orchestrator-tui` | `simple_orchestrator_tui` | **Interface**: Textual TUI; consome `IOrchestratorRepository` |

---

## Diagramas de arquitetura

### Modo standalone

TUI e worker rodam no mesmo host e acessam o SQLite diretamente via `OrchestratorDB`.
Não há serviço de rede entre os componentes.

```
  simple-orchestrator-tui          simple-orchestrator-worker
  ┌──────────────────────┐         ┌──────────────────────────┐
  │  Textual TUI         │         │  QueueRunner             │
  │  (visualiza fila,    │         │  (processa tarefas,      │
  │   enfileira tarefas) │         │   executa vendors)       │
  └──────────┬───────────┘         └────────────┬─────────────┘
             │                                  │
             │  IOrchestratorRepository         │  IOrchestratorRepository
             │  (injeção direta)                │  (injeção direta)
             │                                  │
             └──────────────┬───────────────────┘
                            │
                            ▼
             simple-orchestrator-database
             ┌──────────────────────────────┐
             │  OrchestratorDB              │
             │  agents / queue / sessions   │
             │  memory / heartbeats         │
             └──────────────┬───────────────┘
                            │
                            ▼
                       ┌─────────┐
                       │ SQLite  │
                       └─────────┘
```

### Modo distribuído

TUI e worker se comunicam com a WebAPI via HTTP. `simple-orchestrator-api-client` implementa
a mesma interface (`IOrchestratorRepository`) que o banco; o código consumidor não muda.

```
  simple-orchestrator-tui          simple-orchestrator-worker
  ┌──────────────────────┐         ┌──────────────────────────┐
  │  Textual TUI         │         │  QueueRunner             │
  │  (visualiza fila,    │         │  (processa tarefas,      │
  │   enfileira tarefas) │         │   executa vendors)       │
  └──────────┬───────────┘         └────────────┬─────────────┘
             │                                  │
             │  IOrchestratorRepository         │  IOrchestratorRepository
             │  (via api-client)                │  (via api-client)
             │                                  │
             └──────────────┬───────────────────┘
                            │
              simple-orchestrator-api-client
              ┌─────────────────────────────┐
              │  ApiClient                  │
              │  HTTP impl da interface     │
              └──────────────┬──────────────┘
                             │  HTTP / REST
                             ▼
             simple-orchestrator-webapi
             ┌─────────────────────────────────┐
             │  FastAPI                        │
             │  /queue /agents /sessions ...   │
             └──────────────┬──────────────────┘
                            │
                            ▼
             simple-orchestrator-database
             ┌──────────────────────────────┐
             │  OrchestratorDB              │
             └──────────────┬───────────────┘
                            │
                            ▼
                       ┌─────────┐
                       │ SQLite  │
                       └─────────┘
```

### Fluxo de comunicação entre pacotes

```
  simple-orchestrator-core  ◄── importado por TODOS os outros pacotes
  │
  ├── models/          Pydantic v2 (SessionRecord, QueueItem, AgentRecord, ...)
  ├── interfaces.py    IOrchestratorRepository (Protocol = contrato)
  ├── api.py           Request/Response Pydantic (compartilhados com api-client)
  ├── settings.py      WebApiSettings, WorkerSettings, TuiSettings
  └── validators.py    ValidULID, ValidWorkdir, ValidAgentId, ...

  simple-orchestrator-database
  └── OrchestratorDB  implementa IOrchestratorRepository (SQLite/SQLModel)

  simple-orchestrator-api-client
  └── ApiClient       implementa IOrchestratorRepository (HTTP)

  simple-orchestrator-webapi
  ├── FastAPI routes  delega para OrchestratorDB (do pacote database)
  └── db/             shim de re-exportação (from simple_orchestrator_database import ...)

  simple-orchestrator-worker
  ├── QueueRunner     consome IOrchestratorRepository (standalone ou via cliente HTTP)
  ├── vendors/base    BaseVendor ABC (vendor_name, _run_session, _vendor_kill, execute_session, list_models)
  ├── vendors/claude_code
  ├── vendors/opencode
  └── vendors/copilot

  simple-orchestrator-tui
  └── Textual TUI     consome IOrchestratorRepository (standalone ou via cliente HTTP)
```

---

## Princípios de design

**Core é o único pacote importado por todos.** Nenhum pacote importa de outro (exceto `database` → `core`, `webapi` → `database` + `core`, etc.). Isso previne dependências circulares.

**`IOrchestratorRepository` é o ponto de injeção.** Código que lê/escreve dados deve tipificar contra a Protocol, nunca contra `OrchestratorDB` diretamente. Isso é o que permite trocar SQLite por HTTP sem mudar o consumidor.

**Pydantic models em `core/api.py` são compartilhados.** O `api-client` e o `webapi` usam os mesmos `Request`/`Response`; divergência de schema é detectada em tempo de compilação.

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
