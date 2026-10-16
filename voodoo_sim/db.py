"""SQLite persistence layer, implemented with SQLAlchemy 2.x."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import os
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, Integer, String, create_engine, event, select, desc
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class OverclockProfile(Base):
    __tablename__ = "perfis_overclock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    core_clock_mhz: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_clock_mhz: Mapped[int] = mapped_column(Integer, nullable=False)
    vcore_v: Mapped[float] = mapped_column(Float, nullable=False)
    ambient_temp_c: Mapped[float] = mapped_column(Float, nullable=False, default=25.0)
    cooling_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="Passiva")
    is_stable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stability_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class BenchmarkHistory(Base):
    __tablename__ = "historico_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )
    core_clock_mhz: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_clock_mhz: Mapped[int] = mapped_column(Integer, nullable=False)
    vcore_v: Mapped[float] = mapped_column(Float, nullable=False)
    ambient_temp_c: Mapped[float] = mapped_column(Float, nullable=False)
    cooling_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    resolution: Mapped[str] = mapped_column(String(20), nullable=False)
    workload: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fps_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    temp_peak_c: Mapped[float] = mapped_column(Float, nullable=False)
    temp_steady_c: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_power_w: Mapped[float] = mapped_column(Float, nullable=False)
    crash_probability: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)


def _resolve_database_url(database_url: str | None = None) -> str:
    if database_url:
        return database_url
    configured_url = os.getenv("VOODOO_DATABASE_URL")
    if configured_url:
        return configured_url
    path = Path(os.getenv("VOODOO_DB_PATH", "data/voodoo_sim.db")).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


@lru_cache(maxsize=8)
def get_engine(database_url: str | None = None) -> Engine:
    url = _resolve_database_url(database_url)
    connect_args = {"check_same_thread": False, "timeout": 10} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def initialize_database(engine: Engine | None = None) -> Engine:
    db_engine = engine or get_engine()
    Base.metadata.create_all(db_engine)
    return db_engine


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    db_engine = initialize_database(engine)
    factory = sessionmaker(bind=db_engine, expire_on_commit=False, class_=Session)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def list_profiles(engine: Engine | None = None) -> list[OverclockProfile]:
    with session_scope(engine) as session:
        return list(session.scalars(select(OverclockProfile).order_by(OverclockProfile.name.asc())))


def get_profile_by_name(name: str, engine: Engine | None = None) -> OverclockProfile | None:
    with session_scope(engine) as session:
        return session.scalar(select(OverclockProfile).where(OverclockProfile.name == name))


def save_profile(
    *,
    name: str,
    core_clock_mhz: int,
    memory_clock_mhz: int,
    vcore_v: float,
    ambient_temp_c: float,
    cooling_mode: str,
    is_stable: bool,
    stability_risk: float,
    engine: Engine | None = None,
) -> int:
    clean_name = " ".join(name.strip().split())
    if not clean_name:
        raise ValueError("Informe um nome para o perfil.")
    if len(clean_name) > 100:
        raise ValueError("O nome do perfil deve ter até 100 caracteres.")
    with session_scope(engine) as session:
        item = OverclockProfile(
            name=clean_name,
            core_clock_mhz=core_clock_mhz,
            memory_clock_mhz=memory_clock_mhz,
            vcore_v=vcore_v,
            ambient_temp_c=ambient_temp_c,
            cooling_mode=cooling_mode,
            is_stable=is_stable,
            stability_risk=stability_risk,
        )
        session.add(item)
        session.flush()
        return item.id


def delete_profile(profile_id: int, engine: Engine | None = None) -> bool:
    with session_scope(engine) as session:
        item = session.get(OverclockProfile, profile_id)
        if item is None:
            return False
        session.delete(item)
        return True


def save_benchmark(
    *,
    core_clock_mhz: int,
    memory_clock_mhz: int,
    vcore_v: float,
    ambient_temp_c: float,
    cooling_mode: str,
    resolution: str,
    workload: str,
    score: float | None,
    fps_estimate: float,
    temp_peak_c: float,
    temp_steady_c: float,
    estimated_power_w: float,
    crash_probability: float,
    status: str,
    engine: Engine | None = None,
) -> int:
    with session_scope(engine) as session:
        item = BenchmarkHistory(
            core_clock_mhz=core_clock_mhz,
            memory_clock_mhz=memory_clock_mhz,
            vcore_v=vcore_v,
            ambient_temp_c=ambient_temp_c,
            cooling_mode=cooling_mode,
            resolution=resolution,
            workload=workload,
            score=score,
            fps_estimate=fps_estimate,
            temp_peak_c=temp_peak_c,
            temp_steady_c=temp_steady_c,
            estimated_power_w=estimated_power_w,
            crash_probability=crash_probability,
            status=status,
        )
        session.add(item)
        session.flush()
        return item.id


def list_benchmarks(limit: int = 100, engine: Engine | None = None) -> list[BenchmarkHistory]:
    safe_limit = max(1, min(int(limit), 1000))
    with session_scope(engine) as session:
        statement = select(BenchmarkHistory).order_by(desc(BenchmarkHistory.created_at_utc), desc(BenchmarkHistory.id)).limit(safe_limit)
        return list(session.scalars(statement))


def clear_benchmark_history(engine: Engine | None = None) -> int:
    with session_scope(engine) as session:
        items = list(session.scalars(select(BenchmarkHistory)))
        for item in items:
            session.delete(item)
        return len(items)
