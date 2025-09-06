from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import settings

# Get database URL from settings
DATABASE_URL = settings.DATABASE_URL

# Create database engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_size=22,  # Maintain 5 persistent connections
    max_overflow=10,  # Allow up to 10 overflow connections
    pool_timeout=60,  # 30 seconds timeout
    pool_recycle=1800,  # Recycle connections after 30 minutes
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
