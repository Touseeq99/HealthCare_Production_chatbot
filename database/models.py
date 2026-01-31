from datetime import datetime
from sqlalchemy import Column, String, DateTime, Enum, Text, ForeignKey, JSON, Integer, Boolean, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from .database import Base



class User(Base):
    __tablename__ = 'users'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    role = Column(Enum('patient', 'doctor', 'admin', 'unassigned', name='user_roles'), nullable=False)
    name = Column(String, nullable=False)
    surname = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    specialization = Column(String, nullable=True)
    doctor_register_number = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Optimized indexes
    __table_args__ = (
        Index('idx_users_email', 'email'),
        Index('idx_users_role', 'role'),
        Index('idx_users_created_at', 'created_at'),
    )

    # Use string-based relationships to avoid circular imports
    articles = relationship("Article", back_populates="author", lazy="dynamic")
    chat_sessions = relationship("ChatSession", back_populates="user")

class Article(Base):
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    author_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = Column(String, default='draft', nullable=False)

    # Relationships
    author = relationship("User", back_populates="articles")

class ChatSession(Base):
    __tablename__ = 'chat_sessions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    session_name = Column(String(200), nullable=True)  # Optional session name
    session_type = Column(Enum('patient', 'doctor', name='session_types'), nullable=False, default='patient')
    status = Column(Enum('active', 'archived', 'deleted', name='session_status'), default='active')
    session_data = Column(JSON, default=dict)  # Store session context, preferences
    message_count = Column(Integer, default=0)
    last_message_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Optimized indexes
    __table_args__ = (
        Index('idx_chat_sessions_user_id', 'user_id'),
        Index('idx_chat_sessions_session_type', 'session_type'),
        Index('idx_chat_sessions_status', 'status'),
        Index('idx_chat_sessions_last_message_at', 'last_message_at'),
        Index('idx_chat_sessions_created_at', 'created_at'),
        Index('idx_chat_sessions_user_session_type', 'user_id', 'session_type'),
    )

    # Relationships
    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")

class ChatMessage(Base):
    __tablename__ = 'chat_messages'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey('chat_sessions.id'), nullable=False, index=True)
    content = Column(Text, nullable=False)
    message_type = Column(Enum('user', 'assistant', 'system', name='message_types'), nullable=False, default='user')
    token_count = Column(Integer, nullable=True)  # For cost tracking
    model_used = Column(String(100), nullable=True)  # e.g., 'gpt-4o-mini'
    message_data = Column(JSON, default=dict)  # Store additional data like citations, confidence scores
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    session = relationship("ChatSession", back_populates="messages")

class ConversationContext(Base):
    __tablename__ = 'conversation_contexts'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey('chat_sessions.id'), nullable=False, unique=True)
    context_summary = Column(Text, nullable=True)  # AI-generated summary
    key_topics = Column(JSON, default=list)  # Array of important topics
    user_preferences = Column(JSON, default=dict)  # Learned preferences
    medical_context = Column(JSON, default=dict)  # Medical-specific context (HIPAA compliant)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    session = relationship("ChatSession", backref="context")





class ResearchPaper(Base):
    __tablename__ = 'research_papers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String, nullable=False)
    total_score = Column(Integer, nullable=False)
    confidence = Column(Integer, nullable=False)  # Stored as integer (0-100)
    paper_type = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    scores = relationship("ResearchPaperScore", back_populates="research_paper", cascade="all, delete-orphan")
    keywords = relationship("ResearchPaperKeyword", back_populates="research_paper", cascade="all, delete-orphan")
    comments = relationship("ResearchPaperComment", back_populates="research_paper", cascade="all, delete-orphan")


class ResearchPaperScore(Base):
    __tablename__ = 'research_paper_scores'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    research_paper_id = Column(Integer, ForeignKey('research_papers.id'), nullable=False)
    category = Column(String, nullable=False)  # e.g., 'Study Design', 'Sample Size Power'
    score = Column(Integer, nullable=False)
    rationale = Column(Text, nullable=False)
    max_score = Column(Integer, nullable=False, default=10)  # For flexibility in scoring systems
    
    # Relationships
    research_paper = relationship("ResearchPaper", back_populates="scores")


class ResearchPaperKeyword(Base):
    __tablename__ = 'research_paper_keywords'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    research_paper_id = Column(Integer, ForeignKey('research_papers.id'), nullable=False)
    keyword = Column(String, nullable=False)
    
    # Relationships
    research_paper = relationship("ResearchPaper", back_populates="keywords")


class ResearchPaperComment(Base):
    __tablename__ = 'research_paper_comments'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    research_paper_id = Column(Integer, ForeignKey('research_papers.id'), nullable=False)
    comment = Column(Text, nullable=False)
    is_penalty = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    research_paper = relationship("ResearchPaper", back_populates="comments")