"""
Add is_admin column to users table and create first admin user.

Run this script once to:
1. Add is_admin column to users table (defaults to False)
2. Create an admin user account
"""

import os
import sys
from sqlalchemy import text
from dotenv import load_dotenv

# Add the backend directory to path so we can import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, engine
from services.auth import hash_password

load_dotenv()

def add_admin_column_and_user():
    """Add is_admin column and create first admin user."""
    
    db = SessionLocal()
    
    try:
        print("🔧 Adding is_admin column to users table...")
        
        # Add is_admin column to users table (defaults to False)
        add_column_query = text("""
            ALTER TABLE users 
            ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE
        """)
        
        db.execute(add_column_query)
        db.commit()
        print("✅ is_admin column added successfully")
        
        # Set up admin user credentials
        admin_email = input("Enter admin email: ").strip()
        admin_password = input("Enter admin password: ").strip()
        
        if not admin_email or not admin_password:
            print("❌ Admin email and password are required!")
            return
        
        # Check if admin email already exists
        check_query = text("SELECT id, is_admin FROM users WHERE email = :email")
        existing_user = db.execute(check_query, {"email": admin_email}).fetchone()
        
        if existing_user:
            user_id, is_currently_admin = existing_user
            if is_currently_admin:
                print(f"✅ User {admin_email} is already an admin!")
                return
            else:
                # Make existing user admin
                update_query = text("UPDATE users SET is_admin = TRUE WHERE email = :email")
                db.execute(update_query, {"email": admin_email})
                db.commit()
                print(f"✅ Made existing user {admin_email} an admin!")
                return
        
        # Create new admin user
        print("🔧 Creating admin user account...")
        
        import uuid
        user_id = str(uuid.uuid4())
        hashed_password = hash_password(admin_password)
        
        create_admin_query = text("""
            INSERT INTO users (id, email, password_hash, is_admin, created_at)
            VALUES (:id, :email, :password_hash, TRUE, NOW())
        """)
        
        db.execute(create_admin_query, {
            "id": user_id,
            "email": admin_email,
            "password_hash": hashed_password
        })
        
        db.commit()
        print(f"✅ Admin user created successfully!")
        print(f"   Email: {admin_email}")
        print(f"   ID: {user_id}")
        
        # Verify admin user was created
        verify_query = text("SELECT id, email, is_admin FROM users WHERE email = :email")
        admin_user = db.execute(verify_query, {"email": admin_email}).fetchone()
        
        if admin_user and admin_user[2]:  # is_admin is True
            print("✅ Admin user verification successful!")
        else:
            print("❌ Admin user verification failed!")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        
    finally:
        db.close()

if __name__ == "__main__":
    print("🚀 Setting up admin user...")
    add_admin_column_and_user()
    print("🎉 Setup complete!")