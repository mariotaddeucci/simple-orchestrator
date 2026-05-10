from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from simple_orchestrator_core.settings import FrontendSettings

app = FastAPI(title="Simple Orchestrator Frontend")

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    settings = FrontendSettings()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "api_url": settings.api_url,
            "api_key": settings.api_key,
        },
    )


@app.get("/agents", response_class=HTMLResponse)
async def agents_page(request: Request):
    settings = FrontendSettings()
    return templates.TemplateResponse(
        request,
        "agents.html",
        {
            "api_url": settings.api_url,
            "api_key": settings.api_key,
        },
    )


@app.get("/mcps", response_class=HTMLResponse)
async def mcps_page(request: Request):
    settings = FrontendSettings()
    return templates.TemplateResponse(
        request,
        "mcps.html",
        {
            "api_url": settings.api_url,
            "api_key": settings.api_key,
        },
    )


@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request):
    settings = FrontendSettings()
    return templates.TemplateResponse(
        request,
        "events.html",
        {
            "api_url": settings.api_url,
            "api_key": settings.api_key,
        },
    )
