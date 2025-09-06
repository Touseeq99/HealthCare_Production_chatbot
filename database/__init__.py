# Import all models to ensure they are registered with SQLAlchemy
from .models import Base, User, ChatSession
from .article import Article

# This ensures that all models are imported and registered with SQLAlchemy
# before any relationships are configured
__all__ = ['Base', 'User', 'ChatSession', 'Article']
