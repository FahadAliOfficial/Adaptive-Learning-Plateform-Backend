"""
Database Migration: Add status column to users table

Adds account status tracking for admin user management.
Default is 'active' for all existing and new users.
"""
import sys
import os

# Add parent directory to path to import database module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text


def _column_exists(conn) -> bool:
    """Check if the status column exists (Postgres or SQLite)."""
    try:
        query = text("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'status'
        """)
        result = conn.execute(query).fetchone()
        return bool(result and result[0] > 0)
    except Exception:
        query = text("""
            SELECT COUNT(*) as count
            FROM pragma_table_info('users')
            WHERE name = 'status'
        """)
        result = conn.execute(query).fetchone()
        return bool(result and result[0] > 0)


def migrate():
    """Add status column to users table."""
    print("🔧 Starting migration: add_user_status_column")

    try:
        with engine.connect() as conn:
            if _column_exists(conn):
                print("✅ Column 'status' already exists. Skipping migration.")
                return True

            alter_query = text("ALTER TABLE users ADD COLUMN status VARCHAR DEFAULT 'active'")
            conn.execute(alter_query)

            update_query = text("UPDATE users SET status = 'active' WHERE status IS NULL")
            conn.execute(update_query)
            conn.commit()

            print("✅ Successfully added 'status' column to users")
            return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False


def rollback():
    """Rollback status column (not supported by SQLite)."""
    print("🔄 Rolling back migration: add_user_status_column")
    print("⚠️ Manual rollback required: recreate table without status column")
    return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        success = rollback()
    else:
        success = migrate()

    if success:
        print("\n✅ Migration completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Migration failed!")
        sys.exit(1)
