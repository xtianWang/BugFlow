from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
