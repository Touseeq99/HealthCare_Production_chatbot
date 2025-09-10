from datetime import datetime, timedelta
from typing import Optional, Tuple
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session
import os
import time
from dotenv import load_dotenv
import memcache

from database.database import get_db
from database.models import User
from utils.hash_password import verify_password, get_password_hash
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.logger import logger
from config import settings

# Initialize memcached
mc = memcache.Client(['127.0.0.1:11211'], debug=0)

# Load environment variables
load_dotenv()

# Import settings
from config import settings

# JWT Configuration from settings
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Pydantic models
class LoginResponse(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None
    user: Optional[dict] = None

class LoginRequest(BaseModel):
    email: str
    password: str
    role: str

class TokenData(BaseModel):
    email: Optional[str] = None

class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    surname: str
    role: str
    phone: Optional[str] = None
    specialization: Optional[str] = None
    doctor_register_number: Optional[str] = None

class UserResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    user: Optional[dict] = None
    token: Optional[str] = None

class UserInDB(User):
    __tablename__ = "users"
    __allow_unmapped__ = True
    hashed_password: str

def get_failed_login_key(email: str) -> str:
    """Generate a key for tracking failed login attempts"""
    return f"login_failures:{email}"

def is_account_locked(email: str) -> Tuple[bool, int]:
    """Check if account is locked and return remaining lock time"""
    lock_key = f"account_lock:{email}"
    lock_until = mc.get(lock_key)
    if lock_until and lock_until > time.time():
        return True, int(lock_until - time.time())
    return False, 0

def record_failed_login(email: str):
    """Record a failed login attempt and lock account if threshold is reached"""
    key = get_failed_login_key(email)
    failures = mc.get(key) or 0
    failures += 1
    
    if failures >= settings.MAX_LOGIN_ATTEMPTS:
        # Lock the account
        lock_until = int(time.time()) + settings.LOCKOUT_TIME
        mc.set(f"account_lock:{email}", lock_until, time=settings.LOCKOUT_TIME)
        logger.warning(f"Account locked for {email} after {failures} failed attempts")
        # Reset the failure counter
        mc.delete(key)
    else:
        # Store the failure count with expiration
        mc.set(key, failures, time=settings.LOCKOUT_TIME)
    
    return failures

def clear_login_attempts(email: str):
    """Clear failed login attempts for a successful login"""
    mc.delete(get_failed_login_key(email))
    mc.delete(f"account_lock:{email}")

# Authentication functions
def authenticate_user(db: Session, email: str, password: str, role: str):
    # Check if account is locked
    locked, remaining = is_account_locked(email)
    if locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "message": "Account locked due to too many failed login attempts",
                "retry_after_seconds": remaining
            }
        )

    user = db.query(User).filter(User.email == email, User.role == role).first()
    if not user:
        # Record failed attempt even if user doesn't exist (prevents user enumeration)
        record_failed_login(email)
        return False
        
    if not verify_password(password, user.hashed_password):
        remaining_attempts = settings.MAX_LOGIN_ATTEMPTS - (record_failed_login(email) - 1)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Incorrect email or password",
                "remaining_attempts": remaining_attempts,
                "account_locked": remaining_attempts <= 0
            }
        )
    
    # Clear failed attempts on successful login
    clear_login_attempts(email)
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    # Convert SecretStr to string for JWT encoding
    secret_key_str = SECRET_KEY.get_secret_value() if hasattr(SECRET_KEY, 'get_secret_value') else str(SECRET_KEY)
    encoded_jwt = jwt.encode(to_encode, secret_key_str, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.email == token_data.email).first()
    if user is None:
        raise credentials_exception
    return user

# API Endpoints

router = APIRouter()

@router.post("/signup", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        return {
            "success": False,
            "message": "Email already registered"
        }
    
    try:
        # Create new user
        hashed_password = get_password_hash(user.password)
        db_user = User(
            email=user.email,
            hashed_password=hashed_password,
            name=user.name,
            surname=user.surname,
            role=user.role,
            phone=user.phone or None,
            specialization=user.specialization or None,
            doctor_register_number=user.doctor_register_number or None
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        
        # Generate JWT token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": db_user.email, "role": db_user.role}, 
            expires_delta=access_token_expires
        )
        
        # Prepare response
        return {
            "success": True,
            "message": "Registration successful",
            "user": {
                "id": str(db_user.id),
                "email": db_user.email,
                "name": db_user.name,
                "surname": db_user.surname,
                "role": db_user.role,
                "phone": db_user.phone,
                "specialization": db_user.specialization,
                "doctor_register_number": db_user.doctor_register_number
            },
            "token": access_token
        }
        
    except Exception as e:
        db.rollback()
        return {
            "success": False,
            "message": f"Registration failed: {str(e)}"
        }

@router.post("/login", response_model=LoginResponse)
async def login_for_access_token(
    request: Request,
    login_data: LoginRequest, 
    db: Session = Depends(get_db)
):
    try:
        user = authenticate_user(db, login_data.email, login_data.password, login_data.role)
        if not user:
            # This should not be reached due to the exception in authenticate_user
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Authentication failed"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.email, "role": user.role}, 
            expires_delta=access_token_expires
        )
        
        # Log successful login
        logger.info(
            "User logged in successfully",
            extra={
                "email": user.email,
                "role": user.role,
                "client_ip": request.client.host if request.client else None,
            },
        )
        
        return {
            "success": True,
            "message": "Login successful",
            "token": access_token,
            "user": {
                "email": user.email,
                "name": user.name,
                "role": user.role
            }
        }
        
    except HTTPException as http_exc:
        # Re-raise HTTP exceptions
        raise http_exc
    except Exception as e:
        logger.error(
            "Login error",
            extra={
                "error": str(e),
                "email": login_data.email,
                "client_ip": request.client.host if request.client else None,
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "An error occurred during login"}
        )

@router.get("/verify-token")
async def verify_token(current_user: User = Depends(get_current_user)):
    return {"status": "valid", "user": current_user.email}