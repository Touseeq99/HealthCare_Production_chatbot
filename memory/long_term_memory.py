from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from database.database import get_db
from database.models import ChatSession, ChatMessage, User
from datetime import datetime
import json

class LongTermMemory:
    """PostgreSQL-based long-term memory storage"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_session(self, user_id: int, session_type: str = 'patient', session_name: str = None) -> ChatSession:
        """Create a new chat session"""
        session = ChatSession(
            user_id=user_id,
            session_type=session_type,
            session_name=session_name or f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            status='active',
            message_count=0
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session
    
    def save_message(self, session_id: int, content: str, role: str, 
                    message_type: str = 'chat', metadata: Dict = None) -> ChatMessage:
        """Save a message to long-term storage"""
        message = ChatMessage(
            session_id=session_id,
            content=content,
            message_type=role,
            message_data=metadata or {},
            created_at=datetime.utcnow()
        )
        
        self.db.add(message)
        
        # Update session message count and last message time
        session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session:
            session.message_count += 1
            session.last_message_at = datetime.utcnow()
            session.updated_at = datetime.utcnow()
        
        self.db.commit()
        self.db.refresh(message)
        return message
    
    def get_session_messages(self, session_id: int, limit: int = 50) -> List[ChatMessage]:
        """Get messages from a session"""
        return self.db.query(ChatMessage)\
            .filter(ChatMessage.session_id == session_id)\
            .order_by(ChatMessage.created_at.asc())\
            .limit(limit)\
            .all()
    
    def get_recent_context(self, session_id: int, message_count: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages for context"""
        messages = self.db.query(ChatMessage)\
            .filter(ChatMessage.session_id == session_id)\
            .order_by(ChatMessage.created_at.desc())\
            .limit(message_count)\
            .all()
        
        # Reverse to get chronological order
        messages.reverse()
        
        return [
            {
                "message_id": msg.id,
                "content": msg.content,
                "role": msg.message_type,
                "timestamp": msg.created_at.isoformat(),
                "message_data": msg.message_data
            }
            for msg in messages
        ]
    
    def get_user_sessions(self, user_id: int, status: str = 'active') -> List[ChatSession]:
        """Get all sessions for a user"""
        return self.db.query(ChatSession)\
            .filter(ChatSession.user_id == user_id, ChatSession.status == status)\
            .order_by(ChatSession.updated_at.desc())\
            .all()
    
    def update_session_name(self, session_id: int, name: str) -> bool:
        """Update session name"""
        session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session:
            session.session_name = name
            session.updated_at = datetime.utcnow()
            self.db.commit()
            return True
        return False
    
    def archive_session(self, session_id: int) -> bool:
        """Archive a session"""
        session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session:
            session.status = 'archived'
            session.updated_at = datetime.utcnow()
            self.db.commit()
            return True
        return False
    
    def delete_session(self, session_id: int) -> bool:
        """Delete a session and all its messages"""
        session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session:
            self.db.delete(session)  # This will cascade delete messages
            self.db.commit()
            return True
        return False
    
    def get_session_stats(self, session_id: int) -> Dict[str, Any]:
        """Get session statistics"""
        session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not session:
            return {}
        
        return {
            "session_id": session.id,
            "session_name": session.session_name,
            "message_count": session.message_count,
            "created_at": session.created_at.isoformat(),
            "last_message_at": session.last_message_at.isoformat() if session.last_message_at else None,
            "status": session.status
        }
