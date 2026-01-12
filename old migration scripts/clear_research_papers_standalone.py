#!/usr/bin/env python3
"""
Standalone script to clear only research paper related tables and reset their auto-increment IDs.
This script doesn't depend on the app's configuration and works directly with environment variables.
"""

import sys
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

def get_database_url():
    """Get database URL from environment variables"""
    load_dotenv()
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ ERROR: DATABASE_URL not found in environment variables!")
        print("Please set DATABASE_URL in your .env file or environment.")
        sys.exit(1)
    
    return database_url

def clear_research_papers():
    """Clear research paper tables and reset auto-increment IDs"""
    print("⚠️  WARNING: This will delete ALL research paper data!")
    print("Tables to be cleared:")
    
    # Research paper tables in correct deletion order
    tables = [
        'research_paper_scores',
        'research_paper_keywords', 
        'research_paper_comments',
        'research_papers'
    ]
    
    for table in tables:
        print(f"  - {table}")
    
    # Ask for confirmation
    confirm = input("\nAre you sure you want to proceed? (type 'DELETE RESEARCH PAPERS' to confirm): ")
    if confirm != 'DELETE RESEARCH PAPERS':
        print("Operation cancelled.")
        return
    
    print("\n🗑️  Clearing research paper tables...")
    
    try:
        # Create engine directly from environment
        database_url = get_database_url()
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Begin transaction
            trans = conn.begin()
            
            try:
                # Note: We can't disable foreign key constraints due to insufficient privileges
                # So we'll delete in the correct order respecting foreign keys
                
                # Delete all research paper data in correct order (child tables first)
                for table in tables:
                    print(f"  Deleting from {table}...")
                    result = conn.execute(text(f"DELETE FROM {table}"))
                    print(f"    Deleted {result.rowcount} records")
                
                # Reset auto-increment sequences
                print("  Resetting auto-increment sequences...")
                if 'postgresql' in str(engine.url).lower():
                    sequences = [
                        'research_paper_scores_id_seq',
                        'research_paper_keywords_id_seq',
                        'research_paper_comments_id_seq',
                        'research_papers_id_seq'
                    ]
                    for seq in sequences:
                        try:
                            conn.execute(text(f"ALTER SEQUENCE {seq} RESTART WITH 1"))
                            print(f"    Reset sequence {seq}")
                        except Exception as e:
                            print(f"    Warning: Could not reset sequence {seq}: {e}")
                            
                elif 'mysql' in str(engine.url).lower():
                    for table in tables:
                        conn.execute(text(f"ALTER TABLE {table} AUTO_INCREMENT = 1"))
                        print(f"    Reset auto_increment for {table}")
                        
                elif 'sqlite' in str(engine.url).lower():
                    for table in tables:
                        conn.execute(text(f"DELETE FROM sqlite_sequence WHERE name='{table}'"))
                        print(f"    Reset sequence for {table}")
                
                # Note: No need to re-enable constraints since we never disabled them
                
                # Commit transaction
                trans.commit()
                print("\n✅ Research paper tables cleared successfully!")
                print("All research paper data deleted and IDs reset to start from 1.")
                
            except Exception as e:
                trans.rollback()
                print(f"\n❌ Error during clearing: {e}")
                raise
                
    except Exception as e:
        print(f"\n❌ Database connection error: {e}")
        sys.exit(1)

def show_research_paper_info():
    """Show current research paper data information"""
    try:
        database_url = get_database_url()
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Get database type
            db_type = str(engine.url).split('+')[0].split(':')[0]
            print(f"Database Type: {db_type}")
            print(f"Database URL: {engine.url}")
            
            # Count records in research paper tables
            tables = [
                'research_papers',
                'research_paper_scores',
                'research_paper_keywords',
                'research_paper_comments'
            ]
            
            print("\nCurrent research paper record counts:")
            total_records = 0
            for table in tables:
                try:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                    total_records += count
                    print(f"  {table}: {count} records")
                except Exception as e:
                    print(f"  {table}: Error - {e}")
            
            print(f"\nTotal research paper records: {total_records}")
                    
    except Exception as e:
        print(f"Error connecting to database: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--info":
        show_research_paper_info()
    else:
        print("=== Research Paper Clearing Script (Standalone) ===")
        print("This script will delete ALL research paper data and reset IDs.")
        print("Other data (users, articles, etc.) will remain intact.")
        print()
        show_research_paper_info()
        print()
        clear_research_papers()
