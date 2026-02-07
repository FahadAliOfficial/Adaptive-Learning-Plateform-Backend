"""
Admin Router - Handles administrative endpoints for user management.

Provides endpoints for admin users to manage platform users and view analytics.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from services.user_service import UserService
from services.schemas import (
    AdminUserListResponse,
    AdminUserStatusUpdateRequest,
    AdminUserStatusUpdateResponse,
    AdminUserUpdateRequest,
    AdminUserUpdateResponse,
    AdminPasswordResetRequest,
    AdminPasswordResetResponse,
    AdminUserAnalytics
)
from services.auth import get_current_admin_user

router = APIRouter(prefix="/api/admin", tags=["Admin"])


@router.get("/users", response_model=AdminUserListResponse)
async def get_all_users(
    search: Optional[str] = Query(None, description="Search by email or name"),
    status: Optional[str] = Query("all", description="Filter by status: all, active, inactive, suspended"),
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    List all users with filtering and search capabilities.
    
    **Use Case:** Admin dashboard user management page
    
    **Example:**
    GET /api/admin/users?search=john&status=active
    
    **Returns:**
    - List of users with calculated status, session count, and mastery
    - User statistics (total, active, inactive, suspended counts)
    
    **Requires:** Admin authentication
    """
    try:
        user_service = UserService(db)
        result = user_service.get_all_users_admin(
            search_query=search,
            status_filter=status
        )
        
        return AdminUserListResponse(
            users=result["users"],
            total_count=result["total_count"],
            active_count=result["active_count"],
            inactive_count=result["inactive_count"],
            suspended_count=result["suspended_count"]
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve users: {str(e)}")


@router.patch("/users/{user_id}/status", response_model=AdminUserStatusUpdateResponse)
async def update_user_status(
    user_id: str,
    request: AdminUserStatusUpdateRequest,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Update a user's status (active, inactive, suspended).
    
    **Use Case:** Admin suspending or activating user accounts
    
    **Example:**
    PATCH /api/admin/users/123e4567-e89b-12d3-a456-426614174000/status
    Body: {"status": "suspended"}
    
    **Returns:**
    - Success confirmation
    - Updated user data
    
    **Requires:** Admin authentication
    """
    try:
        user_service = UserService(db)
        updated_user = user_service.update_user_status_admin(user_id, request.status)
        
        status_messages = {
            "active": "User has been activated successfully",
            "inactive": "User has been marked as inactive",
            "suspended": "User has been suspended successfully"
        }
        
        return AdminUserStatusUpdateResponse(
            message=status_messages.get(request.status, f"User status updated to {request.status}"),
            updated_user=updated_user
        )
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update user status: {str(e)}")


@router.get("/users/analytics", response_model=AdminUserAnalytics)
async def get_user_analytics(
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive user analytics for admin dashboard.
    
    **Use Case:** Admin dashboard statistics cards and charts
    
    **Example:**
    GET /api/admin/users/analytics
    
    **Returns:**
    - User counts by status
    - New user growth metrics
    - Platform-wide engagement statistics
    - Language usage distribution
    
    **Requires:** Admin authentication
    """
    try:
        user_service = UserService(db)
        analytics_data = user_service.get_user_analytics_admin()
        
        return AdminUserAnalytics(**analytics_data)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve analytics: {str(e)}")


@router.patch("/users/{user_id}", response_model=AdminUserUpdateResponse)
async def update_user_details(
    user_id: str,
    request: AdminUserUpdateRequest,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Update user details (name, language, etc.).
    
    **Use Case:** Admin editing user profile information
    
    **Example:**
    PATCH /api/admin/users/123e4567-e89b-12d3-a456-426614174000
    Body: {"name": "New Name", "language": "python_3"}
    
    **Returns:**
    - Success confirmation
    - Updated user data
    
    **Requires:** Admin authentication
    """
    try:
        user_service = UserService(db)
        updated_user = user_service.update_user_details_admin(user_id, request)
        
        return AdminUserUpdateResponse(
            message="User details updated successfully",
            updated_user=updated_user
        )
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update user details: {str(e)}")


@router.post("/users/{user_id}/reset-password", response_model=AdminPasswordResetResponse)
async def reset_user_password(
    user_id: str,
    request: AdminPasswordResetRequest,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Reset a user's password (admin only).
    
    **Use Case:** Admin helping users who forgot passwords or need password resets
    
    **Example:**
    POST /api/admin/users/123e4567-e89b-12d3-a456-426614174000/reset-password
    Body: {"new_password": "newSecurePassword123"}
    
    **Returns:**
    - Success confirmation
    
    **Requires:** Admin authentication
    """
    try:
        user_service = UserService(db)
        user_service.reset_user_password_admin(user_id, request.new_password)
        
        return AdminPasswordResetResponse(
            message="User password has been reset successfully"
        )
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset user password: {str(e)}")


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Delete a user account permanently.
    
    **Use Case:** Admin removing spam accounts or handling data deletion requests
    
    **Example:**
    DELETE /api/admin/users/123e4567-e89b-12d3-a456-426614174000
    
    **Returns:**
    - Success confirmation
    
    **Requires:** Admin authentication
    
    **WARNING:** This action is irreversible and will delete all user data
    """
    try:
        user_service = UserService(db)
        user_service.delete_user_admin(user_id)
        
        return {"success": True, "message": "User account has been permanently deleted"}
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete user: {str(e)}")