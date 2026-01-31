from typing import List, Dict, Any, Optional, Tuple
from supabase import Client
from datetime import datetime
from fastapi import Depends
from utils.logger import logger
from memory.current_memory import current_memory, ChatMessage
from memory.long_term_memory import LongTermMemory
from utils.supabase_client import get_supabase_client

class MemoryManager:
    """Coordinates between current memory and long-term storage using Supabase Client"""
    
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.long_term = LongTermMemory(supabase)
        self.current_memory = current_memory
    
    def create_or_get_session(self, user_id: str, session_id: Optional[int] = None, 
                             session_type: str = 'patient') -> Dict[str, Any]:
        """Create new session or get existing one using Supabase Client"""
        if session_id:
            response = self.supabase.table('chat_sessions').select('*')\
                .eq('id', session_id)\
                .eq('user_id', str(user_id))\
                .eq('status', 'active')\
                .execute()
            
            if response.data:
                return response.data[0]
        
        # Create new session
        return self.long_term.create_session(user_id, session_type)
    
    def add_message(self, session_id: int, user_id: str, content: str, 
                   role: str, save_to_long_term: bool = True) -> Dict[str, Any]:
        """Add message to both current memory and long-term storage"""
        
        # Add to current memory (for immediate context)
        chat_message = ChatMessage(
            content=content,
            role=role,
            timestamp=datetime.utcnow()
        )
        self.current_memory.add_message(session_id, chat_message)
        
        # Save to long-term storage
        if save_to_long_term:
            saved_message = self.long_term.save_message(
                session_id=session_id,
                content=content,
                role=role,
                message_type='chat'
            )
            return {
                "message_id": saved_message['id'],
                "session_id": session_id,
                "content": content,
                "role": role,
                "timestamp": saved_message['created_at'],
                "saved_to_long_term": True
            }
        
        return {
            "session_id": session_id,
            "content": content,
            "role": role,
            "timestamp": datetime.utcnow().isoformat(),
            "saved_to_long_term": False
        }
    
    def get_context_for_llm(self, session_id: int, include_long_term: bool = False, 
                            long_term_limit: int = 5) -> List[Dict[str, Any]]:
        """Get context formatted for LLM (last 2 messages + optional long-term)"""
        
        # Get current memory context (last 2 messages)
        current_context = self.current_memory.get_context(session_id)
        
        if not include_long_term:
            return current_context
        
        # Get additional context from long-term storage
        long_term_context = self.long_term.get_recent_context(
            session_id, 
            message_count=long_term_limit
        )
        
        # Combine contexts, avoiding duplicates
        all_messages = long_term_context + current_context
        
        # Remove duplicates (keep last occurrence)
        seen = set()
        unique_context = []
        for msg in reversed(all_messages):
            msg_key = f"{msg['role']}:{msg['content'][:50]}"  # First 50 chars as key
            if msg_key not in seen:
                seen.add(msg_key)
                unique_context.append(msg)
        
        return list(reversed(unique_context))
    
    def get_session(self, session_id: int, user_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID with ownership verification using Supabase Client"""
        response = self.supabase.table('chat_sessions').select('*')\
            .eq('id', session_id)\
            .eq('user_id', str(user_id))\
            .eq('status', 'active')\
            .execute()
        return response.data[0] if response.data else None
    
    def get_session_history(self, session_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Get full session history from long-term storage"""
        messages = self.long_term.get_session_messages(session_id, limit)
        return [
            {
                "message_id": msg['id'],
                "content": msg['content'],
                "role": msg['message_type'],
                "timestamp": msg['created_at'],
                "metadata": msg.get('message_data', {})
            }
            for msg in messages
        ]
    
    def get_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all active sessions for a user"""
        sessions = self.long_term.get_user_sessions(user_id)
        return [
            {
                "session_id": session['id'],
                "session_name": session['session_name'],
                "session_type": session['session_type'],
                "message_count": session['message_count'],
                "created_at": session['created_at'],
                "last_message_at": session['last_message_at'],
                "status": session['status']
            }
            for session in sessions
        ]
    
    def clear_current_memory(self, session_id: int) -> None:
        """Clear current memory for a session"""
        self.current_memory.clear_session(session_id)
    
    def archive_session(self, session_id: int, user_id: str) -> bool:
        """Archive session and clear current memory"""
        success = self.long_term.archive_session(session_id)
        if success:
            self.clear_current_memory(session_id)
        return success
    
    def delete_session(self, session_id: int, user_id: str) -> bool:
        """Delete session and clear current memory"""
        # Verify ownership
        response = self.supabase.table('chat_sessions').select('id')\
            .eq('id', session_id)\
            .eq('user_id', str(user_id))\
            .execute()
        
        if not response.data:
            return False
        
        success = self.long_term.delete_session(session_id)
        if success:
            self.clear_current_memory(session_id)
        return success
    
    def get_session_stats(self, session_id: int, user_id: str) -> Dict[str, Any]:
        """Get session statistics"""
        # Verify ownership
        response = self.supabase.table('chat_sessions').select('id')\
            .eq('id', session_id)\
            .eq('user_id', str(user_id))\
            .execute()
            
        if not response.data:
            return {}
        
        stats = self.long_term.get_session_stats(session_id)
        stats['current_memory_count'] = self.current_memory.get_session_message_count(session_id)
        return stats

# Dependency function for FastAPI
def get_memory_manager(supabase: Client = Depends(get_supabase_client)):
    """Get memory manager instance using Supabase Client"""
    return MemoryManager(supabase)
