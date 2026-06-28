"""FastAPI application — thin API layer wrapping existing Phase A/B/C Python functions."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure project root is on the Python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from web.api.config import CORS_ORIGINS
from web.api.routes import sessions, filesystem, phase_a, phase_b, phase_c, phase_d, certification, artifacts
from web.api.ws import ws_endpoint

app = FastAPI(
    title="Agent Debugger Platform",
    description="Web API for the Agent Debugger pipeline (Phases A-D + Certification)",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routes
app.include_router(sessions.router)
app.include_router(filesystem.router)
app.include_router(phase_a.router)
app.include_router(phase_b.router)
app.include_router(phase_c.router)
app.include_router(phase_d.router)
app.include_router(certification.router)
app.include_router(artifacts.router)


# WebSocket endpoint
@app.websocket("/ws/{session_id}")
async def websocket_route(websocket: WebSocket, session_id: str):
    await ws_endpoint(websocket, session_id)


# Health check
@app.get("/api/health")
async def health():
    return {"status": "ok", "project_root": str(PROJECT_ROOT)}


# In production, serve the React build from web/frontend/dist
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
