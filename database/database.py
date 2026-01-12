from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import settings

# Get database URL from settings
DATABASE_URL = settings.DATABASE_URL

# Create database engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_size=10,  # Maintain 10 persistent connections
    max_overflow=5,  # Allow up to 5 overflow connections
    pool_timeout=30,  # 30 seconds timeout
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
