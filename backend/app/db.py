from collections.abc import Iterator
from pathlib import Path
from sqlite3 import Connection

from fastapi import Request
from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

from app.models import Base


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            URL.create("sqlite+pysqlite", database=str(path)),
            connect_args={"check_same_thread": False, "timeout": 5},
            hide_parameters=True,
        )
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, autoflush=False)

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection: Connection, record: ConnectionPoolEntry) -> None:
            cursor = connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    def initialize(self) -> None:
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()


def get_session(request: Request) -> Iterator[Session]:
    database = request.app.state.database
    if not isinstance(database, Database):
        raise RuntimeError("The application database has not been initialized")
    with database.session_factory() as session:
        yield session
