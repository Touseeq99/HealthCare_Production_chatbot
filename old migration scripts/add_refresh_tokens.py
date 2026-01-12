#!/usr/bin/env python3
"""
Database migration script to add refresh_tokens table
"""

from sqlalchemy import create_engine, text
from database.models import Base
from config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_refresh_tokens_table():
    """Add refresh_tokens table to database"""
    try:
        # Create engine
        engine = create_engine(settings.DATABASE_URL)
        
        # Create the refresh_tokens table
        logger.info("Creating refresh_tokens table...")
        
        # SQL to create the table manually
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id SERIAL PRIMARY KEY,
            token VARCHAR(255) UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMP NOT NULL,
            is_revoked BOOLEAN DEFAULT FALSE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            last_used_at TIMESTAMP NULL,
            ip_address VARCHAR(255) NULL,
            user_agent TEXT NULL
        );
        
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token ON refresh_tokens(token);
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);
        """
        
        with engine.connect() as connection:
            # Execute each statement separately
            statements = create_table_sql.split(';')
            for statement in statements:
                statement = statement.strip()
                if statement:
                    try:
                        connection.execute(text(statement))
                        logger.info(f"Executed: {statement[:50]}...")
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            logger.info(f"Table/index already exists: {statement[:50]}...")
                        else:
                            raise e
            
            connection.commit()
        
        logger.info("✅ refresh_tokens table created successfully!")
        
        # Verify table exists
        with engine.connect() as connection:
            result = connection.execute(text("SELECT COUNT(*) FROM refresh_tokens"))
            count = result.scalar()
            logger.info(f"✅ refresh_tokens table verified - current count: {count}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to create refresh_tokens table: {e}")
        return False
    finally:
        engine.dispose()

if __name__ == "__main__":
    success = add_refresh_tokens_table()
    if success:
        print("✅ Refresh token migration completed successfully!")
    else:
        print("❌ Refresh token migration failed!")
        exit(1)
