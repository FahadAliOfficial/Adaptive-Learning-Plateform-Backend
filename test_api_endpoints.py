"""
Test all authentication API endpoints with PostgreSQL.
Run this while the server is running (uvicorn main:app --reload)
"""
import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_register():
    """Test user registration endpoint."""
    print("\n" + "="*60)
    print("TEST 1: User Registration")
    print("="*60)
    
    payload = {
        "email": f"testuser_{int(time.time())}@example.com",
        "password": "SecurePassword123!",
        "language_id": "python_3",
        "experience_level": "intermediate"
    }
    
    response = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 201:
        print("✅ Registration successful")
        return payload["email"], payload["password"]
    else:
        print("❌ Registration failed")
        return None, None


def test_login(email, password):
    """Test user login endpoint."""
    print("\n" + "="*60)
    print("TEST 2: User Login")
    print("="*60)
    
    payload = {
        "email": email,
        "password": password
    }
    
    response = requests.post(f"{BASE_URL}/api/auth/login", json=payload)
    
    print(f"Status Code: {response.status_code}")
    data = response.json()
    
    if response.status_code == 200:
        print("✅ Login successful")
        print(f"Access Token: {data['access_token'][:50]}...")
        print(f"Refresh Token: {data['refresh_token'][:50]}...")
        print(f"User ID: {data['user_id']}")
        print(f"Email: {data['email']}")
        return data["access_token"], data["refresh_token"]
    else:
        print("❌ Login failed")
        print(f"Response: {json.dumps(data, indent=2)}")
        return None, None


def test_get_profile(access_token):
    """Test get user profile endpoint (protected)."""
    print("\n" + "="*60)
    print("TEST 3: Get User Profile (Protected)")
    print("="*60)
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    response = requests.get(f"{BASE_URL}/api/auth/me", headers=headers)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        print("✅ Profile retrieved successfully")
        return True
    else:
        print("❌ Profile retrieval failed")
        return False


def test_refresh_token(refresh_token):
    """Test token refresh endpoint."""
    print("\n" + "="*60)
    print("TEST 4: Refresh Access Token")
    print("="*60)
    
    payload = {
        "refresh_token": refresh_token
    }
    
    response = requests.post(f"{BASE_URL}/api/auth/refresh", json=payload)
    
    print(f"Status Code: {response.status_code}")
    data = response.json()
    
    if response.status_code == 200:
        print("✅ Token refresh successful")
        print(f"New Access Token: {data['access_token'][:50]}...")
        return True
    else:
        print("❌ Token refresh failed")
        print(f"Response: {json.dumps(data, indent=2)}")
        return False


def test_change_password(access_token, old_password):
    """Test password change endpoint (protected)."""
    print("\n" + "="*60)
    print("TEST 5: Change Password (Protected)")
    print("="*60)
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    payload = {
        "current_password": old_password,
        "new_password": "NewSecurePassword456!"
    }
    
    response = requests.post(f"{BASE_URL}/api/auth/change-password", json=payload, headers=headers)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        print("✅ Password changed successfully")
        return True
    else:
        print("❌ Password change failed")
        return False


def test_protected_without_token():
    """Test that protected endpoints require authentication."""
    print("\n" + "="*60)
    print("TEST 6: Protected Endpoint Without Token")
    print("="*60)
    
    response = requests.get(f"{BASE_URL}/api/auth/me")
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 401:
        print("✅ Correctly rejected unauthorized request")
        return True
    else:
        print("❌ Should have returned 401 Unauthorized")
        return False


def main():
    """Run all authentication tests."""
    print("\n" + "="*70)
    print("  PostgreSQL Authentication API Test Suite")
    print("  Make sure the server is running: uvicorn main:app --reload")
    print("="*70)
    
    # Check if server is running
    try:
        requests.get(BASE_URL)
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Cannot connect to server at", BASE_URL)
        print("Please start the server with: uvicorn main:app --reload")
        return
    
    results = {}
    
    # Test 1: Registration
    email, password = test_register()
    results["registration"] = email is not None
    
    if not email:
        print("\n⚠️ Cannot proceed with other tests without successful registration")
        return
    
    # Test 2: Login
    access_token, refresh_token = test_login(email, password)
    results["login"] = access_token is not None
    
    if not access_token:
        print("\n⚠️ Cannot proceed with protected endpoint tests without access token")
        return
    
    # Test 3: Get Profile (Protected)
    results["get_profile"] = test_get_profile(access_token)
    
    # Test 4: Refresh Token
    results["refresh_token"] = test_refresh_token(refresh_token)
    
    # Test 5: Change Password
    results["change_password"] = test_change_password(access_token, password)
    
    # Test 6: Protected Endpoint Without Token
    results["protected_auth"] = test_protected_without_token()
    
    # Summary
    print("\n" + "="*70)
    print("  TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name.ljust(25)}: {status}")
    
    total = len(results)
    passed = sum(results.values())
    
    print("\n" + "-"*70)
    print(f"Total: {passed}/{total} tests passed")
    print("="*70)
    
    if passed == total:
        print("\n🎉 All authentication tests passed!")
        print("✅ PostgreSQL integration is working perfectly")
        print("✅ JWT authentication is functioning correctly")
        print("✅ Phase 1 is complete and ready to commit")
    else:
        print(f"\n⚠️ {total - passed} test(s) failed. Please review the errors above.")


if __name__ == "__main__":
    main()
