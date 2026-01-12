"""
Simple database migration for enhanced chat models
Run this script to update your database schema for the new chat memory system
"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL environment variable is required")
    sys.exit(1)

def migrate_database():
    """Create new tables and update existing schema"""
    
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # Check if chat_messages table exists and has the right structure
            result = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'chat_messages'
            """))
            
            if result.fetchone()[0] == 0:
                print("Creating new chat tables...")
                
                # Create enhanced chat_sessions table (replace existing)
                conn.execute(text("""
                    DROP TABLE IF EXISTS chat_sessions CASCADE
                """))
                
                conn.execute(text("""
                    CREATE TABLE chat_sessions (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        session_name VARCHAR(200),
                        session_type VARCHAR(20) NOT NULL DEFAULT 'patient',
                        status VARCHAR(20) NOT NULL DEFAULT 'active',
                        session_data JSONB DEFAULT '{}',
                        message_count INTEGER DEFAULT 0,
                        last_message_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                
                # Create chat_messages table
                conn.execute(text("""
                    CREATE TABLE chat_messages (
                        id SERIAL PRIMARY KEY,
                        session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                        content TEXT NOT NULL,
                        message_type VARCHAR(20) NOT NULL DEFAULT 'user',
                        token_count INTEGER,
                        model_used VARCHAR(100),
                        message_data JSONB DEFAULT '{}',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                
                # Create indexes
                conn.execute(text("""
                    CREATE INDEX idx_chat_sessions_user_id ON chat_sessions(user_id)
                """))
                
                conn.execute(text("""
                    CREATE INDEX idx_chat_sessions_status ON chat_sessions(status)
                """))
                
                conn.execute(text("""
                    CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id)
                """))
                
                conn.execute(text("""
                    CREATE INDEX idx_chat_messages_created_at ON chat_messages(created_at)
                """))
                
                # Create conversation_contexts table
                conn.execute(text("""
                    CREATE TABLE conversation_contexts (
                        id SERIAL PRIMARY KEY,
                        session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE UNIQUE,
                        context_summary TEXT,
                        key_topics JSONB DEFAULT '[]',
                        user_preferences JSONB DEFAULT '{}',
                        medical_context JSONB DEFAULT '{}',
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                
                conn.commit()
                print("✅ Chat tables created successfully!")
                
            else:
                print("✅ Chat tables already exist!")
        
        print("\n🎉 Database migration completed successfully!")
        print("\nNew features available:")
        print("- Enhanced chat sessions with metadata")
        print("- Individual message storage with tracking")
        print("- Conversation context management")
        print("- Session statistics and management")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate_database()
