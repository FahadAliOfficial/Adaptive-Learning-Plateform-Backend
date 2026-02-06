"""
Quick test to verify authentication implementation.
Run: python test_auth_implementation.py
"""

def test_imports():
    """Test all imports work."""
    print("Testing imports...")
    try:
        from services.auth import hash_password, verify_password, create_access_token, get_current_user
        from services.schemas import LoginRequest, LoginResponse, UserProfile
        from routers.auth_router import router
        print("✅ All imports successful")
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False


def test_password_hashing():
    """Test password hashing works."""
    print("\nTesting password hashing...")
    try:
        from services.auth import hash_password, verify_password
        
        password = "testPassword123"
        hashed = hash_password(password)
        
        assert hashed != password, "Password should be hashed"
        assert verify_password(password, hashed), "Password verification should work"
        assert not verify_password("wrongPassword", hashed), "Wrong password should fail"
        
        print("✅ Password hashing works")
        return True
    except Exception as e:
        print(f"❌ Password hashing error: {e}")
        return False


def test_jwt_tokens():
    """Test JWT token creation."""
    print("\nTesting JWT token generation...")
    try:
        from services.auth import create_access_token, create_refresh_token, verify_token
        
        data = {"sub": "user-123", "email": "test@example.com"}
        access_token = create_access_token(data)
        refresh_token = create_refresh_token(data)
        
        assert access_token, "Access token should be created"
        assert refresh_token, "Refresh token should be created"
        assert access_token != refresh_token, "Tokens should be different"
        
        # Verify token
        payload = verify_token(access_token)
        assert payload["sub"] == "user-123", "Token payload should match"
        assert payload["type"] == "access", "Token type should be access"
        
        print("✅ JWT token generation works")
        return True
    except Exception as e:
        print(f"❌ JWT token error: {e}")
        return False


def test_schemas():
    """Test Pydantic schemas."""
    print("\nTesting Pydantic schemas...")
    try:
        from services.schemas import LoginRequest, LoginResponse, UserProfile
        
        # Test LoginRequest
        login_req = LoginRequest(email="test@example.com", password="password123")
        assert login_req.email == "test@example.com"
        
        # Test LoginResponse
        login_res = LoginResponse(
            access_token="token123",
            refresh_token="refresh123",
            user_id="user-123",
            email="test@example.com"
        )
        assert login_res.token_type == "bearer"
        
        print("✅ Schemas work")
        return True
    except Exception as e:
        print(f"❌ Schema error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("AUTHENTICATION IMPLEMENTATION TEST")
    print("=" * 50)
    
    results = [
        test_imports(),
        test_password_hashing(),
        test_jwt_tokens(),
        test_schemas()
    ]
    
    print("\n" + "=" * 50)
    if all(results):
        print("✅ ALL TESTS PASSED - Authentication ready!")
    else:
        print("❌ SOME TESTS FAILED - Check errors above")
    print("=" * 50)
