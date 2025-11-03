from datetime import datetime
from sqlalchemy import Column, String, DateTime, Enum, Text, ForeignKey, JSON, Integer, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False)
    role = Column(Enum('patient', 'doctor', 'admin', name='user_roles'), nullable=False)
    name = Column(String, nullable=False)
    surname = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    specialization = Column(String, nullable=True)
    doctor_register_number = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Use string-based relationships to avoid circular imports
    articles = relationship("Article", back_populates="author", lazy="dynamic")
    chat_sessions = relationship("ChatSession", back_populates="user")

class Article(Base):
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = Column(String, default='draft', nullable=False)

    # Relationships
    author = relationship("User", back_populates="articles")

class ChatSession(Base):
    __tablename__ = 'chat_sessions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    messages = Column(JSON, default=list)  # Stores array of {content: string, sender: string, timestamp: datetime}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="chat_sessions")


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