from supabase import create_client, Client
from config import settings
import logging

logger = logging.getLogger(__name__)

def get_supabase_client() -> Client:
    """
    Initialize and return a Supabase client.
    """
    url = settings.SUPABASE_URL
    key = settings.SUPABASE_SERVICE_KEY
    
    if not url or not key:
        logger.warning("Supabase credentials not found in settings. Supabase client will not work.")
        # Return a dummy client or raise error? For now, let's let it fail naturally or return None.
        # But type hint says Client. 
        # In dev, we might tolerate missing creds if not hitting it.
        pass
        
    try:
        supabase: Client = create_client(url, key)
        return supabase
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        raise
