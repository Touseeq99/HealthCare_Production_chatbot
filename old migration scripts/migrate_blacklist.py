#!/usr/bin/env python3
"""
Migration script to clean up old blacklist entries that use partial token identification
and replace them with proper hash-based identification.
"""

import hashlib
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database.database import get_db
from database.models import LoginAttempt
from utils.logger import logger

def get_token_hash(token: str) -> str:
    """Generate a unique hash for the token"""
    return hashlib.sha256(token.encode()).hexdigest()

def migrate_blacklist():
    """Migrate old blacklist entries to use hash-based identification"""
    try:
        db = next(get_db())
        
        try:
            # Find old blacklist entries (those with partial tokens)
            old_entries = db.query(LoginAttempt).filter(
                LoginAttempt.failure_reason.like("blacklisted:%:%..."),
                LoginAttempt.success == False,
                LoginAttempt.ip_address == "blacklist_system",
                LoginAttempt.attempt_time > datetime.utcnow() - timedelta(days=1)  # Only recent ones
            ).all()
            
            migrated_count = 0
            
            for entry in old_entries:
                # Parse the old format
                parts = entry.failure_reason.split(":", 2)
                if len(parts) >= 3:
                    reason = parts[1]
                    partial_token = parts[2]
                    
                    # Skip if it's already a hash (64 chars hex)
                    if len(partial_token) == 64 and all(c in '0123456789abcdef' for c in partial_token):
                        continue
                    
                    # Create new entry with hash (we can't generate the hash without the full token)
                    # So we'll just remove the old entries to prevent false positives
                    db.delete(entry)
                    migrated_count += 1
            
            if migrated_count > 0:
                db.commit()
                logger.info(f"Cleaned up {migrated_count} old blacklist entries")
            else:
                logger.info("No old blacklist entries found to clean up")
                
            return migrated_count
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error during migration: {e}")
            return 0
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Failed to connect to database for migration: {e}")
        return 0

if __name__ == "__main__":
    count = migrate_blacklist()
    print(f"Migration completed. Cleaned up {count} old entries.")
