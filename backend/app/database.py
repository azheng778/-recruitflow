from __future__ import annotations

from collections.abc import Generator
import hashlib
import re
import time

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


settings.validate_database_boundary()


class Base(DeclarativeBase):
    pass


class TracedSession(Session):
    def commit(self) -> None:
        from .agent.trace import span
        with span("db.transaction.commit", "db"):
            super().commit()

    def rollback(self) -> None:
        from .agent.trace import span
        with span("db.transaction.rollback", "db"):
            super().rollback()


engine = create_engine(
    settings.database_url(),
    pool_pre_ping=True,
    pool_recycle=1800,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=TracedSession)


@event.listens_for(engine, "before_cursor_execute")
def _trace_sql_before(conn, cursor, statement, parameters, context, executemany):
    context._recruitflow_started_ns = time.perf_counter_ns()


@event.listens_for(engine, "after_cursor_execute")
def _trace_sql_after(conn, cursor, statement, parameters, context, executemany):
    started = getattr(context, "_recruitflow_started_ns", None)
    if started is None:
        return
    from .agent.trace import record_duration
    normalized = re.sub(r"\s+", " ", statement.strip())
    operation = normalized.split(" ", 1)[0].upper() if normalized else "UNKNOWN"
    table_match = re.search(r"(?:FROM|INTO|UPDATE|JOIN)\s+[`\"]?([\w]+)", normalized, re.IGNORECASE)
    attributes = {
        "operation": operation,
        "table": table_match.group(1) if table_match else None,
        "statement_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
        "executemany": bool(executemany),
    }
    if settings.agent_trace_sql_text:
        attributes["normalized_sql"] = normalized[:1000]
    record_duration(
        "db.sql.execute", "db",
        (time.perf_counter_ns() - started) / 1_000_000,
        attributes,
    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
