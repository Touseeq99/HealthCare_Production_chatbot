from typing import List, Dict, Any, Optional
from supabase import Client
from datetime import datetime
import json

class LongTermMemory:
    """Supabase-based long-term memory storage"""
    
    def __init__(self, supabase: Client):
        self.supabase = supabase
    
    def create_session(self, user_id: str, session_type: str = 'patient', session_name: str = None) -> Dict[str, Any]:
        """Create a new chat session using Supabase Client"""
        data = {
            "user_id": str(user_id),
            "session_type": session_type,
            "session_name": session_name or f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "status": 'active',
            "message_count": 0,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        response = self.supabase.table('chat_sessions').insert(data).execute()
        
        if response.data:
            return response.data[0]
        raise Exception("Failed to create chat session")
    
    def save_message(self, session_id: int, content: str, role: str, 
                    message_type: str = 'chat', metadata: Dict = None) -> Dict[str, Any]:
        """Save a message to long-term storage using Supabase Client"""
        message_data = {
            "session_id": session_id,
            "content": content,
            "message_type": role,
            "message_data": metadata or {},
            "created_at": datetime.utcnow().isoformat()
        }
        
        response = self.supabase.table('chat_messages').insert(message_data).execute()
        
        if not response.data:
            raise Exception("Failed to save message")
            
        saved_message = response.data[0]
        
        # Fetch current message_count and increment it
        session_response = self.supabase.table('chat_sessions')\
            .select('message_count')\
            .eq('id', session_id)\
            .single()\
            .execute()
        
        current_count = session_response.data.get('message_count', 0) if session_response.data else 0
        
        now = datetime.utcnow().isoformat()
        self.supabase.table('chat_sessions').update({
            "message_count": current_count + 1,
            "last_message_at": now,
            "updated_at": now
        }).eq('id', session_id).execute()
        
        return saved_message

    
    def get_session_messages(self, session_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Get messages from a session using Supabase Client"""
        response = self.supabase.table('chat_messages')\
            .select('*')\
            .eq('session_id', session_id)\
            .order('created_at', desc=False)\
            .limit(limit)\
            .execute()
        return response.data or []
    
    def get_recent_context(self, session_id: int, message_count: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages for context using Supabase Client"""
        response = self.supabase.table('chat_messages')\
            .select('*')\
            .eq('session_id', session_id)\
            .order('created_at', desc=True)\
            .limit(message_count)\
            .execute()
        
        messages = response.data or []
        # Reverse to get chronological order
        messages.reverse()
        
        return [
            {
                "message_id": msg['id'],
                "content": msg['content'],
                "role": msg['message_type'],
                "timestamp": msg['created_at'],
                "message_data": msg['message_data']
            }
            for msg in messages
        ]
    
    def get_user_sessions(self, user_id: str, status: str = 'active') -> List[Dict[str, Any]]:
        """Get all sessions for a user using Supabase Client"""
        response = self.supabase.table('chat_sessions')\
            .select('*')\
            .eq('user_id', str(user_id))\
            .eq('status', status)\
            .order('updated_at', desc=True)\
            .execute()
        return response.data or []
    
    def update_session_name(self, session_id: int, name: str) -> bool:
        """Update session name using Supabase Client"""
        response = self.supabase.table('chat_sessions').update({
            "session_name": name,
            "updated_at": datetime.utcnow().isoformat()
        }).eq('id', session_id).execute()
        return len(response.data) > 0
    
    def archive_session(self, session_id: int) -> bool:
        """Archive a session using Supabase Client"""
        response = self.supabase.table('chat_sessions').update({
            "status": 'archived',
            "updated_at": datetime.utcnow().isoformat()
        }).eq('id', session_id).execute()
        return len(response.data) > 0
    
    def delete_session(self, session_id: int) -> bool:
        """Delete a session using Supabase Client"""
        # Cascading delete should be handled by DB foreign keys
        response = self.supabase.table('chat_sessions').delete().eq('id', session_id).execute()
        return len(response.data) > 0
    
    def get_session_stats(self, session_id: int) -> Dict[str, Any]:
        """Get session statistics using Supabase Client"""
        response = self.supabase.table('chat_sessions').select('*').eq('id', session_id).single().execute()
        if not response.data:
            return {}
        
        session = response.data
        return {
            "session_id": session['id'],
            "session_name": session['session_name'],
            "message_count": session['message_count'],
            "created_at": session['created_at'],
            "last_message_at": session['last_message_at'],
            "status": session['status']
        }
