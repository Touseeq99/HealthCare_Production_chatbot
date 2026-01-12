from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ChatMessage:
    content: str
    role: str  # 'user' or 'assistant'
    timestamp: datetime
    session_id: Optional[int] = None
    message_type: str = 'chat'  # 'chat', 'system', etc.

class CurrentChatMemory:
    """In-memory storage for current chat context (last 2 messages)"""
    
    def __init__(self):
        self._sessions: Dict[int, List[ChatMessage]] = {}
    
    def add_message(self, session_id: int, message: ChatMessage) -> None:
        """Add a message to the session memory"""
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        
        message.session_id = session_id
        self._sessions[session_id].append(message)
        
        # Keep only last 2 messages
        if len(self._sessions[session_id]) > 2:
            self._sessions[session_id] = self._sessions[session_id][-2:]
    
    def get_context(self, session_id: int) -> List[Dict[str, Any]]:
        """Get the last 2 messages for context"""
        if session_id not in self._sessions:
            return []
        
        return [
            {
                "role": msg.role,
                "content": msg.content
            }
            for msg in self._sessions[session_id]
        ]
    
    def clear_session(self, session_id: int) -> None:
        """Clear memory for a specific session"""
        if session_id in self._sessions:
            del self._sessions[session_id]
    
    def get_session_message_count(self, session_id: int) -> int:
        """Get number of messages in current memory for session"""
        return len(self._sessions.get(session_id, []))

# Global instance for current chat memory
current_memory = CurrentChatMemory()
