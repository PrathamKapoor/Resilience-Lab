"""Database connection management for the control plane."""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_default_url = "postgresql+psycopg://resiliencelab:resiliencelab@127.0.0.1:5432/resiliencelab"


def _resolve_db_url() -> str:
    return os.environ.get("RESILIENCELAB_DATABASE_URL", _default_url)


def get_engine(url: str | None = None) -> Engine:
    resolved = url or _resolve_db_url()
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if not resolved.startswith("sqlite"):
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
    # Use psycopg3 driver if psycopg2 is not available
    if resolved.startswith("postgresql://"):
        try:
            import psycopg  # noqa: F401

            resolved = resolved.replace("postgresql://", "postgresql+psycopg://", 1)
        except ImportError:
            pass
    engine = create_engine(resolved, **kwargs)
    return engine


_session_factory: sessionmaker[Session] | None = None


def init_session_factory(url: str | None = None) -> sessionmaker[Session]:
    global _session_factory
    engine = get_engine(url)
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return _session_factory


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        return init_session_factory()
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_session() -> Session:
    factory = get_session_factory()
    return factory()
