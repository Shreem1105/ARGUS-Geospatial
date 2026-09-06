from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


class ReadinessCheckError(Exception):
    def __init__(self, database_status: str, postgis_status: str) -> None:
        self.database_status = database_status
        self.postgis_status = postgis_status
        super().__init__("Database readiness check failed")


settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"connect_timeout": 5},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def check_database_readiness() -> None:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1;"))
            try:
                connection.execute(text("SELECT PostGIS_Version();")).scalar_one()
            except SQLAlchemyError as exc:
                raise ReadinessCheckError(
                    database_status="connected",
                    postgis_status="unavailable",
                ) from exc
    except ReadinessCheckError:
        raise
    except SQLAlchemyError as exc:
        raise ReadinessCheckError(
            database_status="unavailable",
            postgis_status="unavailable",
        ) from exc
