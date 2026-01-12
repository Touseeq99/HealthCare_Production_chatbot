#!/usr/bin/env python3
"""
Script to empty all database tables and reset auto-increment IDs.
This script will delete all data from the database and reset all sequences to start from 1.
"""

import sys
import os
from sqlalchemy import text
from database.database import engine, Base
from database.models import *

def clear_database():
    """Clear all tables and reset auto-increment IDs"""
    print("⚠️  WARNING: This will delete ALL data in the database!")
    print("Tables to be cleared:")
    
    # Get all table names from the models
    tables = [
        'login_attempts',
        'refresh_tokens', 
        'chat_sessions',
        'articles',
        'research_paper_scores',
        'research_paper_keywords',
        'research_paper_comments',
        'research_papers',
        'users'
    ]
    
    for table in tables:
        print(f"  - {table}")
    
    # Ask for confirmation
    confirm = input("\nAre you sure you want to proceed? (type 'DELETE ALL DATA' to confirm): ")
    if confirm != 'DELETE ALL DATA':
        print("Operation cancelled.")
        return
    
    print("\n🗑️  Clearing database...")
    
    try:
        with engine.connect() as conn:
            # Begin transaction
            trans = conn.begin()
            
            try:
                # Disable foreign key constraints temporarily (for PostgreSQL)
                if 'postgresql' in str(engine.url).lower():
                    conn.execute(text("SET session_replication_role = replica;"))
                elif 'mysql' in str(engine.url).lower():
                    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
                elif 'sqlite' in str(engine.url).lower():
                    conn.execute(text("PRAGMA foreign_keys = OFF;"))
                
                # Delete all data in correct order (child tables first)
                for table in tables:
                    print(f"  Deleting from {table}...")
                    conn.execute(text(f"DELETE FROM {table}"))
                
                # Reset auto-increment sequences
                print("  Resetting auto-increment sequences...")
                if 'postgresql' in str(engine.url).lower():
                    # PostgreSQL sequences
                    sequences = [
                        'login_attempts_id_seq',
                        'refresh_tokens_id_seq',
                        'chat_sessions_id_seq', 
                        'articles_id_seq',
                        'research_paper_scores_id_seq',
                        'research_paper_keywords_id_seq',
                        'research_paper_comments_id_seq',
                        'research_papers_id_seq',
                        'users_id_seq'
                    ]
                    for seq in sequences:
                        try:
                            conn.execute(text(f"ALTER SEQUENCE {seq} RESTART WITH 1"))
                        except Exception as e:
                            print(f"    Warning: Could not reset sequence {seq}: {e}")
                            
                elif 'mysql' in str(engine.url).lower():
                    # MySQL auto-increment
                    for table in tables:
                        conn.execute(text(f"ALTER TABLE {table} AUTO_INCREMENT = 1"))
                        
                elif 'sqlite' in str(engine.url).lower():
                    # SQLite auto-increment
                    for table in tables:
                        conn.execute(text(f"DELETE FROM sqlite_sequence WHERE name='{table}'"))
                
                # Re-enable foreign key constraints
                if 'postgresql' in str(engine.url).lower():
                    conn.execute(text("SET session_replication_role = DEFAULT;"))
                elif 'mysql' in str(engine.url).lower():
                    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
                elif 'sqlite' in str(engine.url).lower():
                    conn.execute(text("PRAGMA foreign_keys = ON;"))
                
                # Commit transaction
                trans.commit()
                print("\n✅ Database cleared successfully!")
                print("All tables are now empty and IDs will start from 1.")
                
            except Exception as e:
                trans.rollback()
                print(f"\n❌ Error during database clearing: {e}")
                raise
                
    except Exception as e:
        print(f"\n❌ Database connection error: {e}")
        sys.exit(1)

def show_database_info():
    """Show current database information"""
    try:
        with engine.connect() as conn:
            # Get database type
            db_type = str(engine.url).split('+')[0].split(':')[0]
            print(f"Database Type: {db_type}")
            print(f"Database URL: {engine.url}")
            
            # Count records in each table
            tables = [
                'login_attempts',
                'refresh_tokens',
                'chat_sessions', 
                'articles',
                'research_paper_scores',
                'research_paper_keywords',
                'research_paper_comments',
                'research_papers',
                'users'
            ]
            
            print("\nCurrent record counts:")
            for table in tables:
                try:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                    print(f"  {table}: {count} records")
                except Exception as e:
                    print(f"  {table}: Error - {e}")
                    
    except Exception as e:
        print(f"Error connecting to database: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--info":
        show_database_info()
    else:
        print("=== Database Clearing Script ===")
        print("This script will delete ALL data and reset IDs.")
        print()
        show_database_info()
        print()
        clear_database()
