# simple-orchestrator

> Orquestrador de agentes IA multi-vendor assíncrono, com fila de tarefas persistida em SQLite e suporte a execução standalone ou distribuída via REST API.

---

## O que é?

**simple-orchestrator** é um framework Python que coordena a execução de agentes de IA (Claude Code, OpenCode, GitHub Copilot) em background, com controle de concorrência e persistência em SQLite.

Ideal para pipelines onde um agente "delegador" distribui trabalho para agentes especializados, ou para automatizar tarefas recorrentes (revisão de código, auditorias, relatórios) sem intervenção humana.

**Dois modos de execução:**
- **Standalone** — TUI e worker acessam o SQLite diretamente, sem serviço intermediário.
- **Distribuído** — TUI e worker comunicam-se com uma WebAPI REST; o banco fica centralizado.

---

## Funcionalidades principais

| Funcionalidade | Descrição |
|---|---|
| **Fila de tarefas** | Agentes enfileirados e processados com paralelismo configurável. Tarefas no mesmo `workdir` são serializadas automaticamente. |
| **Dependências entre tarefas** | Uma tarefa pode declarar `depends_on`; só inicia após todas as dependências completarem. |
| **Dois modos de execução** | Standalone (SQLite direto) ou distribuído (REST API + worker remoto). |
| **Multi-vendor** | Suporta `claude_code`, `opencode` e `github_copilot` como backends. |
| **MCP** | Conecta servidores MCP externos via `stdio`, `sse` ou `http`, por configuração. |
| **TUI** | Interface terminal que consome a REST API (modo distribuído) ou o banco diretamente (standalone). |

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

A configuração pode ser feita via `orchestrator.toml` (arquivo dedicado) ou via `pyproject.toml` (seção `[tool.simple-orchestrator]`).

**Prioridade:** `orchestrator.toml` → `pyproject.toml` → variáveis de ambiente → valores padrão.

### Exemplo mínimo (`orchestrator.toml`)

```toml
db_path             = "orchestrator.db"
logs_dir            = "logs"
log_level           = "INFO"
max_active_sessions = 4

[agents.reviewer]
name    = "Code Reviewer"
vendor  = "claude_code"
model   = "claude-sonnet-4-6"
workdir = "."
prompt  = "Você é um revisor de código especialista. Analise as mudanças e liste problemas por: Bugs / Segurança / Performance / Estilo."
```

Prompt em arquivo separado (recomendado para prompts longos):

```toml
[agents.reviewer]
name        = "Code Reviewer"
vendor      = "claude_code"
model       = "claude-sonnet-4-6"
workdir     = "."
prompt_file = "prompts/reviewer.md"
```

### Com MCP e skills

```toml
[mcp_servers.filesystem]
type    = "stdio"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "."]

[agents.reviewer]
name        = "Code Reviewer"
vendor      = "claude_code"
model       = "claude-sonnet-4-6"
workdir     = "."
prompt      = "Revise o código."
mcp_servers = ["filesystem"]
```

### Múltiplos ambientes

```bash
ORCHESTRATOR_TOML_FILE=/etc/orchestrator/prod.toml uv run simple-orchestrator worker
```

---

## Uso

### Modo standalone

```bash
# Terminal 1 — worker (processa a fila localmente)
uv run simple-orchestrator worker

# Terminal 2 — TUI (interface terminal, acessa banco direto)
uv run simple-orchestrator-tui
```

### Modo distribuído

```bash
# Servidor — WebAPI REST + banco centralizado
uv run simple-orchestrator webapi

# Worker remoto — conecta via API
ORCHESTRATOR_API_URL=http://servidor:8765 uv run simple-orchestrator worker

# TUI — conecta via API
ORCHESTRATOR_API_URL=http://servidor:8765 uv run simple-orchestrator-tui
```

---

## Controle de concorrência

```toml
max_active_sessions = 4   # máximo de sessões simultâneas (global)

[agents.patcher]
name    = "Code Patcher"
vendor  = "claude_code"
workdir = "/workspace/repo"   # tarefas neste dir são serializadas
prompt  = "Aplique o patch descrito no prompt."

[agents.long_runner]
name                 = "Long Runner"
vendor               = "claude_code"
task_timeout_minutes = 120   # timeout individual (padrão: 30 min)
prompt               = "Execute análise completa."
```

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
        pass  # cancele a sessão no backend externo
```

---

## Referência de comandos

```bash
uv run simple-orchestrator worker    # worker (fila + FastAPI :8765)
uv run simple-orchestrator webapi    # WebAPI standalone (sem fila)
uv run simple-orchestrator-tui       # interface terminal
```

---

## Contribuindo

Veja [CONTRIBUTING.md](CONTRIBUTING.md) para arquitetura detalhada, diagramas e guia de desenvolvimento.
