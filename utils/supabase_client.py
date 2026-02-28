from supabase import create_client, Client
from config import settings
import logging

logger = logging.getLogger(__name__)

# Singleton Supabase client — created once, reused across all requests
_supabase_client: Client = None

def get_supabase_client() -> Client:
    """
    Return a singleton Supabase client instance.
    The client is created once on first call and reused for all subsequent requests.
    This eliminates ~200ms of client creation overhead per request.
    """
    global _supabase_client
    
    if _supabase_client is not None:
        return _supabase_client
    
    url = settings.SUPABASE_URL
    key = settings.SUPABASE_SERVICE_KEY
    
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment variables.")
        raise ValueError("Supabase credentials not configured")
        
    try:
        _supabase_client = create_client(url, key)
        logger.info("Supabase client initialized successfully (singleton)")
        return _supabase_client
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        raise
