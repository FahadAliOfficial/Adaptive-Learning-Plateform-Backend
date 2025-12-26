"""
Centralized database configuration.
Used by all models and services.

This is the SINGLE SOURCE OF TRUTH for database setup.
All models import Base from here to ensure consistency.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import contextmanager
import os
from dotenv import load_dotenv

load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set in .env file")

# Engine with optimized pooling
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,    # Verify connections before using
    pool_size=20,          # Number of connections to keep open
    max_overflow=40,       # Max additional connections when pool full
    echo=False             # Set True for SQL debugging
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ✅ THE SINGLE SOURCE OF TRUTH FOR BASE
Base = declarative_base()


# Dependency for FastAPI routes
def get_db():
    """
    Provides database session to FastAPI endpoints.
    Automatically closes connection after request.
    
    Usage in FastAPI:
        @app.get("/endpoint")
        def my_endpoint(db: Session = Depends(get_db)):
            # db is automatically provided and closed
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Context manager for scripts/services
@contextmanager
def get_db_context():
    """
    For use in scripts, seeders, migrations, etc.
    
    Usage:
        with get_db_context() as db:
            db.query(Model).all()
            # Automatically commits on success, rolls back on error
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
