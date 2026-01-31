from datetime import datetime
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from utils.auth_dependencies import get_current_user
from utils.logger import logger
from utils.supabase_client import get_supabase_client
from config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()

# Request Models
class OnboardingRequest(BaseModel):
    role: str
    name: Optional[str] = None
    surname: Optional[str] = None
    specialization: Optional[str] = None
    doctor_register_number: Optional[str] = None

@router.post("/complete-profile")
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def complete_profile(
    request: Request,
    data: OnboardingRequest,
    current_user: Any = Depends(get_current_user)
):
    """
    Backend-controlled Onboarding:
    Updates the user profile once they've authenticated via Supabase.
    This is where medical-specific business logic lives.
    """
    try:
        # 1. Validation: Role Logic
        allowed_roles = ['patient', 'doctor']
        if data.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Invalid role. Users can only self-assign: {', '.join(allowed_roles)}"
            )

        if data.role == 'doctor':
            if not data.doctor_register_number:
                raise HTTPException(status_code=400, detail="Doctors must provide a registration number.")
        
        # 2. Update via Supabase Client
        update_data = {
            "role": data.role,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if data.name:
            update_data["name"] = data.name
        if data.surname:
            update_data["surname"] = data.surname
        if data.specialization:
            update_data["specialization"] = data.specialization
        if data.doctor_register_number:
            update_data["doctor_register_number"] = data.doctor_register_number
            
        supabase = get_supabase_client()
        response = supabase.table('users').update(update_data).eq('id', str(current_user.id)).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="User not found")
            
        updated_user = response.data[0]
        
        return {
            "success": True,
            "message": "Profile updated successfully",
            "user": {
                "id": str(updated_user["id"]),
                "role": updated_user["role"],
                "name": updated_user.get("name")
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Onboarding error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="An internal error occurred while updating your profile."
        )

@router.get("/verify-token")
async def verify_token(current_user: Any = Depends(get_current_user)):
    """
    Sanity check to verify if a Bearer token is valid and returns user info.
    """
    return {
        "status": "valid", 
        "user": {
            "id": str(current_user.id),
            "email": current_user.email,
            "role": current_user.role
        }
    }

@router.post("/logout")
async def logout(current_user: Any = Depends(get_current_user)):
    """
    Note: Logout should primarily happen on the frontend via supabase.auth.signOut().
    This endpoint is provided for server-side state clearing if needed.
    """
    supabase = get_supabase_client()
    try:
        if supabase:
            supabase.auth.sign_out()
        return {"success": True, "message": "Logged out"}
    except Exception:
        return {"success": True, "message": "Logged out"}
