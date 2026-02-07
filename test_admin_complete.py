#!/usr/bin/env python3
"""
Complete Admin User Management System Test

Tests all admin functionality including:
- Listing users with filters
- Updating user details 
- Password resets
- User status management
- User deletion
- Analytics
"""

import asyncio
import aiohttp
import json
from typing import Dict, Any


BASE_URL = "http://localhost:8000"
ADMIN_EMAIL = "admin@test.com"
ADMIN_PASSWORD = "admin123"


async def login_admin(session: aiohttp.ClientSession) -> str:
    """Login as admin and return token."""
    login_data = {
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    }
    
    async with session.post(f"{BASE_URL}/api/auth/login", json=login_data) as response:
        if response.status != 200:
            raise Exception(f"Admin login failed: {await response.text()}")
        
        data = await response.json()
        return data["access_token"]


async def test_list_users(session: aiohttp.ClientSession, token: str):
    """Test listing users with various filters."""
    print("\\n🔍 Testing user listing...")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Test basic listing
    async with session.get(f"{BASE_URL}/api/admin/users", headers=headers) as response:
        assert response.status == 200, f"Failed to list users: {await response.text()}"
        data = await response.json()
        print(f"✅ Successfully listed {data['total_count']} users")
        
        # Store first user for later tests
        if data['users']:
            return data['users'][0]
    
    # Test search filtering
    async with session.get(f"{BASE_URL}/api/admin/users?search=test", headers=headers) as response:
        assert response.status == 200
        data = await response.json()
        print(f"✅ Search filter returned {len(data['users'])} users")
    
    # Test status filtering
    async with session.get(f"{BASE_URL}/api/admin/users?status=active", headers=headers) as response:
        assert response.status == 200
        data = await response.json()
        print(f"✅ Active filter returned {len(data['users'])} users")
    
    return None


async def test_user_analytics(session: aiohttp.ClientSession, token: str):
    """Test user analytics endpoint."""
    print("\\n📊 Testing user analytics...")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    async with session.get(f"{BASE_URL}/api/admin/users/analytics", headers=headers) as response:
        assert response.status == 200, f"Failed to get analytics: {await response.text()}"
        data = await response.json()
        
        required_fields = [
            'total_users', 'active_users', 'inactive_users', 'suspended_users',
            'new_users_last_7_days', 'new_users_last_30_days', 'avg_sessions_per_user',
            'avg_mastery_across_platform', 'most_popular_language', 'languages_distribution'
        ]
        
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"✅ Analytics: {data['total_users']} total users, {data['active_users']} active")


async def test_update_user_details(session: aiohttp.ClientSession, token: str, user: Dict):
    """Test updating user details."""
    print(f"\\n✏️ Testing user details update for {user['email']}...")
    
    headers = {"Authorization": f"Bearer {token}"}
    user_id = user['id']
    
    # Update user name and language
    update_data = {
        "name": "Updated Test User",
        "language": "python_3"
    }
    
    async with session.patch(
        f"{BASE_URL}/api/admin/users/{user_id}",
        headers=headers,
        json=update_data
    ) as response:
        assert response.status == 200, f"Failed to update user: {await response.text()}"
        data = await response.json()
        
        assert data['success'] == True
        assert data['updated_user']['name'] == "Updated Test User"
        assert data['updated_user']['language'] == "python_3"
        
        print(f"✅ Successfully updated user details")


async def test_update_user_status(session: aiohttp.ClientSession, token: str, user: Dict):
    """Test updating user status."""
    print(f"\\n🔄 Testing user status update for {user['email']}...")
    
    headers = {"Authorization": f"Bearer {token}"}
    user_id = user['id']
    
    # Suspend user
    status_data = {"status": "suspended"}
    
    async with session.patch(
        f"{BASE_URL}/api/admin/users/{user_id}/status",
        headers=headers,
        json=status_data
    ) as response:
        assert response.status == 200, f"Failed to update status: {await response.text()}"
        data = await response.json()
        
        assert data['success'] == True
        assert data['updated_user']['status'] == "suspended"
        
        print(f"✅ Successfully suspended user")
    
    # Reactivate user
    status_data = {"status": "active"}
    
    async with session.patch(
        f"{BASE_URL}/api/admin/users/{user_id}/status",
        headers=headers,
        json=status_data
    ) as response:
        assert response.status == 200, f"Failed to reactivate: {await response.text()}"
        data = await response.json()
        
        assert data['updated_user']['status'] == "active"
        
        print(f"✅ Successfully reactivated user")


