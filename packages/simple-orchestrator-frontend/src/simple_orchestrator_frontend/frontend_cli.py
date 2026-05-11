from __future__ import annotations

import argparse

import uvicorn
from simple_orchestrator_core.settings import FrontendSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple Orchestrator Frontend")
    parser.add_argument("--host", help="Host to bind to")
    parser.add_argument("--port", type=int, help="Port to bind to")
    args = parser.parse_args()

    settings = FrontendSettings()
    host = args.host or settings.frontend_host
    port = args.port or settings.frontend_port

    uvicorn.run("simple_orchestrator_frontend.app:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    main()
