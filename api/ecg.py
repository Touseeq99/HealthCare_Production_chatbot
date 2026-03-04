from fastapi import APIRouter, Request, Depends, status, HTTPException, File, UploadFile
from typing import Any, List, Dict, Optional
from utils.auth_dependencies import get_current_user
from utils.ecg_interpretation import interpret_ecg, parse_ecg_response
from utils.error_handler import AppException, ExternalServiceError, AuthorizationError
from utils.logger import get_request_id
from slowapi import Limiter
from slowapi.util import get_remote_address
from config import settings
import logging

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
router = APIRouter()

@router.post(
    "/ecg/interpret",
    status_code=status.HTTP_200_OK,
    summary="Interpret an ECG image",
    description="Upload an ECG image (JPEG/PNG) and get a structured interpretation report.",
    tags=["ECG Interpretation"],
)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def interpret_ecg_endpoint(
    request: Request,
    file: UploadFile = File(...),
    current_user: Any = Depends(get_current_user),
):
    """
    Interpret an ECG image using GPT-4o Vision.
    """
    # Role enforcement
    user_role = getattr(current_user, "role", None)
    if user_role not in ("doctor", "admin"):
        raise AuthorizationError(
            "Access denied. ECG interpretation is restricted to doctors and admins."
        )

    # Validate file type
    if not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Please upload an image (JPEG/PNG)."
        )

    try:
        # Read file content
        image_bytes = await file.read()
        
        # Call interpretation utility
        raw_content = await interpret_ecg(image_bytes, file.filename)
        
        # Parse response
        parsed_result = parse_ecg_response(raw_content)
        
        logger.info(
            "ECG interpretation completed",
            extra={
                "request_id": get_request_id(),
                "user_id": getattr(current_user, "id", "unknown"),
                "upload_filename": file.filename
            }
        )
        
        return parsed_result

    except Exception as exc:
        logger.error(
            f"ECG interpretation failed: {exc}",
            exc_info=True,
            extra={"request_id": get_request_id()},
        )
        if isinstance(exc, HTTPException):
            raise exc
        raise ExternalServiceError("OpenAI", str(exc))
