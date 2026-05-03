# simple-orchestrator

> Orquestrador de agentes IA multi-vendor assíncrono, com fila de tarefas, polling, cron e servidor MCP integrado.

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
| **Polling** | Enfileira um prompt em intervalo fixo (ex.: a cada 30 min). Possui deduplicação automática. |
| **Cron** | Enfileira prompts em horários definidos por expressão cron de 5 campos (ex.: `0 */6 * * *`). |
| **Multi-vendor** | Suporta `claude_code`, `opencode` e `github_copilot` como backends de execução. |
| **Servidor MCP integrado** | Expõe ferramentas para listar agentes, enfileirar tarefas, monitorar status e salvar memórias — acessíveis diretamente pelos agentes. |
| **MCP local** | Conecta FastMCP apps diretamente por importlib, sem subprocesso extra. |
| **Retomada de sessões** | Sessões interrompidas por reinício da aplicação são retomadas automaticamente. |
| **Memória de agentes** | Agentes podem salvar e recuperar contexto entre execuções via ferramentas MCP. |
| **TUI** | Interface terminal para inspecionar sessões e filas em tempo real. |

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

Toda a configuração fica no arquivo `orchestrator.toml` (commitável no repositório):

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
vendor  = "claude_code"
model   = "claude-sonnet-4-6"
workdir = "."
prompt  = "Você é um revisor de código especialista. Analise as mudanças e liste problemas por: Bugs / Segurança / Performance / Estilo."
```

Para usar um prompt em arquivo markdown:

```toml
[agents.auditor]
name        = "Security Auditor"
vendor      = "claude_code"
model       = "claude-opus-4-7"
workdir     = "."
prompt_file = "prompts/security-auditor.md"
```

---

## Exemplo: Polling + Cron para atribuição de tarefas

O cenário a seguir mostra um pipeline completo onde:

1. Um **cron** aciona um agente delegador a cada 6 horas para buscar novas tarefas.
2. Um **polling** aciona um revisor de código a cada 30 minutos para verificar mudanças recentes.
3. O **delegador** usa as ferramentas MCP para distribuir trabalho para os agentes especializados e aguardar os resultados.

### `orchestrator.toml`

```toml
db_path             = "orchestrator.db"
logs_dir            = "logs"
max_active_sessions = 6

[mcp_servers.orchestrator]
type = "sse"
url  = "http://127.0.0.1:8765/sse"

[mcp_servers.filesystem]
type    = "stdio"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "."]

# ── Polling: revisor de código a cada 30 minutos ──────────────────────────────
[[pollings]]
agent_id         = "reviewer"
prompt           = "Revise as mudanças recentes no repositório e reporte problemas encontrados."
interval_minutes = 30

# ── Cron: delegador a cada 6 horas ────────────────────────────────────────────
[[crons]]
agent_id = "delegator"
prompt   = "Verifique o backlog de tarefas no sistema e distribua para os agentes disponíveis."
cron     = "0 */6 * * *"

# ── Agentes ───────────────────────────────────────────────────────────────────

[agents.reviewer]
name    = "Code Reviewer"
vendor  = "claude_code"
model   = "claude-sonnet-4-6"
workdir = "."
prompt  = """
Você é um revisor de código especialista. Analise as mudanças recentes no git
e forneça um relatório estruturado com: Bugs / Segurança / Performance / Estilo.
"""

[agents.security]
name    = "Security Auditor"
vendor  = "claude_code"
model   = "claude-opus-4-7"
workdir = "."
prompt_file = "prompts/security-auditor.md"

[agents.tester]
name    = "Test Writer"
vendor  = "claude_code"
model   = "claude-sonnet-4-6"
workdir = "."
prompt  = "Você escreve testes automatizados para o código indicado no prompt."

[agents.delegator]
name    = "Task Delegator"
vendor  = "claude_code"
model   = "claude-sonnet-4-6"
workdir = "."
prompt_file = "prompts/delegator.md"

# O delegador precisa do MCP do orquestrador para enfileirar e monitorar tarefas
[agents.delegator.mcp_servers.orchestrator]
type = "sse"
url  = "http://127.0.0.1:8765/sse"
```

### `prompts/delegator.md`

```markdown
# Task Delegator

## Papel
Você é o agente central de distribuição de tarefas. Quando acionado, você deve:

