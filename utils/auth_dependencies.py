from typing import Optional, Any
from datetime import datetime
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from utils.supabase_client import get_supabase_client
from utils.logger import logger

# OAuth2 scheme: Points to dummy path since we use Direct Supabase Auth
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/verify-token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Authenticate user using Supabase Auth and fetch profile from local DB using Supabase Client.
    """
    try:
        supabase = get_supabase_client()
        if not supabase:
             raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Supabase client not initialized"
            )

        # Verify token with Supabase
        user_response = supabase.auth.get_user(token)
        if not user_response or not user_response.user:
             raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Get Supabase User ID
        supabase_user_id = user_response.user.id
        
        # Fetch user from local DB using Supabase client
        response = supabase.table('users').select('*').eq('id', supabase_user_id).execute()
        
        if not response.data or len(response.data) == 0:
             # In case of sync issues, you might want to auto-create logic here
             # For now, stricter is safer
             raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found",
            )
            
        # Return the user data as a dictionary (or we could wrap it in an object)
        # Most of the app expects an object with attributes, so let's wrap it in a SimpleNamespace or a Pydantic model
        from types import SimpleNamespace
        user = SimpleNamespace(**response.data[0])
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_active_user(current_user: Any = Depends(get_current_user)):
    """Get current active user"""
    return current_user
