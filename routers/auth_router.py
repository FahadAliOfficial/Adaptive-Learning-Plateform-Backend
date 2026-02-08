"""
Authentication Router - Handles user authentication endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Optional

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
    response: Response,
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
    5. Generate JWT tokens
    6. Set refresh_token as httpOnly cookie (7 days)
    7. Return access_token in response body (for memory storage)
    
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
        result, refresh_token = user_service.register_user(payload)
        
        # Set refresh_token as httpOnly cookie (can't be accessed by JavaScript)
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,  # Prevents XSS attacks
            secure=False,   # Set to True in production (HTTPS only)
            samesite="lax", # CSRF protection
            max_age=7*24*60*60,  # 7 days in seconds
            path="/api/auth"  # Cookie only sent to auth endpoints
        )
        
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
    response: Response,
    payload: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate user and receive JWT tokens.
    
    **Returns:**
    - `access_token`: Use in Authorization header for API requests (stored in memory, 30 min expiry)
    - Refresh token set as httpOnly cookie (7 days, auto-sent with future requests)
    
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
        "token_type": "bearer",
        "user_id": "uuid-here",
        "email": "student@example.com",
        "last_active_language": "python_3"
    }
    ```
    """
    try:
        user_service = UserService(db)
        result = user_service.login_user(payload)
        
        # Set refresh_token as httpOnly cookie
        response.set_cookie(
            key="refresh_token",
            value=result.refresh_token,
            httponly=True,
            secure=False,  # Set to True in production (HTTPS only)
            samesite="lax",
            max_age=7*24*60*60,  # 7 days
            path="/api/auth"  # Cookie only sent to auth endpoints
        )
        
        # Don't return refresh_token in response body (security best practice)
        result.refresh_token = None
        
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
    response: Response,
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
        
        # Set refresh_token as httpOnly cookie
        response.set_cookie(
            key="refresh_token",
            value=result.refresh_token,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=7*24*60*60,
            path="/api/auth"
        )
        
        # Don't return refresh_token in response body
        result.refresh_token = None
        
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(
    db: Session = Depends(get_db),
    refresh_token: Optional[str] = Cookie(None)
):
    """
    Get a new access token using refresh token from httpOnly cookie.
    
    **Use this when:**
    - Access token expires (after 30 minutes by default)
    - You receive 401 Unauthorized errors
    - On page reload to restore session
    
    **Note:** Refresh token is automatically sent from httpOnly cookie.
    No request body needed!
    """
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found. Please login again."
        )
    
    try:
        # Verify refresh token
        token_data = verify_token(refresh_token)
        
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
async def logout(
    response: Response,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Logout current user by clearing the refresh_token cookie.
    
    **Client should also:**
    1. Clear access_token from memory
    2. Redirect to login page
    
    **Note:** Since access tokens are in memory (not cookies), they're automatically
    cleared when user navigates away. This endpoint clears the long-lived refresh token.
    """
    # Clear the refresh_token httpOnly cookie
    response.delete_cookie(
        key="refresh_token",
        path="/api/auth"
    )
    
    return {
        "success": True,
        "message": "Logged out successfully. Refresh token cleared."
    }


@router.put("/profile")
async def update_profile(
    payload: dict,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Update user profile (language and experience level after onboarding).
    
    **Payload:**
    - language_id: Selected programming language
    - experience_level: beginner, intermediate, or advanced
    
    **Used by:** Onboarding flow to save user preferences
    """
    from sqlalchemy import text
    
    language_id = payload.get("language_id")
    experience_level = payload.get("experience_level")
    
    if not language_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="language_id is required"
        )
    
    # Update user's language preference and set as primary
    update_query = text("""
        UPDATE users 
        SET last_active_language = :language_id,
            primary_language = COALESCE(primary_language, :language_id),
            languages_learning = CASE 
                WHEN languages_learning IS NULL OR languages_learning = '[]'::jsonb
                THEN jsonb_build_array(:language_id)
                WHEN NOT languages_learning ? :language_id
                THEN languages_learning || jsonb_build_array(:language_id)
                ELSE languages_learning
            END
        WHERE id = :user_id
    """)
    
    db.execute(update_query, {
        "language_id": language_id,
        "user_id": current_user["id"]
    })
    
    # Initialize student state if experience level is provided
    if experience_level:
        from services.config import get_config
        config = get_config()
        exp_config = config.get_experience_config(experience_level)
        initial_mastery = exp_config.get('initial_mastery_estimate', 0.0)
        assumed_mastered = exp_config.get('assumed_mastered', [])
        
        # Pre-populate assumed knowledge for intermediate/advanced users
        for mapping_id in assumed_mastered:
            insert_state = text("""
                INSERT INTO student_state 
                    (user_id, mapping_id, language_id, mastery_score, fluency_score, confidence_score, last_practiced_at, last_updated)
                VALUES 
                    (:user_id, :mapping_id, :language_id, :mastery, :fluency, :confidence, NOW(), NOW())
                ON CONFLICT (user_id, mapping_id, language_id) 
                DO NOTHING
            """)
            
            db.execute(insert_state, {
                "user_id": current_user["id"],
                "mapping_id": mapping_id,
                "language_id": language_id,
                "mastery": initial_mastery,
                "fluency": 1.2,
                "confidence": 0.5
            })
    
    db.commit()
    
    return {
        "success": True,
        "message": "Profile updated successfully",
        "language_id": language_id,
        "experience_level": experience_level
    }
