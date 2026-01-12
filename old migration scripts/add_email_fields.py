"""
Database migration script to add email verification and password reset fields to users table.
Run this script to update your existing database schema.
"""

import sys
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
def add_email_fields():
    """Add email verification and password reset fields to users table"""
    try:
        # Get database URL from environment or use default
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            print("❌ DATABASE_URL environment variable not found")
            print("Please set DATABASE_URL in your .env file or environment")
            sys.exit(1)
        
        # Create database connection
        engine = create_engine(database_url)
        
        with engine.connect() as connection:
            # Check if columns already exist
            result = connection.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'users' 
                AND column_name IN ('email_verified', 'email_verification_token', 
                                   'email_verification_expires', 'password_reset_token', 
                                   'password_reset_expires')
            """)).fetchall()
            
            existing_columns = [row[0] for row in result]
            
            # Add email_verified column
            if 'email_verified' not in existing_columns:
                connection.execute(text("""
                    ALTER TABLE users 
                    ADD COLUMN email_verified BOOLEAN DEFAULT FALSE NOT NULL
                """))
                print("✅ Added email_verified column")
            else:
                print("ℹ️ email_verified column already exists")
            
            # Add email_verification_token column
            if 'email_verification_token' not in existing_columns:
                connection.execute(text("""
                    ALTER TABLE users 
                    ADD COLUMN email_verification_token VARCHAR(255)
                """))
                print("✅ Added email_verification_token column")
            else:
                print("ℹ️ email_verification_token column already exists")
            
            # Add email_verification_expires column
            if 'email_verification_expires' not in existing_columns:
                connection.execute(text("""
                    ALTER TABLE users 
                    ADD COLUMN email_verification_expires TIMESTAMP
                """))
                print("✅ Added email_verification_expires column")
            else:
                print("ℹ️ email_verification_expires column already exists")
            
            # Add password_reset_token column
            if 'password_reset_token' not in existing_columns:
                connection.execute(text("""
                    ALTER TABLE users 
                    ADD COLUMN password_reset_token VARCHAR(255)
                """))
                print("✅ Added password_reset_token column")
            else:
                print("ℹ️ password_reset_token column already exists")
            
            # Add password_reset_expires column
            if 'password_reset_expires' not in existing_columns:
                connection.execute(text("""
                    ALTER TABLE users 
                    ADD COLUMN password_reset_expires TIMESTAMP
                """))
                print("✅ Added password_reset_expires column")
            else:
                print("ℹ️ password_reset_expires column already exists")
            
            # Commit the transaction
            connection.commit()
            print("\n🎉 Database migration completed successfully!")
            
            # Set existing users as email_verified (for backward compatibility)
            connection.execute(text("""
                UPDATE users 
                SET email_verified = TRUE 
                WHERE email_verified IS NULL OR email_verified = FALSE
            """))
            connection.commit()
            print("✅ Existing users marked as email_verified for backward compatibility")
            
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    print("🔄 Starting database migration for email verification fields...")
    add_email_fields()
