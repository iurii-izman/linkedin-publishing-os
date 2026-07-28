from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from publisher_api.settings import Settings

STAGE1_ALEMBIC_REVISION = "0001_stage1_vertical"
SessionFactory = Callable[[], Session]


def create_database_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        connect_args={"connect_timeout": settings.database_connect_timeout},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def transactional_session(factory: SessionFactory) -> Iterator[Session]:
    session = factory()
    try:
        with session.begin():
            yield session
    finally:
        session.close()


def database_is_ready(engine: Engine) -> tuple[bool, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    except Exception:
        return False, "database unavailable or migrations not applied"
    if revision != STAGE1_ALEMBIC_REVISION:
        return False, "database migration revision is not current"
    return True, "ready"