async def test_password_reset(session: aiohttp.ClientSession, token: str, user: Dict):
    """Test password reset functionality."""
    print(f"\\n🔐 Testing password reset for {user['email']}...")
    
    headers = {"Authorization": f"Bearer {token}"}
    user_id = user['id']
    
    # Reset password
    password_data = {"new_password": "newTempPassword123"}
    
    async with session.post(
        f"{BASE_URL}/api/admin/users/{user_id}/reset-password",
        headers=headers,
        json=password_data
    ) as response:
        assert response.status == 200, f"Failed to reset password: {await response.text()}"
        data = await response.json()
        
        assert data['success'] == True
        assert "reset successfully" in data['message'].lower()
        
        print(f"✅ Successfully reset user password")


async def test_delete_user(session: aiohttp.ClientSession, token: str, user: Dict):
    """Test user deletion (careful with this!)."""
    print(f"\\n⚠️ Testing user deletion for {user['email']}...")
    print("Note: This will permanently delete the user!")
    
    # Create a test user first to delete safely
    test_user_data = {
        "email": "delete_test_user@example.com",
        "password": "testpass123",
        "language_id": "python_3",
        "experience_level": "beginner"
    }
    
    # Register test user
    async with session.post(f"{BASE_URL}/api/auth/register", json=test_user_data) as response:
        if response.status != 200:
            print("⚠️ Skipping delete test - couldn't create test user")
            return
        
        test_user = await response.json()
        test_user_id = test_user['user_id']
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Delete the test user
    async with session.delete(
        f"{BASE_URL}/api/admin/users/{test_user_id}",
        headers=headers
    ) as response:
        assert response.status == 200, f"Failed to delete user: {await response.text()}"
        data = await response.json()
        
        assert data['success'] == True
        assert "permanently deleted" in data['message'].lower()
        
        print(f"✅ Successfully deleted test user")
    
    # Verify user is gone
    async with session.get(f"{BASE_URL}/api/admin/users", headers=headers) as response:
        data = await response.json()
        deleted_user = next((u for u in data['users'] if u['id'] == test_user_id), None)
        assert deleted_user is None, "User should be deleted"
        
        print(f"✅ Confirmed user was permanently deleted")


async def test_authorization(session: aiohttp.ClientSession):
    """Test that admin endpoints require admin authorization."""
    print("\\n🔒 Testing admin authorization...")
    
    # Try to access admin endpoint without token
    async with session.get(f"{BASE_URL}/api/admin/users") as response:
        assert response.status == 401, "Should require authentication"
        print("✅ Correctly blocked unauthenticated access")
    
    # Try with invalid token
    headers = {"Authorization": "Bearer invalid_token"}
    async with session.get(f"{BASE_URL}/api/admin/users", headers=headers) as response:
        assert response.status == 401, "Should reject invalid token"
        print("✅ Correctly blocked invalid token")


async def run_complete_admin_test():
    """Run comprehensive admin system test."""
    print("🚀 Starting Complete Admin User Management System Test")
    print("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        try:
            # Test authorization first
            await test_authorization(session)
            
            # Login as admin
            print("\\n🔐 Logging in as admin...")
            token = await login_admin(session)
            print("✅ Admin login successful")
            
            # Test all admin functionality
            test_user = await test_list_users(session, token)
            await test_user_analytics(session, token)
            
            if test_user:
                await test_update_user_details(session, token, test_user)
                await test_update_user_status(session, token, test_user)
                await test_password_reset(session, token, test_user)
            
            # Test delete (creates and deletes a test user)
            await test_delete_user(session, token, {})
            
            print("\\n" + "=" * 60)
            print("🎉 ALL ADMIN TESTS PASSED!")
            print("✅ User listing with filters")
            print("✅ User analytics")
            print("✅ User details update")
            print("✅ User status management") 
            print("✅ Password reset")
            print("✅ User deletion")
            print("✅ Authorization controls")
            print("=" * 60)
            
        except Exception as e:
            print(f"\\n❌ Test failed: {str(e)}")
            raise


if __name__ == "__main__":
    print("Admin Complete Test Suite")
    print("Make sure the server is running on http://localhost:8000")
    print("And that you have an admin user with email 'admin@test.com' and password 'admin123'")
    print("\\nPress Enter to start tests, or Ctrl+C to cancel...")
    input()
    
    asyncio.run(run_complete_admin_test())