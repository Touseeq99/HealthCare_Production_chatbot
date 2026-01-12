#!/usr/bin/env python3
"""
Script to clear only research paper related tables and reset their auto-increment IDs.
This script will delete all research paper data while keeping other data intact.
"""

import sys
import os
from sqlalchemy import text
from database.database import engine

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
        with engine.connect() as conn:
            # Begin transaction
            trans = conn.begin()
            
            try:
                # Disable foreign key constraints temporarily
                if 'postgresql' in str(engine.url).lower():
                    conn.execute(text("SET session_replication_role = replica;"))
                elif 'mysql' in str(engine.url).lower():
                    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
                elif 'sqlite' in str(engine.url).lower():
                    conn.execute(text("PRAGMA foreign_keys = OFF;"))
                
                # Delete all research paper data in correct order
                for table in tables:
                    print(f"  Deleting from {table}...")
                    conn.execute(text(f"DELETE FROM {table}"))
                
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
                        except Exception as e:
                            print(f"    Warning: Could not reset sequence {seq}: {e}")
                            
                elif 'mysql' in str(engine.url).lower():
                    for table in tables:
                        conn.execute(text(f"ALTER TABLE {table} AUTO_INCREMENT = 1"))
                        
                elif 'sqlite' in str(engine.url).lower():
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
        with engine.connect() as conn:
            # Get database type
            db_type = str(engine.url).split('+')[0].split(':')[0]
            print(f"Database Type: {db_type}")
            
            # Count records in research paper tables
            tables = [
                'research_papers',
                'research_paper_scores',
                'research_paper_keywords',
                'research_paper_comments'
            ]
            
            print("\nCurrent research paper record counts:")
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
        show_research_paper_info()
    else:
        print("=== Research Paper Clearing Script ===")
        print("This script will delete ALL research paper data and reset IDs.")
        print("Other data (users, articles, etc.) will remain intact.")
        print()
        show_research_paper_info()
        print()
        clear_research_papers()