1. Usar `list_agents` para descobrir os agentes disponíveis.
2. Analisar o backlog de trabalho pendente.
3. Usar `enqueue_tasks` para criar um lote de tarefas com dependências entre elas.
4. Usar `list_tasks` para monitorar o progresso.

## Exemplo de fluxo

Ao receber "Verifique o backlog e distribua tarefas":

```json
// Enfileira revisão de segurança e, após concluir, testes automáticos
[
  {
    "alias": "security-check",
    "agent_id": "security",
    "prompt": "Audite o módulo src/payments/ em busca de vulnerabilidades OWASP."
  },
  {
    "alias": "write-tests",
    "agent_id": "tester",
    "prompt": "Escreva testes para src/payments/ cobrindo os cenários críticos.",
    "depends_on": ["security-check"]
  }
]
```
```

### Iniciando o orquestrador

```bash
uv run simple-orchestrator start
```

O comando inicia:
- O **QueueRunner** (processa a fila de tarefas)
- O **PollingRunner** (dispara tarefas em intervalo fixo)
- O **CronRunner** (dispara tarefas em horário agendado)
- O **Servidor MCP** (SSE em `127.0.0.1:8765`)

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

## Estendendo as ferramentas MCP

É possível adicionar ferramentas customizadas ao servidor MCP do orquestrador de duas formas:

### Opção 1: FastMCP app local (`type = "local"`)

Crie um módulo Python com sua FastMCP app e registre como MCP server local no `orchestrator.toml`. O orquestrador carrega o app via `importlib` sem precisar de um processo extra.

```python
# my_tools/server.py
from fastmcp import FastMCP

mcp = FastMCP("my-tools")

@mcp.tool()
async def fetch_jira_ticket(ticket_id: str) -> str:
    """Busca detalhes de um ticket no Jira."""
    # ... implementação ...
    return f"Ticket {ticket_id}: ..."
```

```toml
# orchestrator.toml
[mcp_servers.my_tools]
type        = "local"
import_path = "my_tools.server:mcp"
```

Esse MCP ficará disponível para todos os agentes (se declarado globalmente) ou apenas para um agente específico (se declarado em `[agents.<id>.mcp_servers.my_tools]`).

### Opção 2: Servidor MCP externo via stdio ou SSE

Você pode apontar para qualquer servidor MCP compatível:

```toml
# Via subprocesso (stdio)
[mcp_servers.github]
type    = "stdio"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-github"]
env     = { GITHUB_TOKEN = "ghp_..." }

# Via SSE (servidor remoto)
[mcp_servers.my_api]
type = "sse"
url  = "https://my-mcp-server.example.com/sse"
headers = { Authorization = "Bearer token" }

# Via HTTP (Streamable HTTP transport)
[mcp_servers.my_http]
type = "http"
url  = "https://my-mcp-server.example.com/mcp"
```

---

## Uso avançado

### Grafo de dependências em lote

Use `enqueue_tasks` com `alias` e `depends_on` para expressar pipelines complexos em uma única chamada, sem precisar de múltiplos round-trips para coletar IDs:

```python
# Via Python diretamente
import asyncio
from simple_orchestrator.db.orchestrator import OrchestratorDB

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

from simple_orchestrator.vendors.base import BaseVendor
from simple_orchestrator.models.session import SessionConfig
from simple_orchestrator.models.model import ModelInfo


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
from simple_orchestrator.db.orchestrator import OrchestratorDB
from simple_orchestrator.queue_runner import QueueRunner
from simple_orchestrator.vendors.claude_code import ClaudeCodeVendor

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
ORCHESTRATOR_TOML_FILE=/etc/orchestrator/prod.toml uv run simple-orchestrator start

# Staging
ORCHESTRATOR_TOML_FILE=/etc/orchestrator/staging.toml uv run simple-orchestrator start
```

---

## Referência rápida de comandos

```bash
uv run simple-orchestrator start          # inicia orquestrador completo (fila + polling + cron + MCP)
uv run simple-orchestrator mcp-server     # inicia apenas o servidor MCP (stdio)
uv run simple-orchestrator tui            # abre a interface terminal
```

---

## Contribuindo

```bash
uv sync --frozen                  # instala dependências
uv run prek install               # instala git hooks
uv run prek run --all-files       # lint + format + type check
uv run pytest --tb=short -q       # executa testes
```
