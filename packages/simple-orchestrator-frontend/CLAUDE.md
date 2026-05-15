# CLAUDE.md — `simple-orchestrator-frontend` (Web Dashboard)

Scope: `packages/simple-orchestrator-frontend/`.

## Why it exists

- Provide a visual dashboard for real-time monitoring of agents, queue, MCPs, and events.
- Implement a "no-build" architecture for easy deployment and rapid prototyping.

## Main goal

Fast, reactive, and low-maintenance web interface for the orchestrator.

## Key files

| File | What it contains |
|---|---|
| `src/simple_orchestrator_frontend/app.py` | FastAPI server with Jinja2 SSR routes |
| `src/simple_orchestrator_frontend/frontend_cli.py` | CLI entry point (`uvicorn` startup) |
| `src/simple_orchestrator_frontend/templates/` | Jinja2 templates (`index`, `agents`, `mcps`, `events`) |
| `src/simple_orchestrator_frontend/static/js/api.js` | JS client for Web API interactions |

## Architecture ("No-Build")

- **Tailwind CSS**: Utility-first CSS, loaded via CDN.
- **Alpine.js**: Lightweight reativity, loaded via CDN. Global store `Alpine.store('app')` in `base.html` manages state.
- **Lucide Icons**: Icon set, loaded via CDN.
- **Jinja2**: Server-side rendering for the initial page load and structure.

## Development rules

- **Keep it simple**: Avoid complex JS build steps (npm/webpack/vite).
- **Alpine.js for state**: Use Alpine.js for interactive components and real-time updates.
- **API interactions**: Centralize all Web API calls in `static/js/api.js`. Use the global `this.api` instance in Alpine.js components.
- **Responsive design**: Use Tailwind utility classes to ensure the dashboard works on various screen sizes.

## Commands

```bash
# Start the frontend
uv run simple-orchestrator-frontend

# Or via the main CLI
uv run simple-orchestrator frontend
```

## Quick validation

Manual verification by running the frontend and navigating the dashboard.
