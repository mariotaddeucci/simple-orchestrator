# simple-orchestrator

> Orquestrador de agentes IA multi-vendor assíncrono, com fila de tarefas e worker REST (FastAPI) para controle remoto.

---

## O que é?

**simple-orchestrator** é um framework Python que coordena a execução de agentes de IA (Claude Code, OpenCode, GitHub Copilot) em background, com controle de concorrência, persistência em SQLite e um servidor [MCP](https://modelcontextprotocol.io/) que expõe ferramentas para que os próprios agentes possam delegar tarefas entre si.

Ideal para pipelines onde um agente "delegador" precisa distribuir trabalho para agentes especializados, ou para automatizar tarefas recorrentes (revisão de código, auditorias, relatórios) sem intervenção humana.

---

## Funcionalidades principais

| Funcionalidade | Descrição |
|---|---|
| **Fila de tarefas** | Agentes são enfileirados e processados com paralelismo configurável. Tarefas com o mesmo `workdir` são serializadas automaticamente. |
| **Dependências entre tarefas** | Uma tarefa pode declarar `depends_on` de outras; ela só inicia após todas as dependências completarem. |
| **Worker REST API** | Exposição de endpoints para enfileirar tarefas e acompanhar status remotamente. |
| **Multi-vendor** | Suporta `claude_code`, `opencode` e `github_copilot` como backends de execução. |
| **Servidor MCP integrado** | Expõe ferramentas para listar agentes, enfileirar tarefas, monitorar status e salvar memórias — acessíveis diretamente pelos agentes. |
| **MCP local** | Conecta FastMCP apps diretamente por importlib, sem subprocesso extra. |
| **Retomada de sessões** | Sessões interrompidas por reinício da aplicação são retomadas automaticamente. |
| **Memória de agentes** | Agentes podem salvar e recuperar contexto entre execuções via ferramentas MCP. |
| **TUI (cliente)** | Interface terminal separada que consome a REST API (sem acesso direto ao DB/local worker). |

---

## Instalação

```bash
# Requer Python 3.13+
pip install simple-orchestrator

# Ou, para desenvolvimento:
git clone https://github.com/mariotaddeucci/simple-orchestrator
cd simple-orchestrator
uv sync --frozen
```

---

## Configuração rápida

A configuração pode ser feita de duas formas:

1. **`orchestrator.toml`** (arquivo dedicado, commitável no repositório)
2. **`pyproject.toml`** (seção `[tool.simple-orchestrator]` no arquivo do projeto Python)

**Prioridade de configuração:**
1. `orchestrator.toml` (ou caminho definido em `ORCHESTRATOR_TOML_FILE`)
2. `pyproject.toml` (seção `[tool.simple-orchestrator]`)
3. Variáveis de ambiente
4. Valores padrão

### Exemplo com `orchestrator.toml`:

```toml
db_path             = "orchestrator.db"
logs_dir            = "logs"
log_level           = "INFO"
max_active_sessions = 4

# Servidor MCP (para que agentes possam se comunicar com o orquestrador)
mcp_server_host = "127.0.0.1"
mcp_server_port = 8765

# MCP global — disponível para todos os agentes
[mcp_servers.filesystem]
type    = "stdio"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "."]

[mcp_servers.orchestrator]
type = "sse"
url  = "http://127.0.0.1:8765/sse"

# Definição de agentes
[agents.reviewer]
name    = "Code Reviewer"
model   = "claude-code/claude-sonnet-4-6"
workdir = "."
prompt  = "Você é um revisor de código especialista. Analise as mudanças e liste problemas por: Bugs / Segurança / Performance / Estilo."
```

### Exemplo com `pyproject.toml`:

```toml
[tool.simple-orchestrator]
db_path             = "orchestrator.db"
logs_dir            = "logs"
log_level           = "INFO"
max_active_sessions = 4

mcp_server_host = "127.0.0.1"
mcp_server_port = 8765

[tool.simple-orchestrator.mcp_servers.filesystem]
type    = "stdio"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "."]

[tool.simple-orchestrator.mcp_servers.orchestrator]
type = "sse"
url  = "http://127.0.0.1:8765/sse"

[tool.simple-orchestrator.agents.reviewer]
name    = "Code Reviewer"
model   = "claude-code/claude-sonnet-4-6"
workdir = "."
prompt  = "Você é um revisor de código especialista. Analise as mudanças e liste problemas por: Bugs / Segurança / Performance / Estilo."
```

Para usar um prompt em arquivo markdown:

**Em `orchestrator.toml`:**
```toml
[agents.auditor]
name        = "Security Auditor"
model       = "claude-code/claude-opus-4-7"
workdir     = "."
prompt_file = "prompts/security-auditor.md"
```

**Em `pyproject.toml`:**
```toml
[tool.simple-orchestrator.agents.auditor]
name        = "Security Auditor"
model       = "claude-code/claude-opus-4-7"
workdir     = "."
prompt_file = "prompts/security-auditor.md"
```

---

## Iniciando

```bash
# Worker (REST API + QueueRunner)
uv run simple-orchestrator worker

# TUI (cliente) — consome a REST API
uv run simple-orchestrator-tui
```

---

## Ferramentas MCP disponíveis

O servidor MCP expõe as seguintes ferramentas para os agentes:

### Agentes

| Ferramenta | Descrição |
|---|---|
| `list_agents(vendor?)` | Lista todos os agentes disponíveis (TOML + banco). Filtrável por vendor. |

### Fila de tarefas

| Ferramenta | Descrição |
|---|---|
| `enqueue_task(agent_id, prompt, depends_on?)` | Enfileira uma única tarefa para um agente. Retorna o `task_id`. |
| `enqueue_tasks(tasks[])` | Enfileira várias tarefas de uma vez, com aliases e dependências entre elas. |
| `list_tasks(status?, agent_id?)` | Lista tarefas na fila, com filtros opcionais. |
| `get_task(task_id)` | Retorna os detalhes completos de uma tarefa, incluindo o `session_id`. |
| `cancel_task(task_id)` | Cancela uma tarefa pendente. |

### Sessões

| Ferramenta | Descrição |
|---|---|
| `get_session(session_id)` | Retorna detalhes da sessão do agente criada para uma tarefa. |

### Memória

| Ferramenta | Descrição |
|---|---|
| `save_memory(agent_id, description, content)` | Salva uma memória para um agente. |
| `list_memories(agent_id?)` | Lista memórias salvas (sem o conteúdo completo). |
| `get_memory(memory_id)` | Recupera o conteúdo completo de uma memória. |
| `delete_memory(memory_id)` | Remove uma memória pelo ID. |

---

## Custom Tools

Adicione ferramentas próprias aos agentes criando uma **FastMCP app** e registrando-a como MCP server local no `orchestrator.toml`. O orquestrador carrega o app via `importlib`, sem precisar de um processo extra.

```python
# my_tools/server.py
from fastmcp import FastMCP

mcp = FastMCP("my-tools")

@mcp.tool()
async def fetch_jira_ticket(ticket_id: str) -> str:
    """Busca detalhes de um ticket no Jira."""
    # ... implementação ...
    return f"Ticket {ticket_id}: ..."

@mcp.tool()
async def post_slack_message(channel: str, text: str) -> str:
    """Envia uma mensagem para um canal do Slack."""
    # ... implementação ...
    return "ok"
```

```toml
# orchestrator.toml — disponível para todos os agentes
[mcp_servers.my_tools]
type        = "local"
import_path = "my_tools.server:mcp"

# Ou apenas para um agente específico:
# [agents.delegator.mcp_servers.my_tools]
# type        = "local"
# import_path = "my_tools.server:mcp"
```

O valor de `import_path` segue a notação `"modulo.caminho:atributo"` — o atributo deve ser uma instância de `FastMCP`.

---

## Servidores MCP externos

Para conectar ferramentas já empacotadas como servidores MCP independentes, use os tipos `stdio`, `sse` ou `http`:

```toml
# Via subprocesso (stdio) — ex.: servidor oficial do GitHub
[mcp_servers.github]
type    = "stdio"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-github"]
env     = { GITHUB_TOKEN = "ghp_..." }

# Via SSE (servidor remoto)
[mcp_servers.my_api]
type    = "sse"
url     = "https://my-mcp-server.example.com/sse"
headers = { Authorization = "Bearer token" }

# Via HTTP (Streamable HTTP transport)
[mcp_servers.my_http]
type = "http"
url  = "https://my-mcp-server.example.com/mcp"
```

Assim como as custom tools, esses servidores podem ser declarados globalmente (para todos os agentes) ou por agente individual.

---

## Uso avançado

### Grafo de dependências em lote

Use `enqueue_tasks` com `alias` e `depends_on` para expressar pipelines complexos em uma única chamada, sem precisar de múltiplos round-trips para coletar IDs:

```python
# Via Python diretamente
import asyncio
from simple_orchestrator_worker.db.orchestrator import OrchestratorDB

async def main():
    async with OrchestratorDB("orchestrator.db") as db:
        # Busca → Análise → Relatório (pipeline sequencial)
        fetch_id = str(ulid.ULID())
        analyze_id = str(ulid.ULID())

        await db.enqueue("fetcher", "Baixe os dados de vendas do mês.", item_id=fetch_id)
        await db.enqueue("analyst", "Analise os dados de vendas.", depends_on=[fetch_id], item_id=analyze_id)
        await db.enqueue("reporter", "Gere o relatório executivo.", depends_on=[analyze_id])
```

Via ferramenta MCP (em um agente):
```json
{
  "tasks": [
    { "alias": "fetch",   "agent_id": "fetcher",  "prompt": "Baixe os dados de vendas do mês." },
    { "alias": "analyze", "agent_id": "analyst",  "prompt": "Analise os dados.", "depends_on": ["fetch"] },
    { "alias": "report",  "agent_id": "reporter", "prompt": "Gere o relatório.", "depends_on": ["analyze"] }
  ]
}
```

### Implementando um vendor customizado

Para integrar um novo backend de IA, herde `BaseVendor` e implemente os métodos abstratos:

```python
from collections.abc import AsyncIterator
from typing import Any

from simple_orchestrator_worker.vendors.base import BaseVendor
from simple_orchestrator_worker.models.session import SessionConfig
from simple_orchestrator_worker.models.model import ModelInfo


class MyCustomVendor(BaseVendor):
    @property
    def vendor_name(self) -> str:
        return "my_vendor"

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="my-model-v1", name="My Model v1", vendor="my_vendor")]

    async def execute_session(self, config: SessionConfig) -> AsyncIterator[Any]:
        # Stream de eventos do seu backend
        yield {"type": "text", "content": "Resposta do agente..."}

    async def _run_session(self, session_id: str, config: SessionConfig) -> None:
        # Drena o iterator e persiste status no DB
        async for event in self.execute_session(config):
            pass  # processe os eventos conforme necessário

    async def _vendor_kill(self, session_id: str) -> None:
        # Cancela a sessão no backend
        handle = self._active_handles.pop(session_id, None)
        if handle:
            await handle.abort()
```

Registre o vendor ao iniciar o orquestrador:

```python
from simple_orchestrator_worker.db.orchestrator import OrchestratorDB
from simple_orchestrator_worker.queue_runner import QueueRunner
from simple_orchestrator_worker.vendors.claude_code import ClaudeCodeVendor

db = OrchestratorDB("orchestrator.db")
vendors = {
    "claude_code": ClaudeCodeVendor(db),
    "my_vendor": MyCustomVendor(db),
}
runner = QueueRunner(db, vendors)
```

### Controlando a concorrência por workdir

O `QueueRunner` serializa automaticamente tarefas que compartilham o mesmo `workdir`. Isso garante que dois agentes nunca modifiquem o mesmo diretório simultaneamente:

```toml
# Todas as tarefas do agente "patcher" no mesmo dir são executadas em sequência
[agents.patcher]
name    = "Code Patcher"
vendor  = "claude_code"
workdir = "/workspace/repo"   # lock por diretório
prompt  = "Aplique o patch descrito no prompt."
```

Para tarefas independentes sem workdir fixo, o orquestrador cria um diretório temporário por sessão.

### Timeout por agente

Configure um timeout diferente do padrão global para agentes específicos:

```toml
[agents.long_runner]
name                  = "Long Running Agent"
vendor                = "claude_code"
task_timeout_minutes  = 120   # 2 horas (padrão global: 30 min)
prompt                = "Execute análise completa do repositório."
```

### Variável de ambiente para múltiplos ambientes

```bash
# Produção
ORCHESTRATOR_TOML_FILE=/etc/orchestrator/prod.toml uv run simple-orchestrator worker

# Staging
ORCHESTRATOR_TOML_FILE=/etc/orchestrator/staging.toml uv run simple-orchestrator worker
```

---

## Referência rápida de comandos

```bash
uv run simple-orchestrator worker         # inicia worker (REST API + fila)
uv run simple-orchestrator mcp-server     # inicia apenas o servidor MCP (stdio)
uv run simple-orchestrator-tui            # abre a interface terminal (cliente REST)
```

---

## Contribuindo

```bash
uv sync --frozen                  # instala dependências
uv run prek install               # instala git hooks
uv run prek run --all-files       # lint + format + type check
uv run pytest --tb=short -q       # executa testes
```
