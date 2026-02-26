"""
Authentication utilities - JWT token management and password hashing.
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import text
import os

from database import get_db

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme for token extraction
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# JWT Configuration from environment
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


# ==================== Password Hashing ====================

def hash_password(password: str) -> str:
    """
    Hash a plaintext password using bcrypt.
    
    Args:
        password: Plaintext password
    
    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a hashed password.
    
    Args:
        plain_password: Plaintext password from user
        hashed_password: Stored hashed password
    
    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


# ==================== JWT Token Management ====================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Payload to encode (should include user_id, email)
        expires_delta: Optional custom expiration time
    
    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """
    Create a JWT refresh token (longer expiration).
    
    Args:
        data: Payload to encode (should include user_id)
    
    Returns:
        Encoded JWT refresh token string
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh"
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict:
    """
    Verify and decode a JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        Decoded token payload
    
    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ==================== User Authentication Dependencies ====================

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    refresh_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
) -> dict:
    """
    Dependency to get current authenticated user from JWT token.
    
    Args:
        token: JWT token from Authorization header
        db: Database session
    
    Returns:
        User data dictionary
    
    Raises:
        HTTPException: If token invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    user_id: Optional[str] = None

    # First try Authorization bearer access token
    if token:
        try:
            payload = verify_token(token)
            token_type: str = payload.get("type")
            if token_type == "access":
                user_id = payload.get("sub")
        except HTTPException:
            user_id = None

    # Fallback: use refresh token cookie to restore session seamlessly
    if user_id is None and refresh_token:
        try:
            payload = verify_token(refresh_token)
            token_type: str = payload.get("type")
            if token_type == "refresh":
                user_id = payload.get("sub")
        except HTTPException:
            user_id = None

    if user_id is None:
        raise credentials_exception
    
    # Fetch user from database
    query = text("""
        SELECT id, email, last_active_language, total_exams_taken, created_at
        FROM users
        WHERE id = :user_id
    """)
    
    user = db.execute(query, {"user_id": user_id}).fetchone()
    
    if user is None:
        raise credentials_exception
    
    return {
        "id": user[0],
        "email": user[1],
        "last_active_language": user[2],
        "total_exams_taken": user[3],
        "created_at": user[4]
    }


async def get_current_active_user(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Dependency to get current active user (can add status check here).
    
    Args:
        current_user: User from get_current_user dependency
    
    Returns:
        User data if active
    """
    # Future: Add user status/banned check here
    # if current_user.get("is_banned"):
    #     raise HTTPException(status_code=400, detail="User account is disabled")
    
    return current_user


# ==================== Optional: Admin Check ====================

async def get_current_admin_user(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    Dependency to verify current user is an admin.
    
    Uses is_admin column from users table for authentication.
    """
    # Check is_admin status from database
    query = text("SELECT is_admin FROM users WHERE id = :user_id")
    result = db.execute(query, {"user_id": current_user["id"]}).fetchone()
    
    if not result or not result[0]:  # is_admin is False or NULL
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions. Admin access required."
        )
    
    return current_user
