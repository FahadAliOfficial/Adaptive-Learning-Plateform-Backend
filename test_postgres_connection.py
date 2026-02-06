"""
Test PostgreSQL connection and authentication flow.
"""
import sys
import os
from database import SessionLocal, engine
from services.user_service import UserService
from services.auth import verify_password, hash_password
from sqlalchemy import text


def test_connection():
    """Test basic PostgreSQL connection."""
    print("Testing PostgreSQL connection...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"✅ Connected to PostgreSQL: {version.split(',')[0]}")
            return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


def test_user_registration():
    """Test user registration with PostgreSQL."""
    print("\nTesting user registration...")
    db = SessionLocal()
    try:
        from services.schemas import UserRegistrationPayload
        user_service = UserService(db)
        
        # Clean up test user if exists
        result = db.execute(text("DELETE FROM users WHERE email='test@postgres.com'"))
        result = db.execute(text("DELETE FROM student_state WHERE user_id NOT IN (SELECT id FROM users)"))
        db.commit()
        
        # Register test user
        user_data = UserRegistrationPayload(
            email="test@postgres.com",
            password="TestPassword123!",
            language_id="python_3",
            experience_level="beginner"
        )
        
        result = user_service.register_user(user_data)
        print(f"✅ User registered: {result.user_id}")
        print(f"   Starting topic: {result.starting_topic}")
        print(f"   Experience level: {result.experience_level}")
        
        # Verify user was created in database
        user_check = db.execute(text(f"SELECT * FROM users WHERE id='{result.user_id}'"))
        user = user_check.fetchone()
        if user:
            print("✅ User record created in database")
            # Verify password was hashed (password_hash column is at index 2)
            if len(user[2]) > 50:  # Hashed passwords are long
                print("✅ Password is properly hashed")
            else:
                print("❌ Password might not be hashed!")
                return False
        else:
            print("❌ User not found in database!")
            return False
            
        return result
        
    except Exception as e:
        print(f"❌ Registration failed: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def test_user_login(user_id):
    """Test user login with JWT tokens."""
    print("\nTesting user login...")
    db = SessionLocal()
    try:
        from services.schemas import LoginRequest
        user_service = UserService(db)
        
        # Login with email and password
        login_data = LoginRequest(
            email="test@postgres.com",
            password="TestPassword123!"
        )
        
        result = user_service.login_user(login_data)
        
        if result and result.access_token:
            print(f"✅ Login successful")
            print(f"   User ID: {result.user_id}")
            print(f"   Email: {result.email}")
            print(f"   Access Token: {result.access_token[:50]}...")
            print(f"   Refresh Token: {result.refresh_token[:50]}...")
            print(f"   Token Type: {result.token_type}")
            return True
        else:
            print("❌ Login failed - no tokens returned")
            return False
            
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False
    finally:
        db.close()


def test_timestamp_functions():
    """Test that NOW() function works in PostgreSQL."""
    print("\nTesting PostgreSQL timestamp functions...")
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT NOW(), CURRENT_TIMESTAMP"))
        now, current = result.fetchone()
        print(f"✅ NOW() works: {now}")
        print(f"✅ CURRENT_TIMESTAMP works: {current}")
        return True
    except Exception as e:
        print(f"❌ Timestamp test failed: {e}")
        return False
    finally:
        db.close()


def main():
    """Run all tests."""
    print("=" * 60)
    print("PostgreSQL Authentication Test Suite")
    print("=" * 60)
    
    tests_passed = 0
    tests_total = 4
    
    # Test 1: Connection
    if test_connection():
        tests_passed += 1
    
    # Test 2: Timestamp functions
    if test_timestamp_functions():
        tests_passed += 1
    
    # Test 3: User registration
    user = test_user_registration()
    if user:
        tests_passed += 1
    
    # Test 4: User login
    if user:
        if test_user_login(user.user_id):
            tests_passed += 1
    
    print("\n" + "=" * 60)
    print(f"Tests Results: {tests_passed}/{tests_total} passed")
    print("=" * 60)
    
    if tests_passed == tests_total:
        print("🎉 All tests passed! PostgreSQL is ready.")
        return 0
    else:
        print("⚠️ Some tests failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
