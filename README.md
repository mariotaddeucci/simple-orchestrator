# simple-orchestrator

> Orquestrador de agentes IA multi-vendor assíncrono, com fila de tarefas e agendamento persistidos em SQLite, gerenciados via REST API.

---

## O que é?

**simple-orchestrator** é um framework Python que coordena a execução de agentes de IA (Claude Code, OpenCode, GitHub Copilot) em background, com controle de concorrência e persistência em SQLite.

Ideal para pipelines onde um agente "delegador" distribui trabalho para agentes especializados, ou para automatizar tarefas recorrentes (revisão de código, auditorias, relatórios) sem intervenção humana.

**Orientado a banco de dados:** agentes, MCPs e eventos de agendamento são criados e gerenciados pela API REST (não por arquivos de configuração). O `orchestrator.toml` define apenas parâmetros de infraestrutura.

**Dois modos de execução:**
- **Standalone** — `simple-orchestrator tui` inicia WebAPI e worker automaticamente como subprocessos. Tudo em um comando.
- **Distribuído** — WebAPI, worker e TUI correm em processos separados (possivelmente em hosts diferentes).

---

## Funcionalidades principais

| Funcionalidade | Descrição |
|---|---|
| **Agentes via API** | Crie, atualize e delete agentes pelo REST (`POST /agents`). Sem configuração em TOML. |
| **MCPs via API** | Registre servidores MCP (stdio/sse/http) globais ou por agente via `POST /mcps`. |
| **Fila de tarefas** | Agentes enfileirados e processados com paralelismo configurável. Tarefas no mesmo `workdir` são serializadas automaticamente. |
| **Eventos agendados** | Crie eventos com intervalo fixo (`interval_minutes`) ou expressão cron (`cron_expression`). O worker dispara automaticamente e calcula o próximo `next_run`. |
| **Dependências entre tarefas** | Uma tarefa pode declarar `depends_on`; só inicia após todas as dependências completarem. |
| **Dois modos de execução** | Standalone (um comando, subprocessos automáticos) ou distribuído (REST API + worker remoto). |
| **Multi-vendor** | Suporta `claude_code`, `opencode` e `github_copilot` como backends. |
| **TUI** | Interface terminal com tabs de Fila, Agentes e Eventos. Enfileirar tarefa por seleção de agente na lista. |

---

## Instalação

```bash
# Requer Python 3.14+
pip install simple-orchestrator

# Desenvolvimento
git clone https://github.com/mariotaddeucci/simple-orchestrator
cd simple-orchestrator
uv sync --frozen
uv run prek install   # instala git hooks
```

---

## Configuração

O `orchestrator.toml` define apenas infraestrutura. Agentes, MCPs e eventos são gerenciados pela API.

### `orchestrator.toml` (infraestrutura)

```toml
db_path             = "orchestrator.db"
logs_dir            = "logs"
log_level           = "INFO"
max_active_sessions = 4
default_task_timeout_minutes = 30.0
poll_interval_seconds = 1.0

api_key      = "change-me"
webapi_host  = "127.0.0.1"
webapi_port  = 8765
```

**Prioridade de configuração:** `orchestrator.toml` → env vars → `.env` → `pyproject.toml` → defaults.

---

## Uso

### Modo standalone (recomendado para começar)

Um único comando inicia a WebAPI, o worker e a TUI. Worker é subprocesso da TUI — encerra junto.

```bash
uv run simple-orchestrator tui
```

### Modo distribuído

```bash
# Servidor — WebAPI REST + banco centralizado
uv run simple-orchestrator webapi

# Worker remoto — conecta via API
ORCHESTRATOR_API_URL=http://servidor:8765 uv run simple-orchestrator worker

# TUI — conecta a WebAPI existente
ORCHESTRATOR_API_URL=http://servidor:8765 uv run simple-orchestrator tui --distributed
```

---

## Gerenciando recursos via API

Todos os exemplos assumem `api_key = "change-me"` e `webapi_port = 8765`.

### Criar um agente

```bash
curl -X POST http://localhost:8765/agents \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "reviewer",
    "name": "Code Reviewer",
    "vendor": "claude_code",
    "model": "claude-sonnet-4-6",
    "workdir": ".",
    "prompt": "Você é um revisor de código. Analise as mudanças e reporte problemas."
  }'
```

### Registrar um MCP global

```bash
curl -X POST http://localhost:8765/mcps \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "filesystem",
    "name": "filesystem",
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
    "is_global": true
  }'
```

### Enfileirar uma tarefa

```bash
curl -X POST http://localhost:8765/queue \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "reviewer",
    "prompt": "Revise o PR mais recente."
  }'
```

### Criar um evento agendado

```bash
# Intervalo fixo: a cada 30 minutos
curl -X POST http://localhost:8765/events \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "revisão periódica",
    "agent_id": "reviewer",
    "prompt": "Revise mudanças recentes e reporte problemas.",
    "schedule_type": "interval",
    "interval_minutes": 30
  }'

# Cron: todo dia às 9h
curl -X POST http://localhost:8765/events \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "relatório diário",
    "agent_id": "reviewer",
    "prompt": "Gere o relatório diário.",
    "schedule_type": "cron",
    "cron_expression": "0 9 * * *"
  }'
```

---

## Controle de concorrência

```toml
# orchestrator.toml
max_active_sessions = 4   # máximo de sessões simultâneas (global)
```

Tarefas para o mesmo `workdir` são serializadas automaticamente pelo worker.
Timeout individual por agente é configurado no campo `task_timeout_minutes` ao criar o agente.

---

## Implementando um vendor customizado

```python
from typing import Any, AsyncIterator
from simple_orchestrator_core.models.session import SessionConfig
from simple_orchestrator_core.models.model import ModelInfo
from simple_orchestrator_worker.vendors.base import BaseVendor


class MyVendor(BaseVendor):
    @property
    def vendor_name(self) -> str:
        return "my_vendor"

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="my-model-v1", name="My Model v1", vendor="my_vendor")]

    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        yield {"type": "text", "content": "Resposta do agente..."}

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        async for _ in self.execute_session(config):
            pass

    async def _vendor_kill(self, session_id: str) -> None:
        pass
```

---

## Referência de comandos

```bash
uv run simple-orchestrator tui               # standalone: inicia webapi + worker + TUI
uv run simple-orchestrator tui --distributed # TUI apenas (conecta a webapi existente)
uv run simple-orchestrator webapi            # WebAPI standalone
uv run simple-orchestrator worker            # worker standalone
```

---

## Contribuindo

Veja [CONTRIBUTING.md](CONTRIBUTING.md) para arquitetura detalhada, diagramas e guia de desenvolvimento.
