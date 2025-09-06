from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, ForeignKey ,DateTime
from sqlalchemy.orm import relationship
from database.database import Base

class Article(Base):
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(String, default='draft', nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Use string-based relationship to avoid circular imports
    author = relationship("User", back_populates="articles", lazy="joined")
