from sqlalchemy import MetaData
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import close_all_sessions, scoped_session, sessionmaker

__all__ = ("metadata", "base", "Base", "Session", "configure")


Base = declarative_base()
base = Base
metadata: MetaData = Base.metadata
Session = scoped_session(sessionmaker())


def configure(bind: Engine = None, future: bool = False) -> None:
    metadata.bind = bind
    close_all_sessions()
    Session.remove()
    Session.configure(bind=bind, future=future)
