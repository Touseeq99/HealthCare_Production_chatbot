from sqlalchemy import create_engine
from models import Base
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def init_db():
    # Get database URL from environment
    DATABASE_URL = os.getenv("DATABASE_URL")
    
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not found in environment variables")
    
    # Create engine and connect to database
    engine = create_engine(DATABASE_URL)
    
    # Create all tables
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")

if __name__ == "__main__":
    init_db()
