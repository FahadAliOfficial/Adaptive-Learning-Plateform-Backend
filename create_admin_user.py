"""
Add Admin User Script

This script creates an admin user in the database for testing admin functionality.
The admin authentication system uses email-based validation via environment variable.
"""
import uuid
from database import SessionLocal, engine
from services.auth import hash_password  
from sqlalchemy import text
import os
from dotenv import load_dotenv

load_dotenv()

def create_admin_user():
    """Create an admin user in the database."""
    
    # Admin user details
    admin_email = "admin@fyp.com"
    admin_password = "Admin123!"  # Change this to a secure password
    
    print(f"Creating admin user: {admin_email}")
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Check if user already exists
        check_query = text("SELECT id FROM users WHERE email = :email")
        existing = db.execute(check_query, {"email": admin_email}).fetchone()
        
        if existing:
            print(f"❌ User {admin_email} already exists!")
            return False
        
        # Create admin user
        user_id = str(uuid.uuid4())
        password_hash = hash_password(admin_password)
        
        insert_query = text("""
            INSERT INTO users (id, email, password_hash, last_active_language, total_exams_taken, created_at)
            VALUES (:id, :email, :password_hash, NULL, 0, NOW())
        """)
        
        db.execute(insert_query, {
            "id": user_id,
            "email": admin_email,
            "password_hash": password_hash
        })
        
        db.commit()
        print(f"✅ Admin user created successfully!")
        print(f"   Email: {admin_email}")
        print(f"   Password: {admin_password}")
        print(f"   User ID: {user_id}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        db.rollback()
        return False
    finally:
        db.close()

def setup_admin_env():
    """Show how to set up the admin environment variable."""
    admin_email = "admin@fyp.com"
    
    print("\n" + "="*60)
    print("📝 ENVIRONMENT SETUP")
    print("="*60)
    
    print("\nTo enable admin access, add this line to your .env file:")
    print(f"ADMIN_EMAILS={admin_email}")
    
    print("\nOr if you have multiple admins:")
    print(f"ADMIN_EMAILS=admin@fyp.com,admin2@fyp.com,admin3@fyp.com")
    
    # Check current environment
    current_admin_emails = os.getenv("ADMIN_EMAILS", "")
    if current_admin_emails:
        print(f"\n✅ Current ADMIN_EMAILS: {current_admin_emails}")
        if admin_email in current_admin_emails:
            print(f"✅ {admin_email} is already configured as admin!")
        else:
            print(f"⚠️  Add {admin_email} to ADMIN_EMAILS to enable admin access")
    else:
        print(f"\n⚠️  ADMIN_EMAILS not set in .env file")
        
        # Try to update .env file
        try:
            env_path = ".env"
            if os.path.exists(env_path):
                with open(env_path, "a") as f:
                    f.write(f"\n# Admin Configuration\nADMIN_EMAILS={admin_email}\n")
                print(f"✅ Added ADMIN_EMAILS to {env_path}")
                print("🔄 Restart the backend server to apply changes")
            else:
                print(f"❌ .env file not found. Please create one and add: ADMIN_EMAILS={admin_email}")
        except Exception as e:
            print(f"❌ Failed to update .env file: {e}")

def main():
    print("🔧 FYP Admin User Setup")
    print("="*60)
    
    success = create_admin_user()
    
    if success:
        setup_admin_env()
        
        print("\n" + "="*60)
        print("🎉 SETUP COMPLETE!")
        print("="*60)
        print("\n📋 Next Steps:")
        print("1. Restart the backend server (uvicorn) to load new environment")
        print("2. Login to the frontend with: admin@fyp.com / Admin123!")
        print("3. Navigate to /admin/users to test the admin interface")
        print("4. **IMPORTANT**: Change the admin password after first login!")
        
    else:
        print("\n❌ Setup failed. Please check the error messages above.")

if __name__ == "__main__":
    main()