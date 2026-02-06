"""
Authentication Router - Handles user authentication endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from database import get_db
from services.user_service import UserService
from services.schemas import (
    UserRegistrationPayload,
    UserRegistrationResponse,
    LoginRequest,
    LoginResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserProfile,
    PasswordChangeRequest,
    PasswordChangeResponse
)
from services.auth import (
    get_current_user,
    get_current_active_user,
    verify_token,
    create_access_token
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=UserRegistrationResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserRegistrationPayload,
    db: Session = Depends(get_db)
):
    """
    Register a new user account.
    
    **Workflow:**
    1. Validate email uniqueness
    2. Hash password with bcrypt
    3. Create user record
    4. Initialize learning state based on experience level
    5. Return starting topic
    
    **Example:**
    ```json
    {
        "email": "student@example.com",
        "password": "securePassword123",
        "language_id": "python_3",
        "experience_level": "beginner"
    }
    ```
    """
    try:
        user_service = UserService(db)
        result = user_service.register_user(payload)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate user and receive JWT tokens.
    
    **Returns:**
    - `access_token`: Use in Authorization header for API requests
    - `refresh_token`: Use to get new access tokens when they expire
    
    **Example:**
    ```json
    {
        "email": "student@example.com",
        "password": "securePassword123"
    }
    ```
    
    **Response:**
    ```json
    {
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
        "token_type": "bearer",
        "user_id": "uuid-here",
        "email": "student@example.com"
    }
    ```
    """
    try:
        user_service = UserService(db)
        result = user_service.login_user(payload)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )


@router.post("/login/form", response_model=LoginResponse)
async def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    OAuth2 compatible login endpoint (for Swagger UI).
    
    Uses form data instead of JSON.
    Automatically used by Swagger's "Authorize" button.
    """
    try:
        user_service = UserService(db)
        login_request = LoginRequest(email=form_data.username, password=form_data.password)
        result = user_service.login_user(login_request)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(
    payload: TokenRefreshRequest,
    db: Session = Depends(get_db)
):
    """
    Get a new access token using refresh token.
    
    **Use this when:**
    - Access token expires (after 30 minutes by default)
    - You receive 401 Unauthorized errors
    
    **Example:**
    ```json
    {
        "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
    }
    ```
    """
    try:
        # Verify refresh token
        token_data = verify_token(payload.refresh_token)
        
        # Check token type
        if token_data.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Use refresh token for this endpoint."
            )
        
        # Extract user_id
        user_id = token_data.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload"
            )
        
        # Get user email from database
        user_service = UserService(db)
        user_profile = user_service.get_user_profile(user_id)
        
        # Generate new access token
        new_access_token = create_access_token({"sub": user_id, "email": user_profile.email})
        
        return TokenRefreshResponse(
            access_token=new_access_token,
            token_type="bearer"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token refresh failed: {str(e)}"
        )


@router.get("/me", response_model=UserProfile)
async def get_current_user_profile(
    current_user: dict = Depends(get_current_active_user)
):
    """
    Get current authenticated user's profile.
    
    **Requires:** Valid access token in Authorization header
    
    **Example:**
    ```
    Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
    ```
    
    **Returns:**
    ```json
    {
        "id": "uuid-here",
        "email": "student@example.com",
        "last_active_language": "python_3",
        "total_exams_taken": 42,
        "created_at": "2026-02-06T10:30:00"
    }
    ```
    """
    return UserProfile(
        id=current_user["id"],
        email=current_user["email"],
        last_active_language=current_user.get("last_active_language"),
        total_exams_taken=current_user.get("total_exams_taken", 0),
        created_at=current_user["created_at"].isoformat() if hasattr(current_user["created_at"], 'isoformat') else str(current_user["created_at"])
    )


@router.post("/change-password", response_model=PasswordChangeResponse)
async def change_password(
    payload: PasswordChangeRequest,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Change current user's password.
    
    **Requires:** Valid access token
    
    **Example:**
    ```json
    {
        "current_password": "oldPassword123",
        "new_password": "newSecurePassword456"
    }
    ```
    """
    try:
        user_service = UserService(db)
        user_service.change_password(
            user_id=current_user["id"],
            current_password=payload.current_password,
            new_password=payload.new_password
        )
        
        return PasswordChangeResponse(
            success=True,
            message="Password changed successfully"
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Password change failed: {str(e)}"
        )


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_active_user)):
    """
    Logout current user (client-side token deletion).
    
    **Note:** JWT tokens are stateless, so logout is handled client-side
    by deleting the tokens. For true server-side logout, implement a
    token blacklist (future enhancement).
    
    **Client should:**
    1. Delete access_token from storage
    2. Delete refresh_token from storage
    3. Redirect to login page
    """
    return {
        "success": True,
        "message": "Logged out successfully. Please delete tokens from client storage."
    }
