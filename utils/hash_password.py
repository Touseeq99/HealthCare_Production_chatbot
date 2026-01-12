from passlib.context import CryptContext
import bcrypt

# Initialize bcrypt backend explicitly to avoid Python 3.13 issues
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Truncate to 72 bytes - bcrypt limitation
    try:
        return pwd_context.verify(plain_password[:72], hashed_password)
    except ValueError:
        # Fallback for Python 3.13 compatibility issues
        return bcrypt.checkpw(plain_password[:72].encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password: str) -> str:
    # Truncate to 72 bytes - bcrypt limitation  
    try:
        return pwd_context.hash(password[:72])
    except ValueError:
        # Fallback for Python 3.13 compatibility issues
        return bcrypt.hashpw(password[:72].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')