"""SQLAlchemy ORM setup — foundation for replacing raw SQL with an ORM.

Usage:
    from core.database_orm import db_session, init_db
    init_db()
    # then use db_session.query(User).all()
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base

Base = declarative_base()

_db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "frankie.db")
_engine = create_engine(f"sqlite:///{_db_path}", pool_pre_ping=True, echo=False)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=_engine))


def init_orm():
    """Import all models so Base knows about them, then create missing tables."""
    import core.models
    Base.metadata.create_all(bind=_engine)


def shutdown_session(exception=None):
    """Remove the session at the end of each request."""
    db_session.remove()
