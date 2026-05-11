# Frontend Agent Instructions

Este pacote é o frontend web do Simple Orchestrator.

## Filosofia "No-Build"

O frontend foi projetado para ser simples e não exigir um passo de build (como npm/webpack/vite).
- **Tailwind CSS:** Carregado via CDN.
- **Alpine.js:** Usado para reatividade simples, carregado via CDN.
- **Lucide Icons:** Carregado via CDN.
- **Jinja2:** Usado para renderização no lado do servidor (SSR) das páginas base.

## Estrutura

- `app.py`: Servidor FastAPI que renderiza os templates Jinja2.
- `templates/`: Contém os arquivos `.html`.
- `static/js/api.js`: Biblioteca JS pura que encapsula as chamadas para a Web API.

## Desenvolvimento

Para adicionar novas funcionalidades:
1. Adicione a rota no `app.py`.
2. Crie o template em `templates/`.
3. Use a instância `this.api` (do Alpine.js) para interagir com o backend.

## Execução

```bash
uv run simple-orchestrator-frontend
```
