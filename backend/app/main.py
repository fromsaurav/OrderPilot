"""FastAPI application entrypoint.

Run with: ``uvicorn app.main:app``. On startup it connects the DB pool, applies the schema
idempotently (Decision #8), and connects the Temporal client (stored on app.state).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .config import get_settings
from .db import db
from .temporal.client import get_client

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await db.init_schema()
    app.state.temporal = await get_client()
    yield
    await db.close()


app = FastAPI(title="OrderPilot — Order Supervisor", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
